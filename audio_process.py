"""A small protocol around the native audio subprocess with bounded cleanup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


class AudioProcess:
    def __init__(self,path,start=0):
        self.ready=False;self.closed=False;self.error='';self.event=threading.Event()
        self.log=tempfile.TemporaryFile(mode='w+b')
        self.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('audio_worker.py')),str(path),str(float(start))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',
            bufsize=1,creationflags=(0x08000000 if os.name=='nt' else 0))
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        self.event.wait(5)
        if not self.ready:
            reason=self.error or self.failure() or 'Дыбыстық плеер іске қосылмады.'
            self.close_player()
            raise RuntimeError(reason)

    def _read(self):
        try:
            for line in self.process.stdout:
                try:item=json.loads(line)
                except ValueError:continue
                if item.get('status')=='ready':self.ready=True;self.event.set()
                elif item.get('status')=='error':self.error=item.get('error','Audio error');self.event.set()
        finally:self.event.set()

    def failure(self):
        if self.error:return self.error
        if self.process.poll() is not None:
            self.log.seek(0);data=self.log.read().decode('utf-8',errors='replace')
            return 'Audio worker exit '+str(self.process.returncode)+': '+data[-1600:]
        return ''

    def send(self,command):
        if self.closed:return
        if self.process.poll() is not None:raise RuntimeError(self.failure())
        self.process.stdin.write(json.dumps(command)+'\n');self.process.stdin.flush()

    def set_pause(self,state):
        self.send(dict(action='pause',paused=bool(state)))

    def close_player(self):
        if self.closed:return
        try:
            if self.process.poll() is None:self.send({'action':'close'})
        except (OSError,ValueError,RuntimeError):pass
        self.closed=True
        try:self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.wait(timeout=2)
        self.reader.join(timeout=1)
        for pipe in (self.process.stdin,self.process.stdout):
            if pipe:pipe.close()
        self.log.close()
