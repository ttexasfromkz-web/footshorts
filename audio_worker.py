"""Audio decoder child; native codec failures cannot terminate the review UI."""
import json
import sys


def emit(status,**values):
    print(json.dumps(dict(status=status,**values)),flush=True)


def main():
    player=None
    try:
        emit('starting')
        from ffpyplayer.player import MediaPlayer
        emit('imported')
        player=MediaPlayer(sys.argv[1],thread_lib='python',loglevel='debug',
            ff_opts={'vn':True,'paused':True,'autoexit':False,'volume':.7})
        emit('ready')
        for line in sys.stdin:
            command=json.loads(line)
            if command['action']=='close':break
            if command['action']=='seek':player.seek(float(command['time']),relative=False,accurate=True)
            elif command['action']=='pause':player.set_pause(bool(command['paused']))
    except Exception as e:
        emit('error',error=str(e))
        return 1
    finally:
        if player is not None:player.close_player()
    return 0


if __name__=='__main__':raise SystemExit(main())
