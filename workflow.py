"""Persistent local projects: automatic creation, review, correction, and retry."""
from pathlib import Path
from datetime import datetime
import json
import os
import re
import shutil
import tempfile
import uuid
import core
import downloader
import publishing

DEFAULTS=dict(target=180,roi=[0,0,.5,.17],use_ocr=True,music_level=.18,
              source_level=.2,crop_top=.15,replays=True,replay_speed=.5)


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
    return text


def output_files(project):
    folder=Path(project['directory'])
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
        for p in written:p.unlink(missing_ok=True)
        for old,backup in backups:
            if backup.exists():os.replace(backup,old)
        raise
    project.update(video_file=video.name,text_file=text.name,status='ready')
    project['revision']=int(project.get('revision',0))+1
    project['updated_at']=datetime.now().isoformat(timespec='seconds')
    save_project(project)
    return output_files(project)


def render_project(project,log=print,cancel=None):
    settings={**DEFAULTS,**project.get('settings',{})}
    source=media_path(project,project['source_file'])
    music=media_path(project,project['music_file']) if project.get('music_file') else None
    if not source.is_file():raise FileNotFoundError('Жобаның бастапқы видеосы табылмады: '+str(source))
    if music and not music.is_file():raise FileNotFoundError('Жобаның музыкасы табылмады: '+str(music))
    project['status']='rendering';save_project(project)
    log('Монтаж және YouTube TXT дайындау…')
    folder=Path(project['directory'])
    try:
        with tempfile.TemporaryDirectory(prefix='.render-',dir=folder) as tmp:
            tmp=Path(tmp);video=tmp/'result.mp4';text=tmp/'result.txt'
            core.render(str(source),str(music) if music else None,project['clips'],video,
                title=project['title'],score=project.get('score') or '?',
                music_level=settings['music_level'],source_level=settings['source_level'],
                crop_top=settings['crop_top'],replays=settings['replays'],replay_speed=settings['replay_speed'],
                max_seconds=settings['target'],log=log,cancel=cancel)
            text.write_text(project_text(project),encoding='utf-8-sig')
            if cancel and cancel.is_set():raise core.Cancelled()
            return commit_outputs(project,video,text)
    except BaseException as e:
        project['status']='cancelled' if isinstance(e,core.Cancelled) else 'error'
        project['error']=str(e);save_project(project);raise


def create_project(base,url='',local_video='',music='',settings=None,title_hint='',log=print,cancel=None):
    settings={**DEFAULTS,**(settings or {})}
    if not url and not Path(local_video).is_file():raise ValueError('YouTube сілтемесін немесе видео файлын беріңіз.')
    if url:url=downloader.normalize_url(url)
    root=Path(base).resolve()/'output';root.mkdir(parents=True,exist_ok=True)
    folder=root/('Жоба_'+datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'_'+uuid.uuid4().hex[:6])
    source=folder/'source';source.mkdir(parents=True)
    p=dict(kind='football_project',schema_version=1,directory=str(folder),status='starting',
           title=title_hint or 'Матч',source_url=url,source_file='source/original.mp4',
           music_file='',score=None,clips=[],settings=settings,revision=0,warnings=[])
    save_project(p)
    log('Жоба: '+str(folder))
    try:
        if cancel and cancel.is_set():raise core.Cancelled()
        if url:
            p['status']='downloading';save_project(p)
            result=downloader.download(url,source,settings.get('quality',1080),log,cancel)
            original=Path(result['path']);raw_title=result.get('title','')
        else:
            log('Бастапқы видеоны жобаға көшіру…')
            original=source/('original'+Path(local_video).suffix.lower())
            shutil.copy2(local_video,original);raw_title=title_hint or Path(local_video).stem
        new_source=source/('original'+original.suffix.lower())
        if original!=new_source:os.replace(original,new_source)
        parsed=publishing.parse_match_title(raw_title)
        p['title']=parsed['title'] if parsed else (raw_title[:140].strip() or 'Матч')
        p['title_score']=parsed.get('score') if parsed else None
        p['raw_title']=raw_title
        p['source_file']='source/'+new_source.name
        if music:
            if not Path(music).is_file():raise FileNotFoundError('Музыка табылмады: '+music)
            music_dest=source/('background'+Path(music).suffix.lower());shutil.copy2(music,music_dest)
            p['music_file']='source/'+music_dest.name;p['music_title']=Path(music).stem
        p=rename_project(p,p['title']);save_project(p)
        p['status']='analyzing';save_project(p)
        analysis=core.analyze(str(media_path(p,p['source_file'])),settings['target'],tuple(settings['roi']),
                              settings['use_ocr'],log,cancel)
        p['analysis']=analysis;p['clips']=analysis['clips'];p['warnings']=analysis.get('warnings',[])
        p['score']=analysis.get('score') or p.get('title_score')
        p['score_source']='video' if analysis.get('score') else ('title' if p.get('title_score') else 'unknown')
        if not parsed:p['warnings'].append('Командалар анықталмады. Нәтижедегі атауды тексеріңіз.')
        if not p['score']:p['warnings'].append('Есеп оқылмады. Нәтижеде «Есеп анықталмады» көрсетіледі; түзетіп қайта жасаңыз.')
        save_project(p)
        if not p['clips']:raise ValueError('Сәттер табылмады. Жоба сақталды; үзінді уақыттарын қолмен енгізіп қайта жасаңыз.')
        return render_project(p,log,cancel)
    except BaseException as e:
        p['status']='cancelled' if isinstance(e,core.Cancelled) else 'error';p['error']=str(e);save_project(p)
        log('Жоба сақталды: '+p['directory']);raise


def rerender(path,score,title=None,clips=None,settings=None,log=print,cancel=None):
    project=load_project(path)
    normalized=score.strip().replace('-',':')
    if not re.fullmatch(r'\d{1,2}:\d{1,2}',normalized):raise ValueError('Дұрыс есепті 1:3 түрінде енгізіңіз.')
    project['score']=normalized;project['score_source']='manual'
    if title and title.strip():project['title']=title.strip()
    if clips is not None:project['clips']=clips
    if settings:project['settings'].update(settings)
    # No download and no analyze calls: source and selected moments are reused.
    return render_project(project,log,cancel)
