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

def run(args, cancel=None):
    """Drain stderr to a file, so long renders cannot deadlock on pipe buffers."""
    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=err, creationflags=CREATE_NO_WINDOW)
        try:
            while True:
                try:
                    code = p.wait(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel and cancel.is_set():
                        p.terminate()
                        raise Cancelled('Тоқтатылды')
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        if code:
            err.seek(0)
            raise RuntimeError(err.read().decode('utf-8', 'replace')[-3000:])

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

def confirmed_goal_candidates(events):
    # A later return to an earlier score retracts the intervening scoreboard state.
    # This handles explicit VAR score reversals, not every possible VAR decision.
    history=[]
    for ev in events:
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
        if sum(x['end']-x['start'] for x in chosen) >= target-.2:
            break
        start, end = max(0, c['start']), min(duration, c['end'])
        # Keep non-overlapping footage. Do not silently repeat the same goal.
        if any(start < x['end']+1 and end > x['start']-1 for x in chosen):
            continue
        left = target-sum(x['end']-x['start'] for x in chosen)
        if left < 3:
            break
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


def analyze(video, target=180, roi=(0,0,.5,.17), use_ocr=True, log=print, cancel=None):
    """Use score changes and crowd/commentary energy; not semantic goal recognition."""
    info = metadata(video)
    duration = info['duration']
    readings, warnings = [], []
    if use_ocr:
        try:
            import cv2
            from rapidocr_onnxruntime import RapidOCR
            log('Экрандағы есепті оқу…')
            engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
            cap = cv2.VideoCapture(str(video))
            try:
                # Detailed sampling near the end helps avoid using an earlier score.
                step = max(4, duration/180)
                times = sorted(set(np.arange(0, duration, step).tolist()+
                                   np.arange(max(0,duration-45),duration,2).tolist()))
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
                for c in candidates:
                    if c.get('kind')=='goal':
                        a=max(0,int(c['start']+2));b=min(n,int(c['end']-2))
                        if b>a:c['goal_at']=min(c['end']-1,max(c['start'],a+int(np.argmax(energy[a:b]))-1.0))
    except Cancelled:
        raise
    except Exception as e:
        warnings.append('Дыбыс талданбады: '+str(e))
    # Reserve a final score card and 0.1s for container/audio rounding.
    limit=min(180.0,float(target))
    if not math.isfinite(limit) or limit<4:raise ValueError('Уақыт шегі: 4–180 секунд.')
    clips=choose_clips(candidates,duration,limit-3.1)
    if not clips:
        warnings.append('Сәттер автоматты табылмады. Уақыттарды қолмен енгізіңіз.')
    if not final:
        warnings.append('Соңғы есеп анық оқылмады. Есепті өзіңіз енгізіңіз немесе бос қалдырыңыз.')
    warnings.append('Бұл — видеода соңғы көрінген есеп. Видео матч аяқталмай тұрып үзілген болса, финалдық есеп болмауы мүмкін.')
    return dict(video=str(Path(video).resolve()),info=info,score=final,clips=clips,
                score_events=events,warnings=warnings,ocr_readings=readings)

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

def make_card(path, title, score, label, final_card=False):
    from PIL import Image, ImageDraw, ImageFont
    fonts=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arialbd.ttf',
           Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    fontpath=next((f for f in fonts if f.exists()),None)
    def font(size):
        return ImageFont.truetype(str(fontpath),size) if fontpath else ImageFont.load_default()
    im=Image.new('RGBA',(720,1280));d=ImageDraw.Draw(im)
    def text(s,y,size,color='white'):
        f=font(size)
        while d.textbbox((0,0),s,font=f)[2]>670 and size>14:
            size-=1;f=font(size)
        box=d.textbbox((0,0),s,font=f)
        d.text(((720-box[2])/2,y),s,font=f,fill=color)
    d.rounded_rectangle((275,276,445,282),3,fill='#66eed2')
    text(title or 'FOOTBALL HIGHLIGHTS',310,36)
    if final_card:
        text('FINAL SCORE' if score!='?' else 'ЕСЕП АНЫҚТАЛМАДЫ',388,21,'#66eed2')
        text(score,458,140)
        text(title,705,30)
    else:
        text(label,891,24,'#66eed2')
    im.save(path)

def make_goal_image(path):
    from PIL import Image,ImageDraw,ImageFont
    fonts=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arialbd.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    font_path=next((x for x in fonts if x.exists()),None)
    f=ImageFont.truetype(str(font_path),100) if font_path else ImageFont.load_default()
    im=Image.new('RGBA',(600,160));d=ImageDraw.Draw(im)
    d.rounded_rectangle((8,8,592,150),28,fill=(7,24,31,255),outline='#66eed2',width=5)
    b=d.textbbox((0,0),'ГООЛ!',font=f)
    d.text(((600-(b[2]-b[0]))/2,3),'ГООЛ!',font=f,fill='#66eed2',stroke_width=2,stroke_fill='white')
    im.save(path)


def render(video,music,clips,output,title='',score='',music_level=.18,source_level=.20,
           crop_top=.15,show_final=True,log=print,cancel=None,replays=True,replay_speed=.5,max_seconds=180,goal_animation=True):
    info=metadata(video)
    validate_clips(clips,info['duration'])
    timeline=plan_timeline(clips,max_seconds,bool(score and show_final),replays,replay_speed)
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
        # Normalize source audio; original broadcasts differ greatly in loudness.
        silent=False
        try:
            run([ffmpeg(),'-v','error','-i',video,'-t','0.1','-map','0:a:0','-f','null','-'],cancel)
        except RuntimeError:
            silent=True
        crop_y=int(info['height']*crop_top)//2*2
        crop_h=(info['height']-crop_y)//2*2
        crop_w=info['width']//2*2
        for i,c in enumerate(clips):
            log(f'Монтаж: {i+1}/{len(clips)}')
            part=tmp/f'{i:03}.mp4';card=tmp/f'{i:03}.png'
            is_replay=c.get('is_replay',False)
            speed=float(c.get('speed',1));out_duration=segment_duration(c)
            make_card(card,title,'',f'ҚАЙТАЛАУ • {speed:g}×' if is_replay else 'ҮЗДІК СӘТТЕР')
            vf=f'[0:v]crop={crop_w}:{crop_h}:0:{crop_y},setpts=(PTS-STARTPTS)/{speed},fps=30,split=2[b][f];[b]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,boxblur=10:2,scale=720:1280,eq=brightness=-.22[bg];[f]scale=720:400:force_original_aspect_ratio=decrease,pad=720:400:(ow-iw)/2:(oh-ih)/2:black[fg];[bg][fg]overlay=0:440[v0];[v0][1:v]overlay=0:0,setsar=1,format=yuv420p[carded]'
            vf+=';[carded]null[v]'
            args=[ffmpeg(),'-v','error','-ss',c['start'],'-t',c['end']-c['start'],'-i',video,'-i',card]
            has_goal=goal_animation and c.get('kind')=='goal' and not is_replay
            audio_index=2
            if has_goal:
                goal_png=tmp/f'goal{i}.png';make_goal_image(goal_png)
                args+=['-loop','1','-i',goal_png];audio_index=3
                g=max(0,(c['goal_at']-c['start'])/speed)
                vf=vf.rsplit(';[carded]null[v]',1)[0]
                vf+=f";[2:v]format=rgba,fade=t=in:st={g}:d=0.12:alpha=1,fade=t=out:st={g+1.8}:d=0.35:alpha=1[goal];[carded][goal]overlay=x=60:y='860+60*exp(-8*(t-{g}))*cos(18*(t-{g}))':enable='between(t,{g},{g+2.2})':shortest=1[v]"
            if silent:
                args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                af=f'[{audio_index}:a]anull[a]'
            else:
                af=f'[0:a]asetpts=PTS-STARTPTS,aresample=48000,atempo={speed},loudnorm=I=-18:TP=-2:LRA=11,volume={source_level}[a]'
            args+=['-filter_complex_threads','2','-filter_complex',vf+';'+af,'-map','[v]','-map','[a]',
                   '-t',out_duration,'-c:v','libx264','-preset','fast','-crf','21','-threads','2',
                   '-c:a','aac','-ar','48000','-ac','2','-y',part]
            run(args,cancel)
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
        if score and show_final:
            log('Соңғы есеп кадры…')
            card=tmp/'final.png';part=tmp/'final.mp4'
            make_card(card,title,score,'',True)
            run([ffmpeg(),'-v','error','-f','lavfi','-i','color=c=0x081a20:s=720x1280:r=30:d=3',
                 '-i',card,'-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-filter_complex',
                 '[0:v][1:v]overlay=0:0,setsar=1,format=yuv420p[v]','-map','[v]','-map','2:a',
                 '-t','3','-c:v','libx264','-preset','fast','-crf','21','-threads','2',
                 '-c:a','aac','-ar','48000','-ac','2','-y',part],cancel)
            metadata(part)
            parts.append(part);total+=3
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
        run(args,cancel)
        result_info=metadata(mixed)
        if abs(result_info['duration']-total)>.6:
            raise RuntimeError('Экспорт толық аяқталмады. Файл сақталмады, қайталап көріңіз.')
        run([ffmpeg(),'-v','error','-i',mixed,'-f','null','-'],cancel)
        # Complete the file first; cancelled / failed exports cannot replace a good output.
        os.replace(mixed,output)
    return str(output)
