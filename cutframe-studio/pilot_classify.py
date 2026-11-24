"""离线复验固定50段；预测阶段不读取人工答案，不联网、不下载。"""
import os
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false')
import json,time,sys,argparse,hashlib
from pathlib import Path
import torch
from transformers import Qwen3VLForConditionalGeneration,AutoTokenizer,Qwen2VLImageProcessor
ROOT=Path(__file__).resolve().parent.parent

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int,default=50);p.add_argument('--max-pixels',type=int,default=512*512);p.add_argument('--manifest',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 reference=ROOT/'参考资料/video-harness-lab-references/素材标注总纲-20261116/试标50段';instructions=(reference/'看图标注任务说明_v0.2.md').read_text('utf-8-sig')
 type_rules=instructions.split('### 1. 画面类型（单选）',1)[1].split('### 2. 空间',1)[0]
 prompt='按四帧拼图中占多数的画面判断，不能靠目录、人物长相或材料名猜。'+type_rules+'\n本次只输出画面类型，不识别人名或材料品牌。根据图片按说明判定，输出唯一JSON对象：{"code":"V01至V24之一，或看不清","evidence":"一句可见依据"}。不要输出其他字段或Markdown。'
 (a.out/'prompt.txt').write_text(prompt,encoding='utf-8');modeldir=ROOT/'local/ai-models/qwen3-vl-4b-instruct'
 print('开始加载本机Qwen3-VL-4B',flush=True);model=Qwen3VLForConditionalGeneration.from_pretrained(str(modeldir),local_files_only=True,torch_dtype=torch.bfloat16,device_map='cuda',attn_implementation='sdpa');tokenizer=AutoTokenizer.from_pretrained(str(modeldir),local_files_only=True);image_processor=Qwen2VLImageProcessor.from_pretrained(str(modeldir),local_files_only=True,min_pixels=256*256,max_pixels=a.max_pixels)
 tokenizer.chat_template=json.loads((modeldir/'chat_template.json').read_text('utf-8'))['chat_template']
 done={}
 resultfile=a.out/'predictions.jsonl'
 if resultfile.exists():
  for line in resultfile.read_text('utf-8').splitlines():
   r=json.loads(line)
   if not r.get('error') and r.get('prompt_sha256')==hashlib.sha256(prompt.encode()).hexdigest() and r.get('max_pixels')==a.max_pixels:done[r['sample_id']]=r
 samples=[(p.stem,p) for p in sorted((reference/'frames').glob('seg_*.jpg'))]
 if a.manifest:samples=[(r['sample_id'],Path(r['frame_path'])) for r in (json.loads(x) for x in a.manifest.read_text('utf-8').splitlines() if x.strip())]
 for sample_id,path in samples[:a.limit]:
  if sample_id in done:continue
  started=time.monotonic();record=dict(sample_id=sample_id,model='Qwen3-VL-4B-Instruct（本机）',rule_version='v0.2',max_pixels=a.max_pixels,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),image_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
  try:
   from PIL import Image
   picture=Image.open(path).convert('RGB');messages=[{'role':'user','content':[{'type':'image','image':picture},{'type':'text','text':prompt}]}];text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True);vision=image_processor(images=[picture],return_tensors='pt');count=int(vision['image_grid_thw'][0].prod())//(image_processor.merge_size**2);text=text.replace('<|image_pad|>','<|image_pad|>'*count);inputs=tokenizer([text],return_tensors='pt');inputs.update(vision);inputs={k:v.to(model.device) for k,v in inputs.items()}
   with torch.inference_mode():generated=model.generate(**inputs,max_new_tokens=96,do_sample=False)
   answer=tokenizer.batch_decode(generated[:,inputs['input_ids'].shape[1]:],skip_special_tokens=True)[0];record['raw_response']=answer
   first,last=answer.find('{'),answer.rfind('}');value=json.loads(answer[first:last+1]);code=value.get('code')
   if code not in {f'V{i:02}' for i in range(1,25)}|{'看不清'}:raise ValueError('画面类型代码不合法')
   record.update(code=code,evidence=value.get('evidence',''))
  except Exception as e:
   record['error']=str(e);print('失败',sample_id,str(e)[:180],flush=True)
  record['seconds']=round(time.monotonic()-started,2)
  with resultfile.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
  print(sample_id,record.get('code',record.get('error','')),record['seconds'],flush=True)
 print('预测完成；人工答案未读入模型',flush=True)
if __name__=='__main__':main()
