"""Persistent local projects: automatic creation, review, correction, and retry."""
from pathlib import Path
from datetime import datetime
import json
import hashlib
import os
import re
import shutil
import tempfile
import uuid
import core
import downloader
import publishing

DEFAULTS=dict(target=180,roi=[0,0,.5,.17],use_ocr=True,music_level=.18,
              source_level=.2,crop_top=.15,replays=True,replay_speed=.5,action_camera=False,intro=True,show_final=True)


def stage_style(project):
    from channel_templates import style
    s=style(project.get('settings',{}).get('channel_style'))
    for key,name in [('brand_logo','brand-logo.png'),('font_file','brand-font')]:
        value=s[key]
        if not value:continue
        path=Path(value)
        if not path.is_absolute():path=media_path(project,value)
        if not path.is_file():raise FileNotFoundError('Арна файлы табылмады: '+str(path))
        dest=media_path(project,'source/'+name+(path.suffix.lower() if key=='font_file' else ''))
        dest.parent.mkdir(parents=True,exist_ok=True)
        if path.resolve()!=dest.resolve():shutil.copy2(path,dest)
        s[key]=str(dest.relative_to(Path(project['directory']).resolve())).replace('\\','/')
    project.setdefault('settings',{})['channel_style']=s


def project_style(project):
    from channel_templates import style
    s=style(project.get('settings',{}).get('channel_style'))
    for key in ('brand_logo','font_file'):
        if s[key] and not Path(s[key]).is_absolute():s[key]=str(media_path(project,s[key]))
    return s


def save_project(project):
    folder=Path(project['directory']);source=folder/'source';source.mkdir(parents=True,exist_ok=True)
    manifest=source/'project.json';temp=source/('project-'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,manifest)
    finally:temp.unlink(missing_ok=True)


def load_project(path):
    p=Path(path).resolve()
    if p.is_dir():p=p/'source'/'project.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    if data.get('kind')!='football_project':raise ValueError('Бұл автоматты жоба файлы емес.')
    data['directory']=str(p.parent.parent)
    # Stored media paths are relative so a whole project can be moved.
    media_path(data,data.get('source_file',''))
    return data


def media_path(project,relative):
    folder=Path(project['directory']).resolve();path=(folder/relative).resolve()
    if not relative or not path.is_relative_to(folder):raise ValueError('Жобадағы файл жолы қате.')
    return path


def recent_projects(base):
    root=Path(base)/'output'
    if not root.exists():return []
    return sorted([p.parent.parent for p in root.glob('*/source/project.json')],
                  key=lambda p:(p/'source/project.json').stat().st_mtime,reverse=True)


def rename_project(project,title):
    old=Path(project['directory']);name=publishing.safe_name(title)
    new=old.parent/name;counter=2
    while new.exists() and new.resolve()!=old.resolve():
        new=old.parent/(name+f' ({counter})');counter+=1
    if new!=old:
        old.rename(new);project['directory']=str(new)
    return project


def project_text(project):
    parsed=publishing.parse_match_title(project['title']);score=project.get('score') or '?'
    music=project.get('music_title') or Path(project.get('music_file','')).stem
    if parsed:
        text=publishing.youtube_text(parsed['team_a'],parsed['team_b'],score,project.get('source_url',''),music)
    else:
        title=project['title'];score_text=score if score!='?' else 'анықталмады'
        text=(f'ВИДЕО АТАУЫ\n{title[:65]} ⚽ Үздік сәттер #Shorts\n\n'
              f'СИПАТТАМА (хештегтерімен бірге)\n⚽ {title}\nЕсеп: {score_text}.\n'
              'Матчтың іріктелген сәттерін тамашала!\nҚай сәт ұнады? Пікірге жаз!\n\n'
              '#рекомендации #рекомендация #Футбол #Football #Highlights #Shorts\n\n'
              'ТЕГТЕР\nфутбол, футбол шортс, football, football highlights, football shorts, shorts\n')
    if not parsed or not project.get('score'):
        text+='\nЖАРИЯЛАУ АЛДЫНДА ТЕКСЕРУ\n'
        if not parsed:text+='Командалар атауы автоматты анықталмады. Матч атауын түзетіңіз.\n'
        if not project.get('score'):text+='Есеп оқылмады. 0:0 деп болжанған жоқ. Есепті енгізіп қайта жасаңыз.\n'
    if project.get('settings',{}).get('intro',True) and parsed:
        credits=[]
        for record in (Path(project['directory'])/'source/logos').glob('*.json'):
            try:
                item=json.loads(record.read_text(encoding='utf-8'))
                if item.get('name') in (parsed['team_a'],parsed['team_b']) and item.get('source'):
                    credits.append(' • '.join(str(item.get(k,'')) for k in ('name','artist','license','source') if item.get(k)))
            except (OSError,ValueError):continue
        if credits:text+='\nЛОГОТИПТЕРДІҢ ДЕРЕККӨЗДЕРІ\n'+'\n'.join(credits)+'\n'
    return text


def output_files(project):
    folder=Path(project['directory']).resolve()
    return dict(directory=str(folder),video=str(folder/project.get('video_file','result.mp4')),
                text=str(folder/project.get('text_file','result.txt')),project=project)


def commit_outputs(project,new_video,new_text):
    """Keep the previous result in source/history; rollback if either replacement fails."""
    folder=Path(project['directory']);name=publishing.safe_name(project['title'])
    video=folder/(name+'.mp4');text=folder/(name+'.txt')
    old_paths=[media_path(project,k) for k in (project.get('video_file',''),project.get('text_file','')) if k]
    old_paths=list(dict.fromkeys([*old_paths,*[p for p in (video,text) if p.exists()]]))
    history=folder/'source'/'history'/('revision_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    backups=[];written=[]
    try:
        for old in old_paths:
            if old.is_file():
                history.mkdir(parents=True,exist_ok=True)
                dest=history/old.name;os.replace(old,dest);backups.append((old,dest))
        os.replace(new_video,video);written.append(video)
        os.replace(new_text,text);written.append(text)
    except BaseException:
        for dest,staged in [(video,new_video),(text,new_text)]:
            if dest in written and dest.exists():os.replace(dest,staged)
        for old,backup in backups:
            if backup.exists():os.replace(backup,old)
        raise
    project.update(video_file=video.name,text_file=text.name,status='ready',checkpoint='ready')
    project['revision']=int(project.get('revision',0))+1
    project['updated_at']=datetime.now().isoformat(timespec='seconds')
    save_project(project)
    return output_files(project)


def render_project(project,log=print,cancel=None):
    stage_style(project)
    settings={**DEFAULTS,**project.get('settings',{})}
    source=media_path(project,project['source_file'])
    music=media_path(project,project['music_file']) if project.get('music_file') else None
    if not source.is_file():raise FileNotFoundError('Жобаның бастапқы видеосы табылмады: '+str(source))
    if music and not music.is_file():raise FileNotFoundError('Жобаның музыкасы табылмады: '+str(music))
    project['status']='rendering';save_project(project)
    log('@progress:'+('logos' if settings['intro'] else 'render')+':0:Монтажға дайындалуда')
    log('Монтаж және YouTube TXT дайындау…')
    folder=Path(project['directory']).resolve()
    try:
        cache=media_path(project,'source/render-checkpoint');cache.mkdir(exist_ok=True)
        video=cache/'result.mp4';text=cache/'result.txt';manifest=cache/'render.json'
        media=[source,*([music] if music else [])]
        media += [Path(project_style(project)[k]) for k in ('brand_logo','font_file') if project_style(project)[k]]
        signature=hashlib.sha256(json.dumps([project['clips'],settings,project['title'],project.get('score'),
                    [(str(p.relative_to(folder)),p.stat().st_size,p.stat().st_mtime_ns) for p in media]],sort_keys=True).encode()).hexdigest()
        reusable=False
        if video.is_file() and manifest.is_file():
            try:reusable=json.loads(manifest.read_text())['signature']==signature and core.metadata(video)['duration']>0
            except (OSError,ValueError,KeyError):pass
        if reusable:log('@progress:render:1:Сақталған монтаж қолданылды')
        else:
            core.render(str(source),str(music) if music else None,project['clips'],video,
                title=project['title'],score=project.get('score') or '?',
                music_level=settings['music_level'],source_level=settings['source_level'],
                crop_top=settings['crop_top'],replays=settings['replays'],replay_speed=settings['replay_speed'],
                max_seconds=settings['target'],action_camera=settings['action_camera'],intro=settings['intro'],
                show_final=settings['show_final'],channel_style=project_style(project),logo_dir=folder/'source/logos',log=log,cancel=cancel)
            temp_manifest=cache/'render.tmp';temp_manifest.write_text(json.dumps({'signature':signature}));os.replace(temp_manifest,manifest)
        project['checkpoint']='render';save_project(project)
        log('@progress:save:0.8:YouTube мәтіні мен видеоны сақтау')
        text.write_text(project_text(project),encoding='utf-8-sig')
        if cancel and cancel.is_set():raise core.Cancelled()
        result=commit_outputs(project,video,text);manifest.unlink(missing_ok=True)
        return result
    except BaseException as e:
        project['status']='cancelled' if isinstance(e,core.Cancelled) else 'error'
        project['error']=str(e);save_project(project);raise


def checkpoint(project,stage,callback=None):
    project['checkpoint']=stage
    save_project(project)
    if callback:callback(dict(directory=project['directory'],project_id=project['project_id'],stage=stage,title=project['title']))


def create_project(base,url='',local_video='',music='',settings=None,title_hint='',log=print,cancel=None,on_source=None,on_checkpoint=None):
    settings={**DEFAULTS,**(settings or {})}
    if not url and not Path(local_video).is_file():raise ValueError('YouTube сілтемесін немесе видео файлын беріңіз.')
    if url:url=downloader.normalize_url(url)
    root=Path(base).resolve()/'output';root.mkdir(parents=True,exist_ok=True)
    ident=uuid.uuid4().hex
    folder=root/('Жоба_'+datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'_'+ident[:6])
    (folder/'source').mkdir(parents=True)
    p=dict(kind='football_project',schema_version=2,project_id=ident,directory=str(folder),status='starting',
           title=title_hint or 'Матч',source_url=url,source_file='source/original.mp4',
           music_file='',score=None,clips=[],settings=settings,revision=0,warnings=[],
           request=dict(local_video=str(local_video),music=str(music),title_hint=title_hint))
    checkpoint(p,'new',on_checkpoint)
    return continue_project(p,log,cancel,on_source,on_checkpoint)


def resolve_checkpoint(base,item):
    directory=item.get('directory','');ident=item.get('project_id')
    if directory and (Path(directory)/'source/project.json').is_file():
        p=load_project(directory)
        if not ident or p.get('project_id')==ident:return Path(directory)
    if ident:
        for candidate in (Path(base)/'output').glob('*/source/project.json'):
            try:
                if json.loads(candidate.read_text(encoding='utf-8')).get('project_id')==ident:return candidate.parent.parent
            except (OSError,ValueError):continue
    return None


def resume_project(directory,log=print,cancel=None,on_source=None,on_checkpoint=None):
    p=load_project(directory);p.setdefault('project_id',uuid.uuid4().hex)
    p.setdefault('source_ready',bool(p.get('raw_title')))
    p.setdefault('analysis_ready',bool(p.get('analysis')))
    return continue_project(p,log,cancel,on_source,on_checkpoint)


def continue_project(p,log=print,cancel=None,on_source=None,on_checkpoint=None):
    settings={**DEFAULTS,**p.get('settings',{})};request=p.get('request',{})
    log('@progress:reset');log('Жоба: '+p['directory'])
    try:
        if cancel and cancel.is_set():raise core.Cancelled()
        if p.get('status')=='ready':
            files=output_files(p)
            if all(Path(files[k]).is_file() and Path(files[k]).stat().st_size for k in ('video','text')):
                log('@progress:save:1:Бұрын дайындалған нәтиже сақталған');return files
        p.pop('error',None)
        if not p.get('source_ready'):
            source=Path(p['directory'])/'source'
            log('@progress:download:0:Бастапқы видеоны дайындау')
            p['status']='downloading';save_project(p)
            url=p.get('source_url','')
            if url:
                auth={}
                if settings.get('youtube_browser'):auth['browser']=settings['youtube_browser']
                if settings.get('youtube_cookie_file'):auth['cookie_file']=settings['youtube_cookie_file']
                result=downloader.download(url,source,settings.get('quality',1080),log,cancel,**auth)
                original=Path(result['path']);raw_title=result.get('title','')
            else:
                local_video=Path(request.get('local_video',''))
                if not local_video.is_file():raise FileNotFoundError('Бастапқы видео табылмады.')
                log('Бастапқы видеоны жобаға көшіру…')
                original=source/('original'+local_video.suffix.lower());temporary=source/'original.copying'
                shutil.copy2(local_video,temporary)
                if cancel and cancel.is_set():raise core.Cancelled()
                os.replace(temporary,original);raw_title=request.get('title_hint') or local_video.stem
            new_source=source/('original'+original.suffix.lower())
            if original!=new_source:os.replace(original,new_source)
            parsed=publishing.parse_match_title(raw_title)
            p['title']=parsed['title'] if parsed else (raw_title[:140].strip() or 'Матч')
            p['title_score']=parsed.get('score') if parsed else None;p['raw_title']=raw_title
            p['source_file']='source/'+new_source.name
            music=request.get('music','')
            if music:
                if not Path(music).is_file():raise FileNotFoundError('Музыка табылмады: '+music)
                music_dest=source/('background'+Path(music).suffix.lower());shutil.copy2(music,music_dest)
                p['music_file']='source/'+music_dest.name;p['music_title']=Path(music).stem
            stage_style(p);p=rename_project(p,p['title']);p['source_ready']=True
            checkpoint(p,'source',on_checkpoint)
        else:
            log('Сақталған бастапқы видео қолданылды — қайта жүктелмейді.')
        if not media_path(p,p['source_file']).is_file():raise FileNotFoundError('Жобаның бастапқы видеосы табылмады.')
        if on_source:on_source(dict(title=p['title'],directory=p['directory'],video=str(media_path(p,p['source_file']))))
        log('@progress:download:1:Бастапқы видео дайын')
        if not p.get('analysis_ready'):
            log('@progress:analyze:0:Есеп пен қызықты сәттерді анықтау')
            p['status']='analyzing';save_project(p)
            analysis=core.analyze(str(media_path(p,p['source_file'])),max(4,settings['target']-(3 if settings['intro'] else 0)),tuple(settings['roi']),settings['use_ocr'],log,cancel)
            p['analysis']=analysis;p['clips']=analysis['clips'];p['warnings']=analysis.get('warnings',[])
            p['score']=analysis.get('score') or p.get('title_score')
            p['score_source']='video' if analysis.get('score') else ('title' if p.get('title_score') else 'unknown')
            if not publishing.parse_match_title(p['title']):p['warnings'].append('Командалар анықталмады. Нәтижедегі атауды тексеріңіз.')
            if not p['score']:p['warnings'].append('Есеп оқылмады. Қажет болса қолмен түзетіңіз.')
            p['analysis_ready']=True;checkpoint(p,'analysis',on_checkpoint)
        else:log('Сақталған талдау қолданылды — қайта талданбайды.')
        log('@progress:analyze:1:Талдау аяқталды')
        if not p['clips']:raise ValueError('Сәттер табылмады. Уақыттарын қолмен енгізіңіз.')
        result=render_project(p,log,cancel)
        checkpoint(p,'ready',on_checkpoint)
        return result
    except BaseException as e:
        p['status']='cancelled' if isinstance(e,core.Cancelled) else 'error';p['error']=str(e);save_project(p)
        log('Жоба сақталды: '+p['directory']);raise


def rerender(path,score,title=None,clips=None,settings=None,log=print,cancel=None):
    project=load_project(path)
    normalized=score.strip().replace('-',':')
    effective={**DEFAULTS,**project.get('settings',{}),**(settings or {})}
    if (normalized or effective['show_final']) and not re.fullmatch(r'\d{1,2}:\d{1,2}',normalized):raise ValueError('Дұрыс есепті 1:3 түрінде енгізіңіз.')
    project['score']=normalized or None;project['score_source']='manual' if normalized else 'unknown'
    if title and title.strip():project['title']=title.strip()
    if clips is not None:project['clips']=clips
    if settings:project['settings'].update(settings)
    # No download and no analyze calls: source and selected moments are reused.
    return render_project(project,log,cancel)
