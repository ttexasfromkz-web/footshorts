"""White broadcast cards and procedural animated fire; no external assets."""
from pathlib import Path
import math
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from publishing import parse_match_title


def font(size, italic=False,path=None):
    if path:return ImageFont.truetype(str(path),size)
    names=['arialbi.ttf','arialbd.ttf'] if italic else ['arialbd.ttf']
    paths=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/n for n in names]
    paths+=[Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-BoldOblique.ttf' if italic else 'DejaVuSans-Bold.ttf')]
    paths+=[Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    path=next((p for p in paths if p.exists()),None)
    return ImageFont.truetype(str(path),size) if path else ImageFont.load_default()


def centered(draw,text,box,size,fill,font_path=None):
    x,y,w,h=box
    while size>12 and draw.textbbox((0,0),text,font=font(size,path=font_path))[2]>w:size-=1
    f=font(size,path=font_path)
    while draw.textbbox((0,0),text,font=f)[2]>w and len(text)>2:text=text[:-2]+'…'
    b=draw.textbbox((0,0),text,font=f)
    draw.text((x+(w-(b[2]-b[0]))/2-b[0],y+(h-(b[3]-b[1]))/2-b[1]),text,font=f,fill=fill)


def brand_mark(im,style):
    x=38
    if style.get('brand_logo'):
        with Image.open(style['brand_logo']) as logo:
            logo=logo.convert('RGBA');logo.thumbnail((60,60));im.alpha_composite(logo,(38,1180))
        x=112
    if style.get('brand_name'):
        d=ImageDraw.Draw(im)
        centered(d,style['brand_name'],(x,1180,680-x,60),24,style['accent_color'],font_path=style.get('font_file') or None)


def card(path,title,score='',label='',final=False,style=None):
    from channel_templates import style as validate_style
    from functools import partial
    style=validate_style(style);put=partial(centered,font_path=style['font_file'] or None)
    im=Image.new('RGBA',(720,1280));d=ImageDraw.Draw(im)
    # Shadow, white face and a restrained gold rim.
    shadow=Image.new('RGBA',im.size);sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((23,65,697,153),24,fill=(0,0,0,150))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)));d=ImageDraw.Draw(im)
    d.rounded_rectangle((24,58,696,146),24,fill=style['panel_color'],outline=style['accent_color'],width=3)
    pair=parse_match_title(title)
    if pair:
        d.ellipse((39,88,61,110),fill='#d73031');d.ellipse((659,88,681,110),fill='#2474ce')
        put(d,pair['team_a'].upper(),(69,73,217,55),25,style['text_color'])
        put(d,pair['team_b'].upper(),(434,73,217,55),25,style['text_color'])
        d.rounded_rectangle((296,59,424,145),20,fill='#0d2032',outline=style['accent_color'],width=2)
        put(d,score if final else 'VS',(303,74,114,54),34,'white')
    else:
        put(d,title or 'FOOTBALL HIGHLIGHTS',(42,70,636,64),30,style['text_color'])
    if final:
        put(d,'СОҢҒЫ ЕСЕП' if score!='?' else 'ЕСЕП АНЫҚТАЛМАДЫ',(35,430,650,50),27,style['accent_color'])
        put(d,score,(35,510,650,175),140,'white')
        d.rounded_rectangle((270,739,450,744),2,fill=style['accent_color'])
    elif 'ҚАЙТАЛАУ' in label:
        d.rounded_rectangle((252,163,468,200),12,fill=(13,32,50,225),outline=style['accent_color'],width=1)
        put(d,label,(261,166,198,28),18,'#f5d795')
    brand_mark(im,style)
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


def intro_layers(folder,title,logos,style=None):
    from channel_templates import style as validate_style
    from functools import partial
    from PIL import ImageColor
    style=validate_style(style);put=partial(centered,font_path=style['font_file'] or None)
    bg_color=ImageColor.getrgb(style['background_color'])
    """A navy/gold VS stage and two separate cards for slide-in animation."""
    folder=Path(folder);folder.mkdir(exist_ok=True)
    bg=Image.new('RGBA',(720,1280));d=ImageDraw.Draw(bg)
    for y in range(1280):
        glow=max(0,1-abs(y-580)/650)
        d.line((0,y,720,y),fill=tuple(min(255,round(v+15*glow)) for v in bg_color)+(255,))
    for x in range(-800,1400,140):d.line((x,1280,x+600,0),fill=(211,175,101,15),width=1)
    put(d,'МАТЧТЫҢ ҮЗДІК СӘТТЕРІ',(45,239,630,55),27,'#ead29e')
    d.rounded_rectangle((280,318,440,322),2,fill=style['accent_color'])
    d.ellipse((319,513,401,595),fill=style['accent_color'])
    d.ellipse((322,516,398,592),fill='#0c2034')
    put(d,'VS',(328,526,64,52),31,'white')
    put(d,'FOOTBALL HIGHLIGHTS',(70,846,580,42),19,'#c9b78e')
    brand_mark(bg,style)
    base=folder/'intro-base.png';bg.save(base)
    pair=parse_match_title(title)
    names=[pair['team_a'],pair['team_b']] if pair else ['КОМАНДА 1','КОМАНДА 2']
    paths=[]
    for index,name in enumerate(names):
        layer=Image.new('RGBA',(720,1280));ld=ImageDraw.Draw(layer)
        x=30 if index==0 else 410
        ld.rounded_rectangle((x,381,x+280,760),24,fill=style['panel_color'],outline=style['accent_color'],width=3)
        ld.ellipse((x+38,412,x+242,616),fill='#edf0f3')
        logo=logos[index] if index<len(logos) else None
        loaded=False
        if logo:
            try:
                with Image.open(logo['path']) as badge:
                    badge=badge.convert('RGBA');badge.thumbnail((172,172))
                    layer.alpha_composite(badge,(x+140-badge.width//2,514-badge.height//2))
                    loaded=True
            except (OSError,ValueError):pass
        ld=ImageDraw.Draw(layer)
        if not loaded:
            # Deliberately generic shield, never presented as an official club crest.
            color='#b82d36' if index==0 else '#236cb4'
            ld.polygon([(x+78,451),(x+202,451),(x+194,544),(x+140,585),(x+86,544)],fill=color)
            initials=''.join(w[0] for w in name.split() if w)[:2].upper()
            put(ld,initials,(x+91,469,98,77),42,'white')
        # Two lines preserve legibility for long club names.
        words=name.upper().split();lines=[' '.join(words)]
        if len(lines[0])>18 and len(words)>1:
            cut=max(1,len(words)//2);lines=[' '.join(words[:cut]),' '.join(words[cut:])]
        for j,line in enumerate(lines):put(ld,line,(x+16,643+j*37,248,39),27,style['text_color'])
        ld.rounded_rectangle((x+92,727,x+188,731),2,fill=style['accent_color'])
        path=folder/('intro-'+str(index)+'.png');layer.save(path);paths.append(path)
    return base,*paths
