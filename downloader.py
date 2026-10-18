"""YouTube downloads with explicitly selected local Chrome or cookie-file login."""
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import core


def normalize_url(value):
    value=value.strip()
    if '://' not in value:value='https://'+value
    u=urlparse(value)
    if u.scheme not in ('https','http') or u.username or u.password or u.port:
        raise ValueError('YouTube сілтемесін енгізіңіз.')
    host=(u.hostname or '').lower()
    if host in ('youtu.be','www.youtu.be'):
        ident=u.path.strip('/').split('/')[0]
    elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
        parts=u.path.strip('/').split('/')
        ident=parse_qs(u.query).get('v',[''])[0] if u.path=='/watch' else (parts[1] if len(parts)==2 and parts[0] in ('shorts','live','embed') else '')
    else:raise ValueError('Тек youtube.com немесе youtu.be сілтемесі қабылданады.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):
        raise ValueError('Бір видеоның толық сілтемесін енгізіңіз. Плейлист сілтемесі жарамайды.')
    return 'https://www.youtube.com/watch?v='+ident


def ffmpeg_directory():
    """yt-dlp expects a binary actually named ffmpeg(.exe)."""
    source=Path(core.ffmpeg())
    target_dir=Path.home()/'.footballshorts'/'tools'
    target_dir.mkdir(parents=True,exist_ok=True)
    target=target_dir/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')
    if not target.exists() or target.stat().st_size!=source.stat().st_size:
        shutil.copy2(source,target)
    return target_dir


def runtime_args():
    script=Path(sys.executable).parent
    deno=shutil.which('deno') or next((str(p) for p in [script/'deno.exe',script/'deno',Path.home()/'.deno/bin/deno.exe'] if p.is_file()),None)
    if not deno:
        try:
            from deno import find_deno_bin
            deno=str(find_deno_bin())
        except (ImportError,RuntimeError,FileNotFoundError):pass
    if deno:return ['--js-runtimes','deno:'+deno]
    node=shutil.which('node')
    if node:return ['--js-runtimes','node:'+node]
    return []


def authentication_args(browser='',cookie_file=''):
    if browser not in ('','chrome'):raise ValueError('Кіру үшін Chrome немесе cookies файлын таңдаңыз.')
    if browser and cookie_file:raise ValueError('Chrome және cookies файлын бірге таңдамаңыз.')
    if browser:return ['--cookies-from-browser',browser]
    if cookie_file:
        path=Path(cookie_file).expanduser().resolve()
        if not path.is_file():raise ValueError('Cookies файлы табылмады. Қайта таңдаңыз.')
        with path.open('rb') as handle:header=handle.readline(256).strip()
        if header not in (b'# Netscape HTTP Cookie File',b'# HTTP Cookie File'):
            raise ValueError('Cookies файлы Netscape cookies.txt форматында болуы керек.')
        return ['--cookies',str(path)]
    return []


def download_error(lines):
    details='\n'.join(lines)[-1800:]
    lower=details.lower()
    if 'decrypt' in lower or 'dpapi' in lower or 'app-bound' in lower:
        return ('Chrome сессиясын Windows шифрлауына байланысты оқу мүмкін болмады. '
                '«Cookies файлы» режимін қолданыңыз немесе видео файлын таңдаңыз. '
                'Chrome қауіпсіздік баптауларын өшіру қажет емес.')
    if 'cookie database' in lower or ('cookies' in lower and 'permission denied' in lower):
        return ('Chrome cookies дерекқоры бос емес немесе қолжетімсіз. Chrome терезелерін толық жауып, қайта көріңіз. '
                'Көмектеспесе «Cookies файлы» режимін немесе жергілікті видеоны қолданыңыз.')
    if 'sign in' in lower or 'not a bot' in lower:
        return ('YouTube кіруді немесе бот емес екеніңізді растауды сұрады. '
                'Chrome-да осы видеоны ашып, аккаунтқа кіріңіз; бағдарламадағы «YouTube кіруі» бөлімінен Chrome таңдаңыз. '
                'Chrome режимі көмектеспесе, «Cookies файлы» немесе жергілікті видео қолданыңыз. '
                'Кіру сессиясы жүктеуге кепілдік бермейді.')
    return 'YouTube видеосы жүктелмеді. Сілтемені және интернетті тексеріңіз.\n\n'+details


def build_command(url,workdir,height=1080,browser='',cookie_file=''):
    if int(height) not in (720,1080):raise ValueError('Сапа: 720 немесе 1080.')
    fmt=(f'bv[ext=mp4][vcodec^=avc1][height<={height}]+ba[ext=m4a]/'
         f'b[ext=mp4][height<={height}]/bv[height<={height}]+ba/b[height<={height}]')
    return [sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--no-simulate',
            '--newline','--no-colors','--progress','--progress-template','download:DL:%(progress._percent_str)s',
            '--print','before_dl:TITLE:%(title)s','--print','after_move:FILE:%(filepath)s',
            '--socket-timeout','20','--retries','2','--fragment-retries','2',
            '--match-filter','!is_live & duration < 14400','--windows-filenames',
            '--ffmpeg-location',str(ffmpeg_directory()),'-f',fmt,'--merge-output-format','mp4',
            '-o',str(Path(workdir)/'video.%(ext)s'),*runtime_args(),*authentication_args(browser,cookie_file),'--',url]


def stop_process(p):
    if p.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=core.CREATE_NO_WINDOW)
    else:
        import signal
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait()


def download(url,directory,height=1080,log=print,cancel=None,browser='',cookie_file=''):
    url=normalize_url(url)
    if cancel and cancel.is_set():raise core.Cancelled()
    dest=Path(directory).resolve();dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='youtube-',dir=dest) as tmp:
        tmp=Path(tmp)
        # Never modify the user's cookie file; yt-dlp updates only this private temporary copy.
        authentication_args(browser,cookie_file)
        if cookie_file:
            private_cookie=tmp/'session-cookies.txt';shutil.copyfile(cookie_file,private_cookie)
            cookie_file=str(private_cookie)
        command=(build_command(url,tmp,height,browser=browser,cookie_file=cookie_file)
                 if browser or cookie_file else build_command(url,tmp,height))
        log('YouTube видеосын жүктеу…')
        p=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           encoding='utf-8',errors='replace',bufsize=1,
                           env={**os.environ,'PYTHONIOENCODING':'utf-8'},
                           creationflags=core.CREATE_NO_WINDOW,start_new_session=(os.name!='nt'))
        lines=queue.Queue();reader_done=threading.Event()
        def read():
            try:
                for line in p.stdout:lines.put(line.rstrip())
            finally:reader_done.set()
        thread=threading.Thread(target=read,daemon=True);thread.start()
        last_progress=0;errors=[];filepath=None;title=''
        try:
            while not (reader_done.is_set() and lines.empty()):
                if cancel and cancel.is_set():raise core.Cancelled()
                try:line=lines.get(timeout=.2)
                except queue.Empty:continue
                if line.startswith('FILE:'):filepath=Path(line[5:]).resolve()
                elif line.startswith('TITLE:'):title=line[6:]
                elif line.startswith('DL:'):
                    if time.monotonic()-last_progress>1:
                        log('Жүктелуде: '+line[3:].strip());last_progress=time.monotonic()
                else:
                    errors.append(line);errors=errors[-12:]
                    if line.startswith('WARNING:'):log(line)
            code=p.wait()
            if cancel and cancel.is_set():raise core.Cancelled()
            if code:
                raise RuntimeError(download_error(errors))
            if not filepath or filepath.parent!=tmp.resolve() or not filepath.is_file():
                raise RuntimeError('Жүктелген видео табылмады. Тікелей эфир, плейлист немесе 4 сағаттан ұзақ видео қабылданбайды.')
            # Some fallback formats cannot be opened by OpenCV on Windows.
            try:core.metadata(filepath)
            except ValueError:
                log('Видеоны үйлесімді MP4 форматына айналдыру…')
                converted=tmp/'converted.mp4'
                core.run([core.ffmpeg(),'-v','error','-i',filepath,'-c:v','libx264','-preset','fast',
                          '-crf','20','-threads','2','-c:a','aac','-movflags','+faststart','-y',converted],cancel)
                core.metadata(converted);filepath=converted
            if cancel and cancel.is_set():raise core.Cancelled()
            ident=parse_qs(urlparse(url).query)['v'][0]
            target=dest/(ident+'_'+uuid.uuid4().hex[:8]+filepath.suffix)
            os.replace(filepath,target)
            return dict(path=str(target),title=title,url=url)
        finally:
            stop_process(p)
            thread.join(timeout=2)
            if p.stdout:p.stdout.close()
