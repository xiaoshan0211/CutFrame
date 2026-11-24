import os,unittest,copy,json
from pathlib import Path
class AnnotationHttpTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('CUTFRAME_STATE'):self.skipTest('请使用隔离测试运行器')
        from app import app,PORT,TOKEN
        self.client=app.test_client();self.headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN};tree=json.loads((Path(__file__).parent/'rules/label-tree-v0.2.json').read_text('utf-8'));self.content=dict(schema_version=1,label_tree=tree,rules=[dict(id='http-test',suite='隔离测试',text='测试句',target_duration=1,illustration_only=True,unprovable='仅示意',notes='',must=[dict(dimension='画面类型',tags=['V05'],raw='V05',notes='',structure_status='人工编辑')],prefer=[],forbid=[])])
    def call(self,url,data=None,method='post'):
        r=getattr(self.client,method)(url,json=data,headers=self.headers);self.assertEqual(r.status_code,200,r.json);return r.json
    def test_V13_api_full_cycle_export_import(self):
        d=self.call('/api/annotation/rules',{'content':self.content,'name':'隔离测试草稿'});base='/api/annotation/rules/'+d['id'];changed=copy.deepcopy(d['content']);changed['rules'][0]['notes']='已编辑';d=self.call(base,{'content':changed,'expected_hash':d['content_hash']},'put')
        self.assertEqual(self.call(base+'/validate',{})['issues'],[])
        r=self.client.post(base+'/publish',json={},headers=self.headers);self.assertEqual(r.status_code,400)
        d=self.call(base+'/confirm',{'reviewer':'测试确认人','expected_hash':d['content_hash']});d=self.call(base+'/publish',{});self.assertEqual(d['status'],'已发布')
        self.assertEqual(self.call(base,method='get')['content'],changed)
        self.assertEqual(self.client.put(base,json={'content':changed},headers=self.headers).status_code,400)
        exported=self.client.get(base+'/export',headers=self.headers);self.assertEqual(exported.json,changed)
        imported=self.call('/api/annotation/rules',{'content':exported.json,'name':'导出后重导入'});self.assertEqual(imported['status'],'草稿');self.assertNotEqual(imported['id'],d['id'])
        self.call('/api/annotation/bindings',{'task_id':'http-test-task','package_id':d['id']});self.assertEqual(self.call('/api/annotation/bindings/http-test-task',method='get')['content_hash'],d['content_hash'])
        self.assertEqual(self.call('/api/annotation/overview',method='get')['counts']['restrictions'],0)
    def test_old_tabs_csp_static_and_write_security(self):
        r=self.client.get('/',headers=self.headers);text=r.get_data(as_text=True)
        import re
        self.assertEqual(re.findall(r'data-view="([^"]+)"',text),['compose','exports'])
        self.assertIn('<main id="compose" class="view active">',text)
        for removed in ('id="cut"','annotation-rules.js','pilot-library.js','/classification-selection','加入单条成片','导出当前片段'):
            self.assertNotIn(removed,text)
        for route in ('/api/clips','/api/annotation/overview','/classification-selection','/api/local/suggestion?text=test'):
            self.assertEqual(self.client.get(route,headers=self.headers).status_code,200,route)
        self.assertIn("script-src 'self'",r.headers['Content-Security-Policy']);self.assertNotIn('<script>',text)
        for file in ('annotation-rules.js','annotation-rules.css'):self.assertEqual(self.client.get('/static/'+file,headers=self.headers).status_code,200)
        for suffix in ('/rules','/bindings'):
            self.assertEqual(self.client.post('/api/annotation'+suffix,json={}).status_code,403)
if __name__=='__main__':unittest.main()
