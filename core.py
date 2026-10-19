"""Local football highlight assistant. No API key and no media uploads."""
from __future__ import annotations
import collections
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave
import numpy as np
from timeline import plan_timeline, segment_duration

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

class Cancelled(Exception):
    pass

def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def read_progress(path,duration):
    try:
        with open(path,'rb') as f:
            f.seek(0,2);size=f.tell();f.seek(max(0,size-4096))
            values=re.findall(rb'(?:^|\n)out_time_us=(-?\d+)\r?\n',f.read())
        if values and duration>0:return max(0.,min(.999,int(values[-1])/(duration*1000000)))
    except (OSError,ValueError):pass
    return None


def run(args, cancel=None, progress=None, duration=None):
    """Drain stderr to disk and read FFmpeg's measured media-time progress."""
    with tempfile.TemporaryFile() as err,tempfile.TemporaryDirectory(prefix='football-progress-') as tmp:
        path=Path(tmp)/'progress.txt'
        command=[str(a) for a in args]
        if progress is not None and duration:
            command=command[:1]+['-progress',str(path),'-nostats']+command[1:]
        p = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=err, creationflags=CREATE_NO_WINDOW)
        last_fraction=None
        try:
            while True:
                try:
                    code = p.wait(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel and cancel.is_set():
                        p.terminate()
                        raise Cancelled('Тоқтатылды')
                    if progress is not None and duration:
                        fraction=read_progress(path,duration)
                        if fraction is not None and fraction!=last_fraction:
                            progress(fraction);last_fraction=fraction
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        if code:
            err.seek(0)
            raise RuntimeError(err.read().decode('utf-8', 'replace')[-3000:])
        if progress is not None:progress(1.)


def metadata(video):
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        w, h = int(cap.get(3)), int(cap.get(4))
        if not cap.isOpened() or fps <= 0 or n <= 0 or w < 2 or h < 2:
            raise ValueError('Видео оқылмады. MP4 / H.264 файлымен көріңіз.')
        return dict(duration=n/fps, width=w, height=h, fps=fps)
    finally:
        cap.release()

def score_from_ocr(result):
    """Accept only a short, high-confidence scoreboard row. Ignore match clock."""
    rows = []
    for box, text, conf in result or []:
        if float(conf) < .55:
            continue
        y = sum(float(p[1]) for p in box)/4
        x = min(float(p[0]) for p in box)
        height = max(float(p[1]) for p in box)-min(float(p[1]) for p in box)
        row = next((r for r in rows if abs(r['y']-y) < max(9, height*.7)), None)
        if row is None:
            row = dict(y=y, parts=[])
            rows.append(row)
        row['parts'].append((x, str(text)))
    for row in sorted(rows, key=lambda r: r['y']):
        text = ' '.join(t for _, t in sorted(row['parts']))
        # Remove clocks first: "83:24" must never become an 8:3 score.
        text = re.sub(r'\b\d{1,3}\s*[:.]\s*\d{2}\b', ' ', text)
        matches = re.findall(r'(?<!\d)([0-9])\s*[-:–]\s*([0-9])(?!\d)', text)
        if not matches:
            matches = re.findall(r'(?<!\d)([0-9])\s+([0-9])(?!\d)', text)
        if len(matches) == 1:
            return tuple(map(int, matches[0]))
    return None

def stable_scores(readings):
    """Two matching reads within 20s; tolerate replays hiding the scoreboard."""
    events = []
    pending, count, first, last_seen = None, 0, 0, -100
    for t, score in readings:
        if score is None:
            continue
        score = tuple(score)
        if score == pending and t-last_seen <= 20:
            count += 1
        else:
            pending, count, first = score, 1, t
        last_seen = t
        if count >= 2 and (not events or events[-1]['score'] != score):
            events.append(dict(time=first, score=score))
    return events

def clean_score_events(events):
    """Ignore an inconsistent OCR state only when the following state resolves it.

    Keep genuine multi-goal jumps as unknown gaps, and keep unit increases followed
    by reversals so the existing VAR handling can retract them.
    """
    def increase(a,b):
        return sum(b)-sum(a) if all(y>=x for x,y in zip(a,b)) else None
    cleaned=[]
    for i,event in enumerate(events):
        if cleaned and i+1<len(events):
            previous=cleaned[-1]['score'];current=event['score'];following=events[i+1]['score']
            if (increase(previous,current)!=1 and increase(previous,following)==1
                    and increase(current,following) is None):
                continue
        cleaned.append(event)
    return cleaned


def confirmed_goal_candidates(events):
    # A later return to an earlier score retracts the intervening scoreboard state.
    # This handles explicit VAR score reversals, not every possible VAR decision.
    history=[]
    for ev in clean_score_events(events):
        score=tuple(ev['score'])
        earlier=next((i for i,x in enumerate(history) if tuple(x['score'])==score),None)
        if earlier is not None:
            history=history[:earlier+1]
        else:
            history.append(ev)
    goals=[]
    for prev,ev in zip(history,history[1:]):
        if sum(ev['score'])-sum(prev['score'])==1 and all(a>=b for a,b in zip(ev['score'],prev['score'])):
            goals.append(dict(start=ev['time']-14,end=ev['time']+3,priority=100,
                              reason='Есеп өзгерді: '+':'.join(map(str,ev['score'])),kind='goal',goal_at=ev['time']-6))
    return goals

def choose_clips(candidates, duration, target):
    target = min(float(target), duration)
    chosen = []
    for c in sorted(candidates, key=lambda c: c['priority'], reverse=True):
        start, end = max(0, c['start']), min(duration, c['end'])
        # Keep non-overlapping footage. Do not silently repeat the same goal.
        overlaps=[x for x in chosen if start < x['end']+1 and end > x['start']-1]
        if overlaps:
            if c.get('kind')=='goal' and all(x.get('kind')=='goal' for x in overlaps):
                lo=min(start,*(x['start'] for x in overlaps));hi=max(end,*(x['end'] for x in overlaps))
                used=sum(x['end']-x['start'] for x in chosen)
                if used-sum(x['end']-x['start'] for x in overlaps)+(hi-lo)<=target:
                    times=sorted({t for x in [*overlaps,c] for t in x.get('goal_times',[x.get('goal_at',max(0,x['start']))])})
                    combined=dict(overlaps[0],start=round(lo,2),end=round(hi,2),goal_times=times,
                                  goal_at=min(hi-.05,max(lo,times[0])),
                                  reason=' / '.join(dict.fromkeys(x.get('reason','Гол') for x in [*overlaps,c])))
                    chosen=[x for x in chosen if x not in overlaps];chosen.append(combined)
            continue
        left = target-sum(x['end']-x['start'] for x in chosen)
        if left < 3:
            continue
        if end-start > left+.001:
            continue
        if end-start >= 3:
            selected=dict(c,start=round(start,2),end=round(end,2))
            if selected.get('goal_at') is not None:
                selected['goal_at']=min(end-.05,max(start,float(selected['goal_at'])))
            chosen.append(selected)
    return sorted(chosen, key=lambda x: x['start'])

def audio_candidates(energy,duration):
    """Only distinct energy peaks. Steady sound never fills the time budget."""
    energy=np.asarray(energy,dtype=float)
    if len(energy)<3:return []
    smooth=np.convolve(energy,np.ones(3)/3,mode='same')
    threshold=max(.015,float(np.quantile(smooth,.85)),float(np.median(smooth))*1.12)
    peaks=[]
    for i in range(1,len(smooth)-1):
        if smooth[i]<threshold or smooth[i]<smooth[i-1] or smooth[i]<=smooth[i+1]:continue
        local=smooth[max(0,i-15):min(len(smooth),i+16)]
        if smooth[i]<float(np.median(local))*1.08:continue
        if i<min(15,duration*.05) or i>duration-3:continue
        peaks.append(i)
    chosen=[]
    for i in sorted(peaks,key=lambda i:smooth[i],reverse=True):
        if any(abs(i-j)<12 for j in chosen):continue
        chosen.append(i)
    return [dict(start=float(i)-6,end=float(i)+5,priority=float(smooth[i])*10,
                 reason='Дыбыстағы эмоция — тексеріңіз') for i in chosen]


def ocr_engine():
    # Disable ONNX Runtime telemetry before any OCR inference session is created.
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)


def analyze(video, target=180, roi=(0,0,.5,.17), use_ocr=True, log=print, cancel=None):
    """Use score changes and crowd/commentary energy; not semantic goal recognition."""
    log('@progress:analyze:0:Видеоны талдау')
    info = metadata(video)
    duration = info['duration']
    readings, warnings = [], []
    if use_ocr:
        try:
            import cv2
            log('Экрандағы есепті оқу…')
            engine = ocr_engine()
            cap = cv2.VideoCapture(str(video))
            try:
                # Detailed sampling near the end helps avoid using an earlier score.
                from highlight_signals import score_sample_times
                times=score_sample_times(duration)
                x,y,rw,rh = roi
                for i,t in enumerate(times):
                    if cancel and cancel.is_set():
                        raise Cancelled()
                    cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
                    ok, frame = cap.read()
                    score = None
                    if ok:
                        h,w = frame.shape[:2]
                        crop = frame[int(y*h):max(int(y*h)+1,int((y+rh)*h)),
                                     int(x*w):max(int(x*w)+1,int((x+rw)*w))]
                        if crop.size:
                            crop = cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
                            result,_ = engine(crop)
                            score = score_from_ocr(result)
                    readings.append((round(t,2),score))
                    if i%12 == 0:
                        log(f'Есепті оқу: {i+1}/{len(times)} кадр')
                from highlight_signals import refinement_times
                extra=refinement_times(readings,duration)
                for j,t in enumerate(extra):
                    if cancel and cancel.is_set():raise Cancelled()
                    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();score=None
                    if ok:
                        h,w=frame.shape[:2]
                        crop=frame[int(y*h):max(int(y*h)+1,int((y+rh)*h)),int(x*w):max(int(x*w)+1,int((x+rw)*w))]
                        if crop.size:
                            result,_=engine(cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
                            score=score_from_ocr(result)
                    readings.append((t,score))
                    if j%20==0:log(f'Гол маңындағы есепті нақтылау: {j+1}/{len(extra)} кадр')
                readings.sort(key=lambda item:item[0])
            finally:
                cap.release()
        except Cancelled:
            raise
        except Exception as e:
            warnings.append('OCR орындалмады: '+str(e))
    events = stable_scores(readings)
    final = None
    if events:
        last = events[-1]
        # Must still be visible in the final 20% (or 35 seconds of a short clip).
        recent = [s for t,s in readings if t >= duration-min(35,duration*.2) and s]
        if len(recent)>=2 and recent[-1] == last['score'] and recent.count(last['score'])>=2:
            final = ':'.join(map(str,last['score']))
    candidates = confirmed_goal_candidates(events)
    ignored=[event for event in events if event not in clean_score_events(events)]
    if ignored:warnings.append(f'Кейінгі есепке қайшы OCR көрсеткіштері ескерілмеді: {len(ignored)}.')
    cleaned=clean_score_events(events)
    if any(sum(b['score'])-sum(a['score'])>1 and all(y>=x for x,y in zip(a['score'],b['score'])) for a,b in zip(cleaned,cleaned[1:])):
        warnings.append('Есеп бірден бірнеше голға өсті. Жеке гол уақыттарын қолмен тексеріңіз.')
    energy=np.asarray([],dtype=float)
    log('@progress:analyze:0.85:Комментатор мен стадион дыбысын талдау')
    log('Комментатор мен стадион дыбысын талдау…')
    try:
        with tempfile.TemporaryDirectory(prefix='football-audio-') as tmp:
            audio=Path(tmp)/'audio.wav'
            run([ffmpeg(),'-v','error','-i',video,'-vn','-ac','1','-ar','8000','-c:a','pcm_s16le','-y',audio],cancel)
            with wave.open(str(audio),'rb') as wf:
                data=np.frombuffer(wf.readframes(wf.getnframes()),dtype='<i2').astype(np.float32)/32768
            # One-second RMS, then smooth to prefer sustained excitement over clicks.
            n=len(data)//8000
            if n:
                energy=np.sqrt(np.mean(data[:n*8000].reshape(n,8000)**2,axis=1))
                candidates.extend(audio_candidates(energy,duration))
    except Cancelled:
        raise
    except Exception as e:
        warnings.append('Дыбыс талданбады: '+str(e))
    from highlight_signals import fuse_candidates,inspect_candidates,remove_repeated_candidates
    candidates=fuse_candidates(candidates,energy)
    removed=0
    try:
        log('Дыбыс, есеп және кадр белгілерін салыстыру…')
        candidates=inspect_candidates(video,candidates,cancel,log)
        candidates,removed=remove_repeated_candidates(candidates)
    except Cancelled:raise
    except Exception as e:warnings.append('Кадрларды салыстыру орындалмады: '+str(e))
    if removed:warnings.append(f'Өте ұқсас қайталанған сәттер алынып тасталды: {removed}.')
    detected_goals=[dict(c) for c in candidates if c.get('kind')=='goal']
    # Reserve a final score card and 0.1s for container/audio rounding.
    limit=min(180.0,float(target))
    if not math.isfinite(limit) or limit<4:raise ValueError('Уақыт шегі: 4–180 секунд.')
    clips=choose_clips(candidates,duration,limit-3.1)
    if not clips:
        warnings.append('Сәттер автоматты табылмады. Уақыттарды қолмен енгізіңіз.')
    if not final:
        warnings.append('Соңғы есеп анық оқылмады. Есепті өзіңіз енгізіңіз немесе бос қалдырыңыз.')
    warnings.append('Бұл — видеода соңғы көрінген есеп. Видео матч аяқталмай тұрып үзілген болса, финалдық есеп болмауы мүмкін.')
    log('@progress:analyze:1:Талдау аяқталды')
    return dict(video=str(Path(video).resolve()),info=info,score=final,clips=clips,
                score_events=events,warnings=warnings,ocr_readings=readings,duplicate_candidates_removed=removed,
                detected_goals=detected_goals,ignored_score_states=ignored)

def validate_clips(clips,duration):
    if not clips:
        raise ValueError('Кемінде бір үзінді таңдаңыз.')
    total=0
    for c in clips:
        a,b=float(c['start']),float(c['end'])
        if not math.isfinite(a+b) or a<0 or b>duration+.05 or b-a<.2:
            raise ValueError(f'Уақыт қате: {a} — {b}. Видео: {duration:.1f} секунд.')
        total+=b-a
    if total>180:
        raise ValueError('Жалпы ұзақтық 180 секундтан аспасын.')
    return total

def make_card(path, title, score, label, final_card=False,style=None,language='kk'):
    from visuals import card
    card(path,title,score,label,final_card,style=style,language=language)

def make_goal_image(path):
    from visuals import goal_frame
    goal_frame(.8).save(path)


def render(video,music,clips,output,title='',score='',music_level=.18,source_level=.20,
           crop_top=.15,show_final=True,log=print,cancel=None,replays=True,replay_speed=.5,max_seconds=180,goal_animation=True,action_camera=False,intro=True,logo_dir=None,channel_style=None,language='kk'):
    from content_language import strings
    text=strings(language)
    from channel_templates import style as validate_style
    channel_style=validate_style(channel_style)
    info=metadata(video)
    validate_clips(clips,info['duration'])
    from review_model import validate_camera
    for clip in clips:validate_camera(clip)
    timeline=plan_timeline(clips,max_seconds,bool(score and show_final),replays,replay_speed,intro_seconds=3 if intro else 0)
    clips=timeline['segments']
    total=timeline['duration']-(3 if score and show_final else 0)
    for note in timeline['notes']:log(note)
    if not 0<=crop_top<=.35:
        raise ValueError('Жоғарғы қию: 0–35%.')
    if total+(3 if score and show_final else 0)>180:
        raise ValueError('Есеп кадрын қоса жалпы ұзақтық 180 секундтан аспасын.')
    if score and score!='?' and not re.fullmatch(r'\d{1,2}\s*[:\-]\s*\d{1,2}',score):
        raise ValueError('Есепті 1:3 түрінде жазыңыз немесе бос қалдырыңыз.')
    output=Path(output).resolve()
    if output in [Path(video).resolve(),Path(music).resolve() if music else None]:
        raise ValueError('Нәтижені бастапқы файлдың үстіне жазуға болмайды.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='football-render-',dir=str(output.parent)) as tmp:
        tmp=Path(tmp);parts=[]
        if intro:
            from visuals import intro_layers
            from logos import pair
            log('@progress:logos:0:Команда логотиптерін іздеу')
            badges=pair(title,logo_dir or tmp/'logos',log,cancel)
            if cancel and cancel.is_set():raise Cancelled()
            log('@progress:logos:1:Логотиптер дайын')
            log('@progress:render:0:3 секундтық кіріспе')
            base,left,right=intro_layers(tmp,title,badges,style=channel_style,language=language)
            intro_part=tmp/'intro.mp4'
            log('3 секундтық матч кіріспесі…')
            intro_filter="[0:v][1:v]overlay=x='-720*pow(1-clip(t/0.75,0,1),3)':y=0[a];[a][2:v]overlay=x='720*pow(1-clip(t/0.75,0,1),3)':y=0,fade=t=in:d=0.12,fade=t=out:st=2.8:d=0.2,setsar=1,format=yuv420p[v]"
            run([ffmpeg(),'-v','error','-loop','1','-framerate','30','-i',base,
                 '-i',left,'-i',right,'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
                 '-filter_complex_threads','2','-filter_complex',intro_filter,'-map','[v]','-map','3:a',
                 '-t','3','-c:v','libx264','-preset','fast','-crf','21','-threads','2',
                 '-c:a','aac','-ar','48000','-ac','2','-y',intro_part],cancel)
            if abs(metadata(intro_part)['duration']-3)>.12:raise RuntimeError('Кіріспе толық шықпады.')
            parts.append(intro_part)
        # Normalize source audio; original broadcasts differ greatly in loudness.
        silent=False
        try:
            run([ffmpeg(),'-v','error','-i',video,'-t','0.1','-map','0:a:0','-f','null','-'],cancel)
        except RuntimeError:
            silent=True
        crop_y=int(info['height']*crop_top)//2*2
        crop_h=(info['height']-crop_y)//2*2
        crop_w=info['width']//2*2
        tracking_cache={}
        fire_pattern=None
        for i,c in enumerate(clips):
            log(f'@progress:render:{i/max(1,len(clips))}:Үзінді {i+1}/{len(clips)}')
            log(f'Монтаж: {i+1}/{len(clips)}')
            part=tmp/f'{i:03}.mp4';card=tmp/f'{i:03}.png'
            is_replay=c.get('is_replay',False)
            speed=float(c.get('speed',1));out_duration=segment_duration(c)
            make_card(card,title,'',f"{text['replay']} • {speed:g}×" if is_replay else text['highlights'].upper(),style=channel_style,language=language)
            use_crop=action_camera
            if action_camera and not c.get('focus_points'):
                import camera
                key=(c['start'],c['end'],c.get('goal_at'),c.get('zoom',1))
                if key not in tracking_cache:
                    log('Доптың қозғалысы мен кадр сенімділігін тексеру…')
                    tracking_cache[key]=camera.track_details(video,c['start'],c['end'],crop_top,cancel,c.get('goal_at'),c.get('zoom',1))
                if not tracking_cache[key]['safe_crop']:
                    use_crop=False;log('Доп бағыты сенімсіз — осы үзіндіде толық алаң сақталды.')
            if use_crop:
                import camera
                _,_,_,portrait_w,portrait_h=camera.geometry(info['width'],info['height'],crop_top,c.get('zoom',1))
                if c.get('focus_points'):
                    xs,ys=camera.manual_tracks(c,info['height'],crop_y,crop_h)
                    y=camera.crop_expression(ys,crop_h,portrait_h,speed)
                else:
                    xs=tracking_cache[key]['points'];y='(ih-oh)/2'
                x=camera.crop_expression(xs,crop_w,portrait_w,speed)
                vf=f"[0:v]setpts=(PTS-STARTPTS)/{speed},crop={crop_w}:{crop_h}:0:{crop_y},crop={portrait_w}:{portrait_h}:x='{x}':y='{y}',scale=720:1280,fps=30[v0];[v0][1:v]overlay=0:0,setsar=1,format=yuv420p[carded]"
            else:
                vf=f'[0:v]crop={crop_w}:{crop_h}:0:{crop_y},setpts=(PTS-STARTPTS)/{speed},fps=30,split=2[b][f];[b]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,boxblur=10:2,scale=720:1280,eq=brightness=-.22[bg];[f]scale=720:400:force_original_aspect_ratio=decrease,pad=720:400:(ow-iw)/2:(oh-ih)/2:black[fg];[bg][fg]overlay=0:440[v0];[v0][1:v]overlay=0:0,setsar=1,format=yuv420p[carded]'
            vf+=';[carded]null[v]'
            args=[ffmpeg(),'-v','error','-ss',c['start'],'-t',c['end']-c['start'],'-i',video,'-i',card]
            has_goal=goal_animation and c.get('kind')=='goal' and not is_replay
            audio_index=2
            if has_goal:
                if fire_pattern is None:
                    from visuals import goal_sequence
                    fire_pattern=goal_sequence(tmp/'fire',cancel,language=language)
                args+=['-framerate','30','-i',fire_pattern];audio_index=3
                g=max(0,(c['goal_at']-c['start'])/speed)
                vf=vf.rsplit(';[carded]null[v]',1)[0]
                vf+=f";[2:v]format=rgba,fade=t=in:st=0:d=0.12:alpha=1,fade=t=out:st=1.8:d=0.4:alpha=1,setpts=PTS+{g}/TB[goal];[carded][goal]overlay=x=32:y='800+28*exp(-8*(t-{g}))*cos(18*(t-{g}))':enable='between(t,{g},{g+2.2})':eof_action=pass:repeatlast=0[v]"

            if silent:
                args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                af=f'[{audio_index}:a]anull[a]'
            else:
                af=f'[0:a]asetpts=PTS-STARTPTS,aresample=48000,atempo={speed},loudnorm=I=-18:TP=-2:LRA=11,volume={source_level}[a]'
            args+=['-filter_complex_threads','2','-filter_complex',vf+';'+af,'-map','[v]','-map','[a]',
                   '-t',out_duration,'-c:v','libx264','-preset','fast','-crf','21','-threads','2',
                   '-c:a','aac','-ar','48000','-ac','2','-y',part]
            report=lambda fraction:log(f'@progress:render:{(i+fraction)/max(1,len(clips))}:Үзінді {i+1}/{len(clips)}')
            run(args,cancel,progress=report,duration=out_duration)
            # A process can exit successfully after writing incomplete media.
            # Validate each container before concatenating it.
            try:
                metadata(part)
            except ValueError:
                log('Үзіндіні қайта экспорттау…')
                run(args,cancel)
                metadata(part)
            if abs(metadata(part)['duration']-out_duration)>.12:
                raise RuntimeError('Қайталау/үзінді толық шықпады. Экспорт тоқтатылды.')
            parts.append(part)
            log(f'@progress:render:{(i+1)/max(1,len(clips))}:Үзінді дайын {i+1}/{len(clips)}')
        if score and show_final:
            log('Соңғы есеп кадры…')
            card=tmp/'final.png';part=tmp/'final.mp4'
            make_card(card,title,score,'',True,style=channel_style,language=language)
            run([ffmpeg(),'-v','error','-f','lavfi','-i','color=c=0x'+channel_style['background_color'][1:]+':s=720x1280:r=30:d=3',
                 '-i',card,'-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-filter_complex',
                 '[0:v][1:v]overlay=0:0,setsar=1,format=yuv420p[v]','-map','[v]','-map','2:a',
                 '-t','3','-c:v','libx264','-preset','fast','-crf','21','-threads','2',
                 '-c:a','aac','-ar','48000','-ac','2','-y',part],cancel)
            metadata(part)
            parts.append(part);total+=3
        log('@progress:save:0:Видеоны біріктіру және музыканы қосу')
        concat=tmp/'concat.txt'
        # Temp directory names generated by tempfile contain no quotes in filenames.
        concat.write_text(''.join("file '"+p.name+"'\n" for p in parts),encoding='utf-8')
        mixed=tmp/'finished.mp4'
        args=[ffmpeg(),'-v','error','-f','concat','-safe','0','-i',concat]
        if music:
            args+=['-stream_loop','-1','-i',music,'-filter_complex',
                   f'[1:a]aresample=48000,loudnorm=I=-18:TP=-2:LRA=11,volume={music_level},afade=t=in:d=0.3,afade=t=out:st={max(0,total-2)}:d=2[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]',
                   '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k']
        else:
            args+=['-map','0:v','-map','0:a','-c','copy']
        args+=['-t',min(total,179.9),'-movflags','+faststart','-y',mixed]
        run(args,cancel,progress=lambda fraction:log(f'@progress:save:{fraction*.5}:Музыка және видео'),duration=total)
        log('@progress:save:0.5:Дайын видеоны толық тексеру')
        result_info=metadata(mixed)
        if abs(result_info['duration']-total)>.6:
            raise RuntimeError('Экспорт толық аяқталмады. Файл сақталмады, қайталап көріңіз.')
        run([ffmpeg(),'-v','error','-i',mixed,'-f','null','-'],cancel,
            progress=lambda fraction:log(f'@progress:save:{.5+fraction*.25}:Видеоны тексеру'),duration=total)
        # Complete the file first; cancelled / failed exports cannot replace a good output.
        os.replace(mixed,output)
    return str(output)
