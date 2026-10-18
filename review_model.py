"""Validated source-time edits and undo history for the review window."""
import copy
import math
import core


def interpolate(points,t,key,default=.5):
    if not points:return default
    ordered=sorted(points,key=lambda p:p['time'])
    if t<=ordered[0]['time']:return ordered[0][key]
    for a,b in zip(ordered,ordered[1:]):
        if t<=b['time']:
            q=(t-a['time'])/max(b['time']-a['time'],1e-9)
            return a[key]+q*(b[key]-a[key])
    return ordered[-1][key]


def validate_camera(clip):
    zoom=float(clip.get('zoom',1))
    if not math.isfinite(zoom) or not 1<=zoom<=2:raise ValueError('Үлкейту: 1–2.')
    points=clip.get('focus_points',[])
    if not isinstance(points,list) or len(points)>80:raise ValueError('Камера: ең көбі 80 нүкте.')
    seen=set()
    for p in points:
        t,x,y=(float(p[k]) for k in ('time','x','y'))
        if not all(math.isfinite(v) for v in (t,x,y)) or not clip['start']<=t<clip['end'] or not 0<=x<=1 or not 0<=y<=1:
            raise ValueError('Камера нүктесі үзінді ішінде болуы керек.')
        if t in seen:raise ValueError('Бір уақытта екі камера нүктесі бар.')
        seen.add(t)


class ReviewModel:
    def __init__(self,clips,duration):
        self.clips=copy.deepcopy(clips);self.duration=float(duration);self.history=[]

    def change(self,index,fn):
        candidate=copy.deepcopy(self.clips[index]);fn(candidate)
        core.validate_clips([candidate],self.duration);validate_camera(candidate)
        g=candidate.get('goal_at')
        if g is not None and not candidate['start']<=float(g)<candidate['end']:
            raise ValueError('Гол белгісі шекарадан тыс қалды. Алдымен гол белгісін түзетіңіз.')
        self.history.append(copy.deepcopy(self.clips));self.history=self.history[-50:];self.clips[index]=candidate

    def trim(self,index,start,end):
        start,end=float(start),float(end)
        def edit(c):
            old=c.get('focus_points',[])
            if old:
                inside=[p for p in old if start<=p['time']<end]
                times=sorted({start,max(start,end-.001),*(p['time'] for p in inside)})
                c['focus_points']=[dict(time=t,x=interpolate(old,t,'x'),y=interpolate(old,t,'y')) for t in times]
            c.update(start=start,end=end)
        self.change(index,edit)

    def mark_goal(self,index,time):
        self.change(index,lambda c:c.update(goal_at=float(time),kind='goal',reason='Гол'))

    def clear_goal(self,index):
        def edit(c):c.pop('goal_at',None);c.update(kind='highlight',reason='Қызықты сәт')
        self.change(index,edit)

    def focus(self,index,time,x,y):
        def edit(c):
            points=[p for p in c.get('focus_points',[]) if abs(p['time']-time)>.04]
            points.append(dict(time=float(time),x=float(x),y=float(y)))
            c['focus_points']=sorted(points,key=lambda p:p['time'])
        self.change(index,edit)

    def delete(self,index):
        self.history.append(copy.deepcopy(self.clips));self.clips.pop(index)

    def undo(self):
        if self.history:self.clips=self.history.pop()

    def validate(self):
        core.validate_clips(self.clips,self.duration)
        for c in self.clips:validate_camera(c)
        return copy.deepcopy(self.clips)
