"""预测结束后独立对照旧审核，并显式导入试标轮次；不会替人确认。"""
import argparse,json,collections
from pathlib import Path
from annotation_store import Store
from pilot_library import Pilot
ROOT=Path(__file__).resolve().parent.parent

def main():
 p=argparse.ArgumentParser();p.add_argument('--round-dir',type=Path,required=True);p.add_argument('--name',required=True);p.add_argument('--manifest',type=Path);a=p.parse_args();ref=ROOT/'参考资料/video-harness-lab-references';pred=a.round_dir/'predictions.jsonl';rows=[json.loads(x) for x in pred.read_text('utf-8').splitlines() if x.strip()];latest={r['sample_id']:r for r in rows if r.get('code') and not r.get('error')}
 score=dict(samples=len(latest),codes=dict(collections.Counter(r['code'] for r in latest.values())),errors=[r for r in rows if r.get('error')],type='新样本，待人工独立审核' if a.manifest else '旧50段人工答案的开发样本复验，不是独立验收准确率',money=0)
 if not a.manifest:
  gold=json.loads((ref/'素材标注总纲-20261116/试标50段/审核结果.json').read_text('utf-8-sig'))['结果'];expected={r['seg']:r['机器画面类型'] if r['verdict']=='对' else r['fix'] for r in gold};score['matching']=sum(r['code']==expected.get(r['sample_id']) for r in latest.values());score['mismatches']=[dict(sample_id=r['sample_id'],predicted=r['code'],old_review=expected[r['sample_id']],evidence=r.get('evidence','')) for r in latest.values() if r['code']!=expected.get(r['sample_id'])]
 store=Store(ROOT/'local/cutframe/annotation.sqlite3');pilot=Pilot(store);score['round_id']=pilot.import_round(a.name,pred,ref,a.manifest);score['name']=a.name;(a.round_dir/'evaluation.json').write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(score,ensure_ascii=False))
if __name__=='__main__':main()
