"""Durable sequential jobs: one failed match cannot cancel the remaining queue."""
import copy
from pathlib import Path
import threading
import uuid
import json
import time
from progress import Progress
import core
import downloader
import updater


class BatchQueue:
    def __init__(self,path,clock=time.monotonic):
        self.path=Path(path);self.lock=threading.RLock();self.items=[];self.running=False
        self.clock=clock;self.active=None;self.started=None;self.initial_elapsed=0.;self.last_saved=0.;self.progress=None
        if self.path.is_file():
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.items=data.get('items',[])
            for item in self.items:
                if item.get('status')=='running':item['status']='queued'
        self.save()

    def save(self):
        with self.lock:updater.atomic_json(self.path,{'schema':1,'items':self.items})

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.items)

    def checkpoint(self,url,info):
        with self.lock:
            item=next(i for i in self.items if i['url']==url and i['status']=='running')
            item.update(directory=info['directory'],project_id=info['project_id'],checkpoint=info['stage'],title=info.get('title',item.get('title','')))
            self.save()

    def observe(self,url,message):
        with self.lock:
            if self.active is None or self.active['url']!=url:return
            self.progress.observe(message)
            self.active.update(progress=self.progress.snapshot()['percent'],stage=self.progress.stage,
                               elapsed_seconds=self.initial_elapsed+max(0,self.clock()-self.started))
            if self.clock()-self.last_saved>=1:self.save();self.last_saved=self.clock()

    def summary(self):
        with self.lock:
            durations=[i.get('elapsed_seconds',0) for i in self.items if i['status']=='done' and i.get('elapsed_seconds',0)>0]
            pending=sum(i['status']=='queued' for i in self.items)
            remaining=pending+(max(0,1-self.active.get('progress',0)/100) if self.active else 0)
            eta=(sum(durations)/len(durations))*remaining if durations else None
            return dict(total=len(self.items),done=sum(i['status']=='done' for i in self.items),
                        errors=sum(i['status']=='error' for i in self.items),pending=pending,eta_seconds=eta,
                        estimating=bool(remaining and not durations))

    def restart(self,ids):
        with self.lock:
            if self.running:raise ValueError('Кезек аяқталған соң қайталаңыз.')
            for item in self.items:
                if item['id'] in ids:
                    for key in ('project_id','checkpoint','progress','elapsed_seconds','stage'):item.pop(key,None)
                    item.update(status='queued',error='',directory='')
            self.save()

    def add(self,text):
        with self.lock:
            if self.running:raise ValueError('Кезек жүріп жатыр. Аяқталған соң қосыңыз.')
            existing={i['url'] for i in self.items if i['status'] in ('queued','running')}
            for line in text.splitlines():
                raw=line.strip()
                if not raw:continue
                error=''
                try:url=downloader.normalize_url(raw)
                except ValueError as e:url=raw;error=str(e)
                if url in existing:continue
                self.items.append(dict(id=uuid.uuid4().hex,url=url,status='error' if error else 'queued',
                                       error=error,directory='',title=''))
                existing.add(url)
            self.save()

    def add_files(self,paths):
        """Keep full local paths (including spaces) and snapshot each as one job."""
        with self.lock:
            if self.running:raise ValueError('Кезек жүріп жатыр. Аяқталған соң қосыңыз.')
            paths=[Path(p).expanduser().resolve() for p in paths]
            for path in paths:
                if not path.is_file():raise ValueError('Видео файлы табылмады: '+str(path))
            existing={i['url'] for i in self.items if i['status'] in ('queued','running')}
            for path in paths:
                if str(path) in existing:continue
                self.items.append(dict(id=uuid.uuid4().hex,url=str(path),source_type='file',
                    status='queued',error='',directory='',title=path.stem))
                existing.add(str(path))
            self.save()

    def remove(self,ids):
        with self.lock:
            if self.running:raise ValueError('Кезек жүріп жатыр. Аяқталған соң өшіріңіз.')
            self.items=[i for i in self.items if i['id'] not in ids]
            self.save()

    def retry_failed(self):
        with self.lock:
            if self.running:return
            for item in self.items:
                if item['status'] in ('error','cancelled'):item.update(status='queued',error='')
            self.save()

    def clear_done(self):
        with self.lock:
            if self.running:return
            self.items=[i for i in self.items if i['status']!='done'];self.save()

    def run(self,process,cancel,notify=lambda _:None):
        with self.lock:
            if self.running:raise ValueError('Кезек қазірдің өзінде жүріп жатыр.')
            self.running=True
        results=[]
        try:
            for item in self.items:
                if cancel.is_set():break
                if item['status']!='queued':continue
                self.active=item;self.started=self.clock();self.initial_elapsed=item.get('elapsed_seconds',0)
                self.progress=Progress(self.clock)
                item.update(status='running',error='');self.save();notify(self.snapshot())
                try:
                    result=process(item['url'])
                    item.update(status='done',directory=result['directory'],title=result['project']['title'])
                    results.append(result)
                except core.Cancelled:
                    item.update(status='cancelled',error='Пайдаланушы тоқтатты.')
                    item['elapsed_seconds']=self.initial_elapsed+max(0,self.clock()-self.started)
                    self.save();notify(self.snapshot());break
                except Exception as e:item.update(status='error',error=str(e))
                item['elapsed_seconds']=self.initial_elapsed+max(0,self.clock()-self.started)
                if item['status']=='done':item['progress']=100
                self.save();notify(self.snapshot())
        finally:
            with self.lock:self.running=False;self.active=None;self.started=None;self.save()
        return results
