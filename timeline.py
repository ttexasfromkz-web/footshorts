"""Plan full source segments and replays before encoding any frames."""
import math

def is_goal(c):
    return c.get('kind')=='goal' or c.get('goal_at') is not None or any(x in c.get('reason','').lower() for x in ('есеп өзгерді','гол','goal'))

def segment_duration(c):
    speed=float(c.get('speed',1))
    if not math.isfinite(speed) or not .5<=speed<=2:
        raise ValueError('Жылдамдық: 0.5–2.0.')
    raw=(float(c['end'])-float(c['start']))/speed
    if not math.isfinite(raw) or raw<=0:raise ValueError('Үзінді уақыты қате.')
    return math.ceil(raw*30-1e-7)/30

def plan_timeline(clips,limit=180,score_card=True,replays=True,replay_speed=.5,intro_seconds=0):
    limit=float(limit)
    if not math.isfinite(limit) or not 4<=limit<=180:raise ValueError('Уақыт шегі: 4–180 секунд.')
    if not .5<=float(replay_speed)<=1:raise ValueError('Қайталау жылдамдығы: 0.5–1.0.')
    intro_seconds=float(intro_seconds)
    if intro_seconds not in (0,3):raise ValueError('Кіріспе: 0 немесе 3 секунд.')
    budget=limit-(3 if score_card else 0)-intro_seconds-.1
    mains=[];replay_map={};notes=[]
    for i,c in enumerate(clips):
        main=dict(c,index=i,is_replay=False,speed=float(c.get('speed',1)))
        main['kind']='goal' if is_goal(c) else 'highlight'
        if main['kind']=='goal':
            g=float(c.get('goal_at',max(c['start'],c['end']-8)))
            if not math.isfinite(g) or not c['start']<=g<c['end']:
                raise ValueError('Гол уақыты өз үзіндісінің ішінде болуы керек.')
            main['goal_at']=g
            if replays:
                a=max(c['start'],g-4);b=min(c['end'],g+3)
                if b-a>=.5:
                    replay_map[i]=dict(main,start=a,end=b,speed=float(replay_speed),is_replay=True)
        mains.append(main)
    goals=[c for c in mains if c['kind']=='goal']
    extras=[c for c in mains if c['kind']!='goal']
    used=sum(segment_duration(c) for c in goals)
    if used>budget+.001:raise ValueError('Гол үзінділерінің өзі шекке сыймады. Уақыттарын қысқартыңыз немесе шекті өсіріңіз.')
    selected={c['index'] for c in goals};replay_selected=set()
    # Preserve all goal source footage, then add whole replays. Never crop a replay to fill a gap.
    for c in goals:
        r=replay_map.get(c['index'])
        if r and used+segment_duration(r)<=budget+.001:
            replay_selected.add(c['index']);used+=segment_duration(r)
        elif r:notes.append('Толық қайталау шекке сыймағандықтан қосылмады: '+str(c['index']+1))
    for c in sorted(extras,key=lambda c:c.get('priority',0),reverse=True):
        if used+segment_duration(c)<=budget+.001:
            selected.add(c['index']);used+=segment_duration(c)
        else:notes.append('Қосымша сәт шекке сыймады: '+str(c['index']+1))
    result=[]
    for c in sorted(mains,key=lambda c:c['start']):
        if c['index'] not in selected:continue
        result.append(c)
        if c['index'] in replay_selected:result.append(replay_map[c['index']])
    if not result:raise ValueError('Таңдалған уақытқа бүтін үзінді сыймады.')
    return dict(segments=result,duration=sum(segment_duration(c) for c in result)+(3 if score_card else 0)+intro_seconds,notes=notes)
