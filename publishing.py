"""Evidence-based text templates; no invented scorers, minutes or competition."""
from pathlib import Path
import os
import re
import tempfile


def parse_match_title(title):
    text=re.sub(r'[\r\n]+',' ',title or '').strip()
    for section in re.split(r'\s*[|｜]\s*',text):
        section=re.sub(r'(?i)^\s*(?:highlights?|обзор(?: матча)?|шолу)\s*[:：-]?\s*','',section)
        score=re.search(r'(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)',section)
        pair=re.split(r'\s+(?:v(?:s)?\.?|x)\s+',section,flags=re.I,maxsplit=1)
        if len(pair)==2:
            a,b=pair
            if score:
                a=a.replace(score.group(0),'');b=b.replace(score.group(0),'')
            s=score.group(1)+':'+score.group(2) if score else None
        elif score and section[:score.start()].strip() and section[score.end():].strip():
            a,b=section[:score.start()].strip(),section[score.end():].strip()
            s=score.group(1)+':'+score.group(2)
        else:
            pair=re.split(r'\s+[-–—]\s+',section,maxsplit=1)
            if len(pair)!=2:continue
            a,b=pair
            if score:a=a.replace(score.group(0),'');b=b.replace(score.group(0),'')
            s=score.group(1)+':'+score.group(2) if score else None
        b=re.split(r'\s+[•｜|]\s+|\s+\(',b)[0].strip()
        a=a.strip(' -–—:');b=b.strip(' -–—:')
        if 1<=len(a)<=80 and 1<=len(b)<=80 and not re.search(r'\d{4}',a+b):
            return dict(team_a=a,team_b=b,title=a+' — '+b,score=s)
    return None


def safe_name(value):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',value)
    value=re.sub(r'\s+',' ',value).strip(' .')[:64].rstrip(' .')
    if not value:raise ValueError('Матч атауын енгізіңіз.')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        value='Match_'+value
    return value


def youtube_text(team_a,team_b,score,source_url='',music_name=''):
    if not team_a.strip() or not team_b.strip():raise ValueError('Екі команданың атын енгізіңіз.')
    if score!='?' and not re.fullmatch(r'\d{1,2}:\d{1,2}',score):raise ValueError('Расталған есепті 1:3 түрінде енгізіңіз.')
    score_text=score if score!='?' else 'анықталмады'
    match=f'{team_a.strip()} — {team_b.strip()}'
    title=f'{match} {score if score!="?" else ""} ⚽ Матчтың үздік сәттері! #Shorts'
    if len(title)>100:title=f'{match[:65]} {score} ⚽ #Shorts'[:100]
    team_hashes=['#'+re.sub(r'[^\w]','',t,flags=re.U) for t in (team_a,team_b)]
    hashtags=' '.join(dict.fromkeys(['#рекомендации','#рекомендация',*team_hashes,'#Футбол','#Football','#Highlights','#Shorts']))
    desc=f'⚽ {match}\n\nЕсеп: {score_text}.\nМатчтың іріктелген қызықты сәттерін тамашала!\n\nҚай сәт саған көбірек ұнады? Пікірге жаз! 👇\nФутбол үзінділері үшін арнаға жазыл!'
    if music_name:desc+='\n\n🎵 Фондық музыка: '+music_name
    if source_url:desc+='\nБастапқы видео: '+source_url
    tags=[]
    for item in [team_a,team_b,match,f'{match} {score}' if score!='?' else match,'футбол','матчтың үздік сәттері','голдар','футбол шортс','football','football highlights','football shorts','goals','shorts']:
        item=item.replace(',',' ').strip()
        if item not in tags and len(', '.join(tags+[item]))<=500:tags.append(item)
    return f'ВИДЕО АТАУЫ\n{title}\n\nСИПАТТАМА (хештегтерімен бірге)\n{desc}\n\n{hashtags}\n\nТЕГТЕР\n'+', '.join(tags)+'\n'


def export_package(base,video,music,clips,team_a,team_b,score,source_url='',**options):
    import core
    name=safe_name(team_a+' — '+team_b)
    text=youtube_text(team_a,team_b,score,source_url,Path(music).stem if music else '')
    output=Path(base).resolve()/'output';output.mkdir(parents=True,exist_ok=True)
    # Build both files privately, then publish the complete folder in one rename.
    with tempfile.TemporaryDirectory(prefix='.export-',dir=output) as tmp:
        staging=Path(tmp)/'match';staging.mkdir()
        core.render(video,music,clips,staging/(name+'.mp4'),title=team_a+' — '+team_b,score=score,**options)
        (staging/(name+'.txt')).write_text(text,encoding='utf-8-sig')
        folder=output/name;counter=2
        while True:
            if folder.exists():
                folder=output/(name+f' ({counter})');counter+=1;continue
            try:staging.rename(folder);break
            except FileExistsError:continue
        return dict(directory=str(folder),video=str(folder/(name+'.mp4')),text=str(folder/(name+'.txt')))
