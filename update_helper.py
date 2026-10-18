"""Detached updater: wait for the app, validate, install, health-check, rollback."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
import updater


def wait_parent(pid,timeout=90):
    until=time.monotonic()+timeout
    while updater.process_alive(pid):
        if time.monotonic()>until:raise RuntimeError('Бағдарлама жабылмады. Жаңарту кейінге қалды.')
        time.sleep(.2)


def run_logged(args,root):
    with (root/'.updates/updater.log').open('ab') as log:
        p=subprocess.run([str(a) for a in args],stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                         creationflags=(0x08000000 if os.name=='nt' else 0))
    if p.returncode:raise RuntimeError('Жаңарту тәуелділіктері орнатылмады.')


def candidate_python(root,stage,python):
    current=root/'requirements.txt';new=stage/'files/requirements.txt'
    if current.is_file() and current.read_text(encoding='utf-8').replace('\r\n','\n').strip()==new.read_text(encoding='utf-8').replace('\r\n','\n').strip():return python
    # Never mutate the working environment. Build a separate one for changed dependencies.
    env=root/'.updates/envs'/('env-'+uuid.uuid4().hex)
    run_logged([python,'-m','venv',env],root)
    target=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    run_logged([target,'-m','pip','install','-r',new],root)
    return str(target)


def start_app(root,python,token=''):
    env={**os.environ,'FOOTSHORTS_SKIP_UPDATE':'1','FOOTSHORTS_UPDATER_RESTART':'1'}
    if token:env['FOOTSHORTS_UPDATE_HEALTH_TOKEN']=token
    else:env.pop('FOOTSHORTS_UPDATE_HEALTH_TOKEN',None)
    log=(root/'.updates/app-start.log').open('ab')
    try:return subprocess.Popen([str(python),str(root/'app.py')],cwd=root,env=env,stdin=subprocess.DEVNULL,
                                 stdout=log,stderr=log,creationflags=(0x08000000 if os.name=='nt' else 0))
    finally:log.close()


def health_check(root,process,version,token,timeout=40):
    health=root/'.updates'/('health-'+token+'.json');until=time.monotonic()+timeout
    try:
        while time.monotonic()<until:
            if process.poll() is not None:raise RuntimeError('Жаңа бағдарлама іске қосылмады.')
            if health.exists():
                data=json.loads(health.read_text())
                if data.get('version')==version and data.get('pid')==process.pid:return
            time.sleep(.2)
        raise RuntimeError('Жаңа нұсқаның іске қосылуы расталмады.')
    finally:health.unlink(missing_ok=True)


def apply_update(root,stage,python,starter=start_app,checker=health_check,environment=candidate_python):
    root=Path(root).resolve();stage=Path(stage).resolve()
    if not stage.is_relative_to(root/'.updates/staging'):raise ValueError('Жаңарту қалтасы қате.')
    manifest=json.loads((stage/'update.json').read_text());updater.validate_archive(stage/'payload.zip',manifest)
    if updater.version_tuple(manifest['version'])<=updater.version_tuple(updater.local_version(root)):
        raise ValueError('Ескі немесе сол нұсқаны орнатуға болмайды.')
    files=stage/'files';files.mkdir(exist_ok=True)
    with zipfile.ZipFile(stage/'payload.zip') as z:
        for name in manifest['files']:(files/name).write_bytes(z.read(name))
    backup=root/'.updates/backups'/('before-'+manifest['version']+'-'+uuid.uuid4().hex[:8])
    backup.mkdir(parents=True);changed=[];process=None
    runtime=root/'.updates/runtime.json'
    previous_runtime=runtime.read_bytes() if runtime.is_file() else None
    try:
        new_python=environment(root,stage,python)
        for name in manifest['files']:
            target=root/name
            if target.is_symlink():raise ValueError('Бағдарлама файлы symlink болмауы керек.')
            exists=target.exists()
            if exists:shutil.copy2(target,backup/name)
            # Each file replacement is atomic; the application is stopped during the transaction.
            shutil.copy2(files/name,stage/('install-'+name))
            os.replace(stage/('install-'+name),target);changed.append((name,exists))
        token=uuid.uuid4().hex
        process=starter(root,new_python,token)
        checker(root,process,manifest['version'],token)
        updater.atomic_json(root/'.updates/runtime.json',{'python':new_python,'version':manifest['version']})
        updater.atomic_json(root/'.updates/last-update.json',{'version':manifest['version'],'status':'installed','time':time.time()})
        return True
    except BaseException as e:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for name,existed in reversed(changed):
            if existed:os.replace(backup/name,root/name)
            else:(root/name).unlink(missing_ok=True)
        if previous_runtime is None:runtime.unlink(missing_ok=True)
        else:runtime.write_bytes(previous_runtime)
        updater.atomic_json(root/'.updates/failed.json',{'version':manifest['version'],'time':time.time(),'error':str(e)})
        raise


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--stage',required=True)
    p.add_argument('--pid',required=True,type=int);p.add_argument('--python',required=True);a=p.parse_args()
    root=Path(a.root).resolve();lock=root/'.updates/update.lock'
    if not updater.acquire_lock(lock):return 1
    try:
        wait_parent(a.pid)
        try:apply_update(root,a.stage,a.python)
        except Exception as e:
            print('Update failed; restored previous version:',e,flush=True)
            start_app(root,updater.runtime_python(root,a.python))
            return 1
        return 0
    finally:updater.release_lock(lock)

if __name__=='__main__':raise SystemExit(main())
