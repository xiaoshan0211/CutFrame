"""独立进程加载用户确认的G版模型；输入输出仅由本地服务指定。"""
import os, sys, json, hashlib
from pathlib import Path
request_path=Path(sys.argv[1]).resolve()
job=json.loads(request_path.read_text('utf-8'))
approved=job['approved']['selected']
repo=Path(approved['gpt_model']).parents[2]
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['PATH']=str(repo/'runtime')+os.pathsep+os.environ['PATH']
sys.path[:0]=[str(repo),str(repo/'GPT_SoVITS')]
os.chdir(repo)
import torch, numpy as np, soundfile as sf, importlib
from GPT_SoVITS.TTS_infer_pack.TTS import TTS,TTS_Config
module=importlib.import_module('GPT_SoVITS.TTS_infer_pack.TTS')
original_detector=module.get_sovits_version_from_path_fast
def detect(path):
    if Path(path).resolve()==Path(approved['sovits_model']).resolve():
        weights=module.load_sovits_new(path)
        assert weights['config']['model']['version']=='v2Pro' and 'sv_emb.weight' in weights['weight']
        return 'v2','v2Pro',False
    return original_detector(path)
module.get_sovits_version_from_path_fast=detect
torch.set_num_threads(4)
cfg=TTS_Config({'custom':dict(device='cuda',is_half=False,version='v2Pro',t2s_weights_path=approved['gpt_model'],vits_weights_path=approved['sovits_model'],bert_base_path=str(repo/'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large'),cnhuhbert_base_path=str(repo/'GPT_SoVITS/pretrained_models/chinese-hubert-base'))})
cfg.configs_path=str(request_path.parent/'inference.yaml')
tts=TTS(cfg)
assert tts.is_v2pro
params=dict(approved['parameters']);params['text']=job['text']
# 长稿按原有标点分段推理，避免整段生成时跳读；不改写输入原稿。
if len(job['text'])>100:
    params['text_split_method']='cut5'
waves=list(tts.run(params))
if not waves: raise RuntimeError('没有生成音频')
sr=waves[0][0]; audio=np.concatenate([w[1] for w in waves])
if len(audio)/sr<max(1,len(job['text'])*.035) or not np.isfinite(audio).all():
    raise RuntimeError('配音异常短或含无效采样，未发布，请查看任务日志')
output=request_path.parent/'voice.wav'
sf.write(output,audio,sr,subtype='PCM_16')
record=dict(text=job['text'],parameters=params,gpt_model=approved['gpt_model'],sovits_model=approved['sovits_model'],precision='float32',seconds=len(audio)/sr,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),review='待人工完整试听')
(request_path.parent/'generation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
