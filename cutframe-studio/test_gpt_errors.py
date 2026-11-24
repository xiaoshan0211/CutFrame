import io,json,unittest,urllib.error
from unittest.mock import patch
from test_gpt_provider import GPTTests
from gpt_provider import call_gpt,budget_db,budget_status,GPTRequestError


class ErrorTests(GPTTests):
    def test_tls_before_send_releases_reserve(self):
        def fail(req,mark):
            mark('建立TLS连接')
            raise urllib.error.URLError('SSL EOF')
        with patch('gpt_provider.open_tracked_request',side_effect=fail) as mocked:
            with self.assertRaises(GPTRequestError):call_gpt(self.rule,self.ledger,'secret',[],{},0,2,{})
            self.assertEqual(mocked.call_count,1)
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],0)
        self.assertEqual(budget_status(self.ledger,self.rule)['remaining_usd'],self.rule['budget']['total_cap_usd'])
    def test_disconnect_after_send_keeps_reserve(self):
        def fail(req,mark):
            mark('发送HTTP请求')
            raise urllib.error.URLError('SSL EOF')
        with patch('gpt_provider.open_tracked_request',side_effect=fail) as mocked:
            with self.assertRaises(GPTRequestError):call_gpt(self.rule,self.ledger,'secret',[],{},0,2,{})
            self.assertEqual(mocked.call_count,1)
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],1)
    def test_json_mode_instruction_in_input(self):
        def transport(body):
            self.assertEqual(body['text']['format']['type'],'json_object')
            self.assertIn('JSON',body['input'][0]['content'][0]['text'])
            return {'usage':{'input_tokens':100,'output_tokens':10},'output':[{'content':[{'type':'output_text','text':'{"segments":[]}'}]}]}
        call_gpt(self.rule,self.ledger,'secret',[],{'text':'施工'},0,2,{},transport)
    def latest(self):
        with budget_db(self.ledger) as db:r=db.execute('select data from calls order by created desc limit 1').fetchone()
        return json.loads(r[0])
    def test_http_error_details_and_redaction(self):
        def transport(body):
            raise urllib.error.HTTPError('https://api.openai.com/v1/responses',400,'bad',{'x-request-id':'req-test'},io.BytesIO(json.dumps({'error':{'message':'invalid sk-test-secret','code':'invalid_parameter','param':'input'}}).encode()))
        with self.assertRaises(GPTRequestError) as ctx:call_gpt(self.rule,self.ledger,'sk-test-secret',[],{},0,2,{},transport)
        d=self.latest();self.assertEqual(d['error']['http_status'],400);self.assertEqual(d['request_id'],'req-test')
        self.assertNotIn('sk-test-secret',json.dumps(d));self.assertNotIn('sk-test-secret',str(ctx.exception))
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],1)
    def test_invalid_json_usage_preserved(self):
        def transport(body):return {'usage':{'input_tokens':100,'output_tokens':50},'id':'res-test','output':[{'content':[{'type':'output_text','text':'not-json'}]}]}
        with self.assertRaises(GPTRequestError):call_gpt(self.rule,self.ledger,'secret',[],{},0,2,{},transport)
        d=self.latest();self.assertEqual(d['error']['stage'],'解析模型JSON');self.assertEqual(d['response_id'],'res-test');self.assertEqual(d['usage']['input_tokens'],100)
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],0)
    def test_incomplete_output_classified_without_retry(self):
        calls=[]
        def transport(body):
            calls.append(1);return {'usage':{'input_tokens':100,'output_tokens':1800},'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}
        with self.assertRaisesRegex(GPTRequestError,'max_output_tokens'):call_gpt(self.rule,self.ledger,'secret',[],{},0,2,{},transport)
        self.assertEqual(len(calls),1);self.assertEqual(self.latest()['response_status'],'incomplete')
    def test_local_serialization_failure_does_not_reserve(self):
        with self.assertRaises(ValueError):call_gpt(self.rule,self.ledger,'secret',[],{'bad':float('nan')},0,2,{},lambda body:self.fail('本地无效数据不得发请求'))
        self.assertEqual(budget_status(self.ledger,self.rule)['remaining_usd'],self.rule['budget']['total_cap_usd'])


if __name__=='__main__':unittest.main()
