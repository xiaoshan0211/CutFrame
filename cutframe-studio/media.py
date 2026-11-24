"""本地媒体处理。时间值校验改编自 CutFrame，版权见 THIRD_PARTY_NOTICES.md。"""
from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def is_portrait_916(meta):
    try:
        w,h=float(meta['width']),float(meta['height'])
        sar=str(meta.get('sar') or '1:1').split(':')
        if len(sar)==2 and float(sar[1])>0:w*=float(sar[0])/float(sar[1])
        angle=float(meta.get('rotation') or 0)%180
        if abs(angle-90)<.01:w,h=h,w
        elif min(angle,180-angle)>.01:return False
        return w>0 and h>0 and abs(w*16-h*9)<.01
    except (ValueError,TypeError,KeyError,ZeroDivisionError):return False

def seconds(value, label='时间'):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}必须是有效秒数')
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{label}必须是有限的非负秒数')
    return value

def probe(binary, path, uploaded=False):
    formats=['-protocol_whitelist','file','-format_whitelist','mov,matroska,webm,avi,asf,mpegts'] if uploaded else []
    r = subprocess.run([binary, '-v', 'error', *formats,'-show_format', '-show_streams', '-of', 'json', str(path)],
                       capture_output=True, timeout=45, creationflags=FLAGS)
    if r.returncode:
        raise ValueError(r.stderr.decode('utf-8', 'replace')[-2000:])
    raw = json.loads(r.stdout)
    videos = [s for s in raw.get('streams', []) if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    audio = [s for s in raw.get('streams', []) if s['codec_type'] == 'audio']
    v = videos[0] if videos else {}
    duration = seconds(raw.get('format', {}).get('duration', v.get('duration', 0)), '时长')
    return dict(duration=duration, width=v.get('width'), height=v.get('height'), sar=v.get('sample_aspect_ratio','1:1'), codec=v.get('codec_name'),
                video_index=v.get('index',0), audio_index=audio[0].get('index') if audio else None,
                pixel=v.get('pix_fmt'), transfer=v.get('color_transfer'), fps=v.get('avg_frame_rate'),
                audio=bool(audio), audio_codec=audio[0].get('codec_name') if audio else None,
                rotation=next((s.get('rotation', 0) for s in v.get('side_data_list', []) if 'rotation' in s), v.get('tags',{}).get('rotate',0)))

def validate_range(start, end, duration):
    start, end = seconds(start, '入点'), seconds(end, '出点')
    if end <= start or end > duration + .02:
        raise ValueError('需要 0 ≤ 入点 < 出点 ≤ 素材时长')
    return start, end

def sdr_filter(meta):
    if meta.get('transfer') in ('arib-std-b67', 'smpte2084'):
        return 'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,'
    return ''

def encoder_args(config):
    codec = config.get('encoder', 'h264_mf')
    if codec == 'libx264':
        return ['-c:v', codec, '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p']
    return ['-c:v', codec, '-b:v', '8M', '-pix_fmt', 'yuv420p']

def clip_command(config, path, output, start, end, mode, meta, proxy=False):
    cmd = [config['ffmpeg'], '-hide_banner', '-nostdin', '-n', '-ss', str(start), '-i', str(path),
           '-t', str(end-start), '-map', '0:'+str(meta.get('video_index',0)), '-map', '0:a:0?', '-sn', '-dn']
    if mode == 'copy':
        cmd += ['-c', 'copy', '-avoid_negative_ts', 'make_zero']
    else:
        vf = sdr_filter(meta)
        vf += 'scale=960:960:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1' if proxy else 'scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1'
        cmd += ['-vf', vf] + encoder_args(config) + ['-c:a', 'aac', '-b:a', '192k']
    return cmd + ['-movflags', '+faststart', str(output)]
