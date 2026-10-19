"""Conservative score/audio/visual fusion; no claim of semantic goal recognition."""
import math
import numpy as np


def score_sample_times(duration):
    # Stable-score confirmation requires successive observations <=20s apart.
    # Keep this bound even for a full 90-minute broadcast.
    step=min(8.,max(2.,duration/240.))
    return sorted({*np.arange(0,duration,step).tolist(),*np.arange(max(0,duration-45),duration,2.).tolist()})


def refinement_times(readings,duration):
    """Densely sample scoreboard increases, including two goals between sparse reads."""
    from core import stable_scores
    events=stable_scores(readings);windows=[]
    for before,after in zip(events,events[1:]):
        difference=sum(after['score'])-sum(before['score'])
        if not 1<=difference<=3 or any(a<b for a,b in zip(after['score'],before['score'])):continue
        previous=[t for t,s in readings if s and tuple(s)==tuple(before['score']) and t<after['time']]
        last=max(previous,default=before['time'])
        start=max(0,after['time']-60,last-12);end=min(duration,after['time']+5)
        windows.extend(np.arange(start,end,1.).tolist())
    known={round(t,2) for t,_ in readings}
    return sorted({round(t,2) for t in windows if round(t,2) not in known})


def frame_signature(frame):
    import cv2
    small=cv2.resize(frame,(160,90));gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    # Ignore the score/time overlay; keep actual player/ball spatial structure.
    body=gray[18:];tiny=cv2.resize(body,(17,9))
    bits=(tiny[:,1:]>tiny[:,:-1]).flatten()
    hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    green=float(np.mean(cv2.inRange(hsv,(30,35,25),(95,255,255))>0))
    return {'bits':np.packbits(bits).tolist(),'mean':float(body.mean()/255),
            'contrast':float(body.std()/255),'green':green}


def bit_distance(a,b):
    if len(a)!=len(b):return math.inf
    return sum((int(x)^int(y)).bit_count() for x,y in zip(a,b))


def repeated_sequence(a,b):
    """Suppress only near-identical sequences, never arbitrary alternate angles."""
    if len(a)<5 or len(b)<5:return False
    pairs=list(zip(a,b))
    # A static field/black/title screen is not enough to call two plays identical.
    movement=max(bit_distance(a[0]['bits'],s['bits']) for s in a[1:])
    if movement<12:return False
    matches=sum(bit_distance(x['bits'],y['bits'])<=6 and abs(x['mean']-y['mean'])<.06
                and abs(x['green']-y['green'])<.12 for x,y in pairs)
    return matches>=max(5,math.ceil(len(pairs)*.85))


def inspect_candidates(video,candidates,cancel=None,log=print):
    import cv2
    from core import Cancelled
    cap=cv2.VideoCapture(str(video));result=[]
    # Process strongest moments first and bound extra decoding on long matches.
    ordered=sorted(candidates,key=lambda c:c['priority'],reverse=True)[:80]
    try:
        for i,c in enumerate(ordered):
            if cancel and cancel.is_set():raise Cancelled()
            samples=[];start=max(0,float(c['start']));end=max(start,float(c['end']))
            for t in np.linspace(start,end-.05,6):
                if cancel and cancel.is_set():raise Cancelled()
                cap.set(cv2.CAP_PROP_POS_MSEC,max(0,t)*1000);ok,frame=cap.read()
                if ok:samples.append(frame_signature(frame))
            item=dict(c);item['_signature']=samples
            cuts=sum(bit_distance(a['bits'],b['bits'])>45 for a,b in zip(samples,samples[1:]))
            field=any(s['green']>.22 for s in samples)
            motion=any(bit_distance(a['bits'],b['bits'])>12 for a,b in zip(samples,samples[1:]))
            item['evidence']={**item.get('evidence',{}),'field':field,'visual_activity':motion,'scene_changes':cuts}
            if field and motion:item['priority']+=4
            result.append(item)
            if i%10==0:log(f'Кадр белгілері: {i+1}/{len(ordered)} сәт')
    finally:cap.release()
    return result


def fuse_candidates(candidates,energy):
    energy=np.asarray(energy,dtype=float);merged=[]
    baseline=float(np.median(energy)) if len(energy) else 0.
    for candidate in candidates:
        c=dict(candidate);is_goal=c.get('kind')=='goal'
        evidence={**c.get('evidence',{}),'score_change':is_goal,'audio_peak':False}
        a=max(0,int(c['start']));b=min(len(energy),max(a,int(c['end'])))
        if b>a and baseline>0:
            peak=a+int(np.argmax(energy[a:b]));strong=energy[peak]>max(.015,baseline*1.25)
            evidence['audio_peak']=bool(strong)
            if strong:
                c['priority']+=10 if is_goal else 2
                if is_goal:c['goal_at']=min(c['end']-1,max(c['start'],float(peak)-1))
        c['evidence']=evidence
        # Audio/scene activity alone is a chance, never a confirmed goal.
        c['confidence']='score_confirmed' if is_goal else 'review_required'
        if not is_goal:c['kind']='highlight'
        merged.append(c)
    return merged


def remove_repeated_candidates(candidates):
    chosen=[];removed=0
    for c in sorted(candidates,key=lambda x:x['priority'],reverse=True):
        signature=c.get('_signature',[])
        # Independent confirmed scoreboard goals are never dropped by visual similarity.
        duplicate=c.get('kind')!='goal' and any(repeated_sequence(signature,p.get('_signature',[])) for p in chosen)
        if duplicate:removed+=1;continue
        chosen.append(c)
    return [{k:v for k,v in c.items() if k!='_signature'} for c in chosen],removed
