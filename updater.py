"""GitHub Releases updates. Runtime/data directories are never part of a patch."""
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

REPOSITORY='ttexasfromkz-web/footshorts'
API=f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
ASSET='FootballShorts-update.zip'
MAX_ZIP=16*1024*1024
MAX_UNPACKED=32*1024*1024
KNOWN={'version.json','requirements.txt','README.md','README_KZ.md','VALIDATION.md',
       '1_INSTALL.bat','2_START.bat','3_UPDATE_YOUTUBE.bat'}


def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):
        raise ValueError('Нұсқа форматы қате.')
    return tuple(map(int,value.split('.')))


def local_version(root):
    p=json.loads((Path(root)/'version.json').read_text(encoding='utf-8'))
    version_tuple(p['version'])
    return p['version']


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def allowed_file(name):
    # Only top-level application files. output, music, .venv and local settings cannot match.
    return isinstance(name,str) and (name in KNOWN or bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.py',name)))


def release_url(url,tag):
    p=urlparse(url)
    prefix=f'/{REPOSITORY}/releases/download/{tag}/'
    if p.scheme!='https' or p.netloc!='github.com' or not p.path.startswith(prefix) or p.query or p.fragment:
        raise ValueError('Жаңарту сілтемесі осы GitHub репозиторийіне жатпайды.')
    return url


class HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        p=urlparse(newurl)
        if p.scheme!='https' or p.hostname not in {'github.com','api.github.com','release-assets.githubusercontent.com',
                                                  'objects.githubusercontent.com','github-releases.githubusercontent.com'}:
            raise ValueError('Жаңарту бағыты рұқсат етілмеген.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,limit):
    req=Request(url,headers={'User-Agent':'FootballShorts-Updater','Accept':'application/vnd.github+json'})
    with build_opener(HTTPSRedirect()).open(req,timeout=20) as r:
        if urlparse(r.geturl()).scheme!='https':raise ValueError('HTTPS қажет.')
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError('Жаңарту файлы рұқсат етілген көлемнен үлкен.')
        return data


def validate_manifest(manifest,tag=None):
    version_tuple(manifest.get('version'))
    if tag and tag!='v'+manifest['version']:raise ValueError('Release тегі мен нұсқасы сәйкес емес.')
    if manifest.get('repository')!=REPOSITORY or manifest.get('asset_name')!=ASSET:
        raise ValueError('Жаңарту манифесті қате.')
    if not re.fullmatch(r'[a-f0-9]{64}',manifest.get('sha256','')):raise ValueError('SHA256 жоқ.')
    files=manifest.get('files')
    if not isinstance(files,dict) or not {'app.py','updater.py','update_helper.py','version.json','requirements.txt'}<=files.keys():
        raise ValueError('Жаңартудың міндетті файлдары жоқ.')
    if len(files)>100 or any(not allowed_file(k) or not re.fullmatch(r'[a-f0-9]{64}',str(v)) for k,v in files.items()):
        raise ValueError('Жаңарту деректер қалтасын өзгертуге тырысады немесе файл тізімі қате.')
    return manifest


def validate_archive(path,manifest):
    validate_manifest(manifest)
    if Path(path).stat().st_size>MAX_ZIP or sha256(path)!=manifest['sha256']:raise ValueError('Жаңарту SHA256 сәйкес емес.')
    with zipfile.ZipFile(path) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(n.lower() for n in names)) or set(names)!=set(manifest['files']):
            raise ValueError('ZIP файл тізімі сәйкес емес немесе қайталанған.')
        if sum(i.file_size for i in infos)>MAX_UNPACKED:raise ValueError('ZIP ашылғандағы көлемі үлкен.')
        for info in infos:
            if not allowed_file(info.filename) or info.is_dir() or stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('ZIP ішіндегі жолға рұқсат жоқ.')
            data=z.read(info)
            if hashlib.sha256(data).hexdigest()!=manifest['files'][info.filename]:raise ValueError('Файл SHA256 сәйкес емес.')
            if info.filename.endswith('.py'):compile(data,info.filename,'exec')
        version=json.loads(z.read('version.json'))
        if version.get('version')!=manifest['version'] or version.get('repository')!=REPOSITORY:
            raise ValueError('Пакет нұсқасы манифестке сәйкес емес.')
    return True


def prepare_update(root,log=print,force=False):
    root=Path(root).resolve()
    if os.environ.get('FOOTSHORTS_SKIP_UPDATE')=='1':return None
    current=local_version(root)
    try:release=json.loads(fetch(API,1024*1024))
    except HTTPError as e:
        if e.code==404:return None
        raise
    tag=release.get('tag_name','')
    if not tag.startswith('v') or release.get('draft') or release.get('prerelease'):return None
    if version_tuple(tag[1:])<=version_tuple(current):return None
    failed=root/'.updates'/'failed.json'
    if failed.is_file() and not force:
        try:
            failure=json.loads(failed.read_text())
            if failure.get('version')==tag[1:] and time.time()-failure.get('time',0)<86400:return None
        except (ValueError,TypeError):pass
    assets={a['name']:a for a in release.get('assets',[]) if isinstance(a,dict) and 'name' in a}
    if 'update.json' not in assets or ASSET not in assets:return None
    manifest=json.loads(fetch(release_url(assets['update.json']['browser_download_url'],tag),128*1024))
    validate_manifest(manifest,tag)
    if int(assets[ASSET].get('size',MAX_ZIP+1))>MAX_ZIP:raise ValueError('Пакет көлемі үлкен.')
    log('Жаңа нұсқа табылды: '+manifest['version']+'. Жүктелуде…')
    payload=fetch(release_url(assets[ASSET]['browser_download_url'],tag),MAX_ZIP)
    digest=assets[ASSET].get('digest')
    if digest and digest!='sha256:'+hashlib.sha256(payload).hexdigest():raise ValueError('GitHub asset SHA256 сәйкес емес.')
    staging=root/'.updates'/'staging';staging.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=manifest['version']+'-',dir=staging))
    try:
        package=stage/'payload.zip';package.write_bytes(payload)
        validate_archive(package,manifest)
        atomic_json(stage/'update.json',manifest)
        log('Жаңарту тексерілді. Ағымдағы жұмыс біткен соң орнатылады.')
        return str(stage)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise


def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=k.OpenProcess(0x1000,False,pid)
        if handle:
            exit_code=wintypes.DWORD()
            k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            ok=k.GetExitCodeProcess(handle,ctypes.byref(exit_code));k.CloseHandle(handle)
            return bool(ok and exit_code.value==259)
        return ctypes.get_last_error()==5
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def acquire_lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    for _ in range(2):
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid()},f)
            return True
        except FileExistsError:
            try:
                if process_alive(json.loads(path.read_text()).get('pid')):return False
            except (ValueError,OSError,TypeError):return False
            path.unlink(missing_ok=True)
    return False


def release_lock(path):
    path=Path(path)
    try:
        if json.loads(path.read_text()).get('pid')==os.getpid():path.unlink(missing_ok=True)
    except (OSError,ValueError):pass


def launch_helper(root,stage):
    root=Path(root).resolve();stage=Path(stage).resolve()
    if not stage.is_relative_to(root/'.updates'/'staging'):raise ValueError('Жаңарту қалтасы қате.')
    manifest=json.loads((stage/'update.json').read_text());validate_archive(stage/'payload.zip',manifest)
    helper=stage/'helper';helper.mkdir(exist_ok=True)
    # Run the trusted OLD helper from a stable location while application files are replaced.
    for name in ('updater.py','update_helper.py'):shutil.copy2(root/name,helper/name)
    log_path=root/'.updates'/'updater.log'
    with log_path.open('ab') as log:
        return subprocess.Popen([sys.executable,str(helper/'update_helper.py'),'--root',str(root),
                                 '--stage',str(stage),'--pid',str(os.getpid()),'--python',sys.executable],
                                cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                creationflags=(0x08000000 if os.name=='nt' else 0),start_new_session=(os.name!='nt'))


def runtime_python(root,fallback=None):
    fallback=fallback or sys.executable
    try:
        path=json.loads((Path(root)/'.updates/runtime.json').read_text())['python']
        if Path(path).is_file():return path
    except (OSError,ValueError,KeyError):pass
    return fallback


def mark_healthy(root):
    token=os.environ.get('FOOTSHORTS_UPDATE_HEALTH_TOKEN','')
    if re.fullmatch(r'[a-f0-9]{32}',token):
        atomic_json(Path(root)/'.updates'/('health-'+token+'.json'),{'version':local_version(root),'pid':os.getpid()})
