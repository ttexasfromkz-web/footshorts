"""Embedded frame-accurate preview with FFmpeg audio and deterministic cleanup."""
import time
import cv2
import core


class PreviewPlayer:
    def __init__(self,path,clock=time.monotonic,audio=True):
        self.path=str(path);self.clock=clock;self.info=core.metadata(path)
        self.duration=self.info['duration'];self.fps=self.info['fps']
        self.capture=cv2.VideoCapture(self.path)
        self.audio=None;self.audio_enabled=audio;self.audio_error=''
        self.closed=False;self.playing=False;self.pos=0.;self.started=0.
        self.last_index=-1;self.last_frame=None

    def position(self):
        if self.closed:return self.pos
        return min(self.duration,self.pos+(self.clock()-self.started if self.playing else 0))

    def _audio(self):
        if not self.audio_enabled:return
        try:
            if self.audio is None:
                from ffpyplayer.player import MediaPlayer
                self.audio=MediaPlayer(self.path,ff_opts={'vn':True,'paused':True,'volume':.7})
            self.audio.seek(self.pos,relative=False,accurate=True)
            self.audio.set_pause(not self.playing)
        except Exception as e:
            self.audio_error=str(e);self.audio_enabled=False
            if self.audio:
                self.audio.close_player();self.audio=None

    def play(self):
        if self.closed or self.playing:return
        if self.pos>=self.duration-.03:self.seek(0)
        self.started=self.clock();self.playing=True;self._audio()

    def pause(self):
        if self.closed:return
        self.pos=self.position();self.playing=False
        if self.audio:self.audio.set_pause(True)

    def seek(self,t):
        if self.closed:return
        self.pos=max(0,min(float(t),max(0,self.duration-1/self.fps)))
        self.started=self.clock()
        if self.audio:
            self.audio.seek(self.pos,relative=False,accurate=True)
            self.audio.set_pause(not self.playing)

    def frame(self):
        if self.closed:return None
        t=self.position()
        if t>=self.duration and self.playing:self.pause()
        index=min(int(self.info['duration']*self.fps)-1,max(0,round(t*self.fps)))
        if index!=self.last_index:
            if index!=self.last_index+1:self.capture.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,frame=self.capture.read()
            if ok:self.last_frame=frame;self.last_index=index
        return self.last_frame

    def close(self):
        if self.closed:return
        self.pos=self.position();self.closed=True;self.playing=False
        self.capture.release()
        if self.audio:
            audio=self.audio;self.audio=None;audio.close_player()
