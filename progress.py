"""Measured pipeline progress; no invented ticking percentages."""
import math
import re
import time

STAGES=[('download','Жүктеу',0,20),('analyze','Талдау',20,45),
        ('logos','Логотип іздеу',45,48),('render','Монтаж',48,94),('save','Сақтау',94,100)]


class Progress:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.reset()

    def reset(self):
        now=self.clock();self.started=now;self.changed=now;self.stage_started=now
        self.stage='download';self.fraction=0.;self.detail='Дайындалуда';self.running=True

    def observe(self,message):
        message=str(message)
        if message=='@progress:reset':self.reset();return True
        if message.startswith('@progress:'):
            _,stage,value,*detail=message.split(':',3)
            if stage not in {s[0] for s in STAGES}:return True
            try:fraction=float(value)
            except ValueError:return True
            if not math.isfinite(fraction):return True
            self.set(stage,fraction,detail[0] if detail else '')
            return True
        m=re.search(r'Жүктелуде:\s*([\d.]+)%',message)
        if m:self.set('download',float(m[1])/100,message)
        m=re.search(r'Есепті оқу: (\d+)/(\d+)',message)
        if m and int(m[2]):self.set('analyze',.85*int(m[1])/int(m[2]),message)
        return False

    def set(self,stage,fraction,detail=''):
        if stage!=self.stage:
            self.stage=stage;self.stage_started=self.clock();self.fraction=0.
        self.fraction=max(self.fraction,min(1.,max(0.,fraction)))
        self.changed=self.clock();self.detail=detail

    def finish(self,success):
        self.running=False
        if success:self.set('save',1.,'Дайын')

    def snapshot(self):
        now=self.clock()
        key,label,start,end=next(s for s in STAGES if s[0]==self.stage)
        percent=start+(end-start)*self.fraction
        elapsed=max(0,int(now-self.started))
        # Stage-only ETA: download speed cannot predict OCR or encoding time.
        eta='Қалған уақыт: есептелуде'
        stage_elapsed=now-self.stage_started
        if self.running and .02<self.fraction<1 and stage_elapsed>=2:
            remaining=stage_elapsed*(1-self.fraction)/self.fraction
            eta=f'Осы кезеңге шамамен: {int(remaining)//60:02}:{int(remaining)%60:02}'
        if self.fraction>=1:eta='Кезең аяқталды'
        quiet=max(0,int(now-self.changed))
        detail=self.detail+(' • Соңғы мәлімет: '+str(quiet)+' сек бұрын' if self.running and quiet>=15 else '')
        return dict(percent=percent,text=f'{label} • {percent:.0f}% • Өткен уақыт: {elapsed//60:02}:{elapsed%60:02} • {eta}',detail=detail)
