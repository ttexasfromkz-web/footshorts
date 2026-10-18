"""Audio decoder child; native codec failures cannot terminate the review UI."""
import json
import sys
import time


def emit(status,**values):
    print(json.dumps(dict(status=status,**values)),flush=True)


def main():
    player=None
    try:
        from ffpyplayer.player import MediaPlayer
        # Start at the requested time when opening. Seeking before the read thread
        # initializes its streams can crash native FFmpeg on Windows.
        player=MediaPlayer(sys.argv[1],thread_lib='python',loglevel='warning',
            ff_opts={'vn':True,'paused':True,'autoexit':False,'volume':.7,'ss':float(sys.argv[2])})
        until=time.monotonic()+4
        while time.monotonic()<until:
            if player.get_metadata().get('duration',0)>0:break
            time.sleep(.01)
        else:raise RuntimeError('Дыбыстық файл ашылмады.')
        emit('ready')
        for line in sys.stdin:
            command=json.loads(line)
            if command['action']=='close':break
            if command['action']=='pause':player.set_pause(bool(command['paused']))
    except Exception as e:
        emit('error',error=str(e))
        return 1
    finally:
        if player is not None:player.close_player()
    return 0


if __name__=='__main__':raise SystemExit(main())
