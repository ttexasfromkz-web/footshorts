"""Durable sequential jobs: one failed match cannot cancel the remaining queue."""
import copy
from pathlib import Path
import threading
import uuid
import json
import core
import downloader
import updater


class BatchQueue:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.items=[];self.running=False
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
                item.update(status='running',error='');self.save();notify(self.snapshot())
                try:
                    result=process(item['url'])
                    item.update(status='done',directory=result['directory'],title=result['project']['title'])
                    results.append(result)
                except core.Cancelled:
                    item.update(status='cancelled',error='Пайдаланушы тоқтатты.')
                    self.save();notify(self.snapshot());break
                except Exception as e:item.update(status='error',error=str(e))
                self.save();notify(self.snapshot())
        finally:
            with self.lock:self.running=False;self.save()
        return results
