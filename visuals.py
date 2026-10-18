"""White broadcast cards and procedural animated fire; no external assets."""
from pathlib import Path
import math
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from publishing import parse_match_title


def font(size, italic=False):
    names=['arialbi.ttf','arialbd.ttf'] if italic else ['arialbd.ttf']
    paths=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/n for n in names]
    paths+=[Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-BoldOblique.ttf' if italic else 'DejaVuSans-Bold.ttf')]
    paths+=[Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    path=next((p for p in paths if p.exists()),None)
    return ImageFont.truetype(str(path),size) if path else ImageFont.load_default()


def centered(draw,text,box,size,fill):
    x,y,w,h=box
    while size>12 and draw.textbbox((0,0),text,font=font(size))[2]>w:size-=1
    f=font(size)
    while draw.textbbox((0,0),text,font=f)[2]>w and len(text)>2:text=text[:-2]+'…'
    b=draw.textbbox((0,0),text,font=f)
    draw.text((x+(w-(b[2]-b[0]))/2-b[0],y+(h-(b[3]-b[1]))/2-b[1]),text,font=f,fill=fill)


def card(path,title,score='',label='',final=False):
    im=Image.new('RGBA',(720,1280));d=ImageDraw.Draw(im)
    # Shadow, white face and a restrained gold rim.
    shadow=Image.new('RGBA',im.size);sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((23,65,697,153),24,fill=(0,0,0,150))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)));d=ImageDraw.Draw(im)
    d.rounded_rectangle((24,58,696,146),24,fill='#fafafa',outline='#dcb56b',width=3)
    pair=parse_match_title(title)
    if pair:
        d.ellipse((39,88,61,110),fill='#d73031');d.ellipse((659,88,681,110),fill='#2474ce')
        centered(d,pair['team_a'].upper(),(69,73,217,55),25,'#102336')
        centered(d,pair['team_b'].upper(),(434,73,217,55),25,'#102336')
        d.rounded_rectangle((296,59,424,145),20,fill='#0d2032',outline='#dcb56b',width=2)
        centered(d,score if final else 'VS',(303,74,114,54),34,'white')
    else:
        centered(d,title or 'FOOTBALL HIGHLIGHTS',(42,70,636,64),30,'#102336')
    if final:
        centered(d,'СОҢҒЫ ЕСЕП' if score!='?' else 'ЕСЕП АНЫҚТАЛМАДЫ',(35,430,650,50),27,'#e0bd77')
        centered(d,score,(35,510,650,175),140,'white')
        d.rounded_rectangle((270,739,450,744),2,fill='#dcb56b')
    elif 'ҚАЙТАЛАУ' in label:
        d.rounded_rectangle((252,163,468,200),12,fill=(13,32,50,225),outline='#dcb56b',width=1)
        centered(d,label,(261,166,198,28),18,'#f5d795')
    im.save(path)


def goal_frame(t):
    """A short fire burst: coherent moving tongues, glow, sparks and gold type."""
    w,h=656,300
    fire=Image.new('RGBA',(w,h));d=ImageDraw.Draw(fire)
    rng=random.Random(97)
    envelope=min(1,t/.16)*max(0,min(1,(2.2-t)/.4))
    for i in range(58):
        x=rng.uniform(38,w-38);base=rng.uniform(196,235)
        length=rng.uniform(38,135)*(.75+.25*math.sin(t*14+i))*envelope
        sway=16*math.sin(t*10+i*1.7);width=rng.uniform(7,21)
        left=[];right=[]
        for j in range(17):
            q=j/16
            center=x+sway*q+8*math.sin(q*5+t*12+i)*math.sin(q*math.pi)
            radius=width*(1-q)**.8
            left.append((center-radius,base-length*q));right.append((center+radius,base-length*q))
        points=left+right[::-1]
        d.polygon(points,fill=(255,rng.randint(65,165),8,225))
        d.line([(x,base),(x+sway*.35,base-length*.45)],fill=(255,224,115,225),width=5)
    for i in range(42):
        x=rng.uniform(20,w-20)+20*math.sin(t*3+i)
        y=242-((t*105+rng.uniform(0,270))%265)
        d.ellipse((x,y,x+3,y+7),fill=(255,194,66,round(230*envelope)))
    im=Image.new('RGBA',(w,h));im.alpha_composite(fire.filter(ImageFilter.GaussianBlur(12)))
    im.alpha_composite(fire.filter(ImageFilter.GaussianBlur(1.6)))
    mask=Image.new('L',(w,h));md=ImageDraw.Draw(mask);f=font(130,True)
    text='ГООЛ!';b=md.textbbox((0,0),text,font=f)
    md.text(((w-(b[2]-b[0]))/2-b[0],128-b[1]),text,font=f,fill=255)
    outline=Image.new('RGBA',(w,h),'#dba14b');outline.putalpha(mask.filter(ImageFilter.MaxFilter(15)));im.alpha_composite(outline)
    outline=Image.new('RGBA',(w,h),'#171b23');outline.putalpha(mask.filter(ImageFilter.MaxFilter(9)));im.alpha_composite(outline)
    gold=Image.new('RGBA',(w,h));gd=ImageDraw.Draw(gold)
    for y in range(h):
        k=max(0,min(1,(y-128)/110))
        gd.line((0,y,w,y),fill=(255,round(254-88*k),round(230-196*k),255))
    gold.putalpha(mask);im.alpha_composite(gold)
    return im


def goal_sequence(folder,cancel=None):
    folder=Path(folder);folder.mkdir(exist_ok=True)
    for i in range(66):
        if cancel and cancel.is_set():
            from core import Cancelled
            raise Cancelled()
        goal_frame(i/30).save(folder/f'{i:03}.png')
    return folder/'%03d.png'
