"""Check and repair the exact local Python used by Football Shorts; stdlib only."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import uuid
import updater

MODULES=('numpy','cv2','PIL','rapidocr_onnxruntime','imageio_ffmpeg','yt_dlp','ffpyplayer.player','tkinter','deno')
PROBE="""import importlib,json
missing=[]
for name in %r:
    try:importlib.import_module(name)
    except Exception as e:missing.append(name+': '+str(e))
print(json.dumps(missing))
"""%(MODULES,)


def probe(python):
    try:
        result=subprocess.run([str(python),'-I','-c',PROBE],stdin=subprocess.DEVNULL,
            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60,
            creationflags=0x08000000 if os.name=='nt' else 0)
        if result.returncode:return ['Python: '+result.stderr[-1200:]]
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired) as e:return [str(e)]


def candidates(root,preferred=None):
    root=Path(root).resolve();choices=[]
    paths=[preferred,root/'.runtime/python.exe',root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')]
    for value in paths:
        if not value:continue
        path=Path(value).resolve()
        if path.is_relative_to(root) and path.is_file() and path not in choices:choices.append(path)
    return choices


def logged_run(args,root,log):
    with (root/'.updates/repair.log').open('a',encoding='utf-8') as saved:
        process=subprocess.Popen([str(x) for x in args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',
            creationflags=0x08000000 if os.name=='nt' else 0)
        try:
            for line in process.stdout:
                saved.write(line);saved.flush();log(line.rstrip())
            if process.wait():raise RuntimeError('Орнату аяқталмады. .updates/repair.log файлын тексеріңіз.')
        finally:
            if process.poll() is None:process.terminate();process.wait()
            process.stdout.close()


def ensure_runtime(root,preferred=None,log=print):
    root=Path(root).resolve();(root/'.updates').mkdir(exist_ok=True)
    available=candidates(root,preferred)
    for python in available:
        log('Python кітапханаларын тексеру…')
        missing=probe(python)
        if not missing:
            updater.atomic_json(root/'.updates/runtime.json',{'python':str(python),'version':updater.local_version(root)})
            return str(python)
        log('Ортаны жөндеу қажет: '+', '.join(missing))
    lock=root/'.updates/instance.lock'
    if lock.is_file():
        try:
            if updater.process_alive(json.loads(lock.read_text()).get('pid')):
                raise RuntimeError('Бағдарламаны жауып, қайта іске қосыңыз. Ашық Python ортасы өзгертілмеді.')
        except (ValueError,OSError):pass
    if not updater.acquire_lock(root/'.updates/repair.lock'):raise RuntimeError('Жөндеу қазір жүріп жатыр. Аяқталуын күтіңіз.')
    try:
        # Always create a separate environment; never overwrite a running python.exe.
        seed=next((p for p in [*available,Path(sys._base_executable)] if p.is_file()),None)
        if not seed:raise RuntimeError('Python табылмады. FootballShorts-Setup.exe орнатқышын іске қосыңыз.')
        environment=root/'.updates/envs'/('repair-'+uuid.uuid4().hex)
        log('Жаңа Python ортасы жасалуда…')
        logged_run([seed,'-m','venv',environment],root,log)
        python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        logged_run([python,'-m','pip','install','--disable-pip-version-check','-r',root/'requirements.txt'],root,log)
        missing=probe(python)
        if missing:raise RuntimeError('Кітапханалар әлі оқылмады: '+', '.join(missing))
        updater.atomic_json(root/'.updates/runtime.json',{'python':str(python),'version':updater.local_version(root)})
        log('Python ортасы дайын.')
        return str(python)
    finally:updater.release_lock(root/'.updates/repair.lock')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parent));parser.add_argument('--repair',action='store_true')
    args=parser.parse_args()
    try:ensure_runtime(args.root,updater.runtime_python(args.root));raise SystemExit(0)
    except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)
