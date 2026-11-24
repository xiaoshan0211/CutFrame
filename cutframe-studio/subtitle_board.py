"""逐条字幕选片的导出约束；仅阻止错误，不替用户补镜头或改时间。"""
import math
import copy

def continue_gap_shots(tasks,shots,duration,source_durations=None):
    """仅派生播放/渲染范围，不修改人工选择、字幕时间或确认签名。"""
    result=copy.deepcopy(shots)
    if tasks and tasks[0]['start']>.001:raise ValueError('片头没有上一镜头，需手动选片')
    for i,t in enumerate(tasks):
        to=tasks[i+1]['start'] if i+1<len(tasks) else duration
        extra=to-t['end']
        if extra<-.001:raise ValueError(f'第{i+1}条与下一条时间重叠')
        if extra<=.001:continue
        ss=[s for s in result if s.get('task_ids')==[t['id']]]
        if not ss or abs(ss[-1]['timeline_start']+ss[-1]['end']-ss[-1]['start']-t['end'])>.001:raise ValueError(f'第{i+1}条尚未完整选片，不能续播停顿')
        last=ss[-1];limit=(source_durations or {}).get(last.get('asset_id'),last.get('source_duration',0))
        if not isinstance(limit,(int,float)) or not math.isfinite(limit) or last['end']+extra>limit+.001:raise ValueError(f'第{i+1}条「{t["text"]}」原片剩余不足，停顿需续播 {extra:.2f} 秒；请提前镜头开始位置或更换素材')
        last['subtitle_end']=last['end'];last['gap_extension']=extra;last['end']+=extra
    return result

def validate_subtitle_board(board, shots, cues, duration, workflow, settings, imports):
    tasks=board.get('tasks',[])
    if len(tasks)!=len(cues):raise ValueError('字幕任务数量已变化，请回第四步同步')
    off=settings['subtitle_offset'];at=0.;used=[];continuing=board.get('gap_policy')=='continue_previous'
    for t,c in zip(tasks,cues):
        if t['text']!=c['text'] or abs(t['start']-c['start']-off)>.001 or abs(t['end']-c['end']-off)>.001:raise ValueError('任务与已保存字幕不一致，请同步选片任务')
        if abs(t['start']-at)>.001:
            if not continuing or not used or t['start']<at:raise ValueError(f'字幕时间间隙或重叠 {at:.2f}–{t["start"]:.2f} 秒，尚未决定处理方式')
            at=t['start']
        ss=[s for s in shots if s.get('task_ids')==[t['id']]]
        if not 1<=len(ss)<=2:raise ValueError('每条字幕必须对应一至两个镜头')
        if t.get('planned_shots')==2 and len(ss)!=2:raise ValueError('双镜字幕还缺一个镜头')
        for s in ss:
            pos=s.get('timeline_start')
            if not isinstance(pos,(int,float)) or not math.isfinite(pos) or abs(pos-at)>.001:raise ValueError('镜头位置与字幕时间不连续')
            if s.get('fallback') and not s.get('fallback_confirmed'):raise ValueError('替代画面尚未确认')
            if s['end']>s.get('available_end',s['end'])+.001:raise ValueError('镜头超出已选源片段')
            at+=s['end']-s['start'];used.append(s)
        if abs(at-t['end'])>.001:raise ValueError('镜头时长与本条字幕不一致')
    if used!=shots:raise ValueError('镜头顺序或任务关联无效')
    if abs(at-duration)>.001 and (not continuing or at>duration):raise ValueError(f'末尾时间间隙 {at:.2f}–{duration:.2f} 秒，尚未决定处理方式')

def frame_duration(start,end,fps):
    frames=round(end*fps)-round(start*fps)
    if frames<1:raise ValueError('镜头短于输出的一帧，请调整镜头切点')
    return frames/fps
