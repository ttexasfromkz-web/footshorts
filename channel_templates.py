"""Portable named channel presets; media is copied, authentication is excluded."""
import copy
import json
from pathlib import Path
import re
import shutil
import uuid
from PIL import Image,ImageFont
import updater

SETTING_KEYS={'target','roi','use_ocr','music_level','source_level','crop_top','replays','replay_speed','action_camera','intro','show_final','quality'}
STYLE_DEFAULTS=dict(brand_name='',brand_logo='',font_file='',font_name='Стандарт',accent_color='#dcb56b',text_color='#102336',panel_color='#fafafa',background_color='#081a20')


def style(value=None):
    result={**STYLE_DEFAULTS,**{k:v for k,v in (value or {}).items() if k in STYLE_DEFAULTS}}
    for key in ('accent_color','text_color','panel_color','background_color'):
        if not isinstance(result[key],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',result[key]):raise ValueError('Түс пішімі: #12ABCD.')
    result['brand_name']=str(result['brand_name']).strip()[:70]
    result['font_name']=str(result['font_name']).strip()[:80]
    for key in ('brand_logo','font_file'):result[key]=str(result[key] or '')
    return result


class TemplateStore:
    def __init__(self,base):
        self.root=Path(base).resolve()/'channel_templates';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'templates.json'

    def records(self):
        if not self.path.is_file():return []
        data=json.loads(self.path.read_text(encoding='utf-8'))
        return data.get('templates',[])

    def names(self):return [r['name'] for r in self.records()]

    def asset(self,relative):
        p=(self.root/relative).resolve()
        if not p.is_relative_to(self.root):raise ValueError('Шаблон файлының жолы қате.')
        if not p.is_file():raise FileNotFoundError('Шаблон файлы табылмады: '+str(p))
        return str(p)

    def get(self,name):
        found=next((r for r in self.records() if r['name']==name),None)
        if not found:raise ValueError('Шаблон табылмады.')
        result=copy.deepcopy(found);s=result['settings']['channel_style']
        for key in ('brand_logo','font_file'):
            if s.get(key):s[key]=self.asset(s[key])
        if result.get('music_file'):result['music_file']=self.asset(result['music_file'])
        return result

    def save(self,name,settings,music=''):
        name=str(name).strip()
        if not name or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('Шаблон атауы: 1–80 таңба.')
        saved={k:copy.deepcopy(v) for k,v in settings.items() if k in SETTING_KEYS}
        s=style(settings.get('channel_style'));ident=uuid.uuid4().hex;folder=self.root/ident;folder.mkdir()
        try:
            if s['brand_logo']:
                with Image.open(s['brand_logo']) as im:
                    im=im.convert('RGBA');im.thumbnail((1024,1024));im.save(folder/'logo.png')
                s['brand_logo']=ident+'/logo.png'
            if s['font_file']:
                ImageFont.truetype(s['font_file'],20)
                ext=Path(s['font_file']).suffix.lower()
                if ext not in ('.ttf','.otf'):raise ValueError('Қаріп: TTF немесе OTF.')
                shutil.copy2(s['font_file'],folder/('font'+ext));s['font_file']=ident+'/font'+ext
            music_file=''
            if music:
                source=Path(music)
                if not source.is_file():raise FileNotFoundError('Музыка табылмады.')
                filename='music'+source.suffix.lower();shutil.copy2(source,folder/filename);music_file=ident+'/'+filename
            saved['channel_style']=s
            record=dict(id=ident,name=name,settings=saved,music_file=music_file)
            records=[r for r in self.records() if r['name'].casefold()!=name.casefold()]
            records.append(record);updater.atomic_json(self.path,{'schema':1,'templates':records})
        except BaseException:
            shutil.rmtree(folder);raise
        return self.get(name)

    def delete(self,name):
        # Only remove the index entry; projects and copied template media remain usable.
        records=[r for r in self.records() if r['name']!=name]
        updater.atomic_json(self.path,{'schema':1,'templates':records})
