"""Conservative Wikimedia logo lookup, with per-project caching and safe fallback."""
from pathlib import Path
import hashlib
import html
import io
import json
import re
import time
import unicodedata
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from PIL import Image
from publishing import parse_match_title

HOSTS={'www.wikidata.org','commons.wikimedia.org','upload.wikimedia.org'}
UA='FootballShorts/1.7 (https://github.com/ttexasfromkz-web/footshorts)'


def allowed(url):
    p=urlparse(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
        raise ValueError('Unexpected logo host')


class Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        allowed(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,deadline,limit=2_000_000):
    allowed(url);remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('Logo lookup timed out')
    with build_opener(Redirect()).open(Request(url,headers={'User-Agent':UA}),timeout=min(3,remaining)) as response:
        data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Logo response too large')
    return data


def api(host,params,deadline):
    return json.loads(fetch('https://'+host+'/w/api.php?'+urlencode(dict(format='json',**params)),deadline))


def normalized(name):
    name=unicodedata.normalize('NFKC',name).casefold()
    name=re.sub(r'\b(?:fc|fk|фк|фк\.|football club|футбольный клуб)\b',' ',name)
    return re.sub(r'[^\w]+','',name)


def find_entity(name,deadline):
    candidates={}
    for language in ('kk','ru','en'):
        data=api('www.wikidata.org',dict(action='wbsearchentities',search=name,language=language,
                                       uselang=language,type='item',limit=5),deadline)
        for item in data.get('search',[]):
            names=[item.get('label',''),item.get('match',{}).get('text',''),*item.get('aliases',[])]
            description=item.get('description','').casefold()
            if not any(word in description for word in ('football','soccer','футбол')):continue
            if not any(normalized(n)==normalized(name) for n in names):continue
            if re.fullmatch(r'Q\d+',item.get('id','')):candidates[item['id']]=item
        if candidates:break
    # An ambiguous name must never silently pick an arbitrary club.
    if len(candidates)!=1:return None
    return next(iter(candidates))


def strip_markup(value):
    return html.unescape(re.sub('<[^>]+>','',str(value)))[:1000]


def install(name,image,folder):
    """An explicitly chosen local crest overrides automatic lookup for this team."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(name.encode()).hexdigest()[:20]
    path=folder/(key+'.png')
    with Image.open(image) as im:
        if im.width*im.height>12_000_000:raise ValueError('Сурет тым үлкен.')
        im=im.convert('RGBA');im.thumbnail((320,320))
        tmp=folder/(key+'.tmp');im.save(tmp,format='PNG');tmp.replace(path)
    record=folder/(key+'.json')
    record.write_text(json.dumps(dict(name=name,manual=True),ensure_ascii=False),encoding='utf-8')
    return path


def resolve(name,folder,log=print,cancel=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(name.encode()).hexdigest()[:20]
    image_path=folder/(key+'.png');record=folder/(key+'.json')
    if image_path.is_file() and record.is_file():
        try:
            data=json.loads(record.read_text(encoding='utf-8'))
            if data.get('name')==name:
                with Image.open(image_path) as im:im.verify()
                return dict(data,path=str(image_path))
        except (OSError,ValueError):pass
    try:
        if cancel and cancel.is_set():return None
        deadline=time.monotonic()+9
        entity=find_entity(name,deadline)
        if not entity:return None
        data=api('www.wikidata.org',dict(action='wbgetentities',ids=entity,props='claims'),deadline)
        claims=data.get('entities',{}).get(entity,{}).get('claims',{}).get('P154',[])
        filenames={c.get('mainsnak',{}).get('datavalue',{}).get('value') for c in claims if c.get('rank')!='deprecated'}
        filenames.discard(None)
        if len(filenames)!=1:return None
        filename=next(iter(filenames))
        result=api('commons.wikimedia.org',dict(action='query',prop='imageinfo',
            titles='File:'+filename,iiprop='url|extmetadata',iiurlwidth=320),deadline)
        entries=[p['imageinfo'][0] for p in result.get('query',{}).get('pages',{}).values() if p.get('imageinfo')]
        if len(entries)!=1:return None
        info=entries[0];url=info.get('thumburl') or info['url']
        if cancel and cancel.is_set():return None
        raw=fetch(url,deadline,5_000_000)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>12_000_000:raise ValueError('Logo dimensions too large')
            im=im.convert('RGBA');im.thumbnail((320,320))
            tmp=folder/(key+'.tmp');im.save(tmp,format='PNG');tmp.replace(image_path)
        ext=info.get('extmetadata',{})
        data=dict(name=name,entity=entity,source=info.get('descriptionurl',''),
                  artist=strip_markup(ext.get('Artist',{}).get('value','')),
                  license=strip_markup(ext.get('LicenseShortName',{}).get('value','')))
        record.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        return dict(data,path=str(image_path))
    except Exception as e:
        log('Логотип алынбады: '+name+' ('+type(e).__name__+'). Бейтарап белгі қолданылады.')
        return None


def pair(title,folder,log=print,cancel=None):
    teams=parse_match_title(title)
    if not teams:return [None,None]
    result=[]
    for key in ('team_a','team_b'):
        name=teams[key];log('Логотип іздеу: '+name)
        logo=resolve(name,folder,log,cancel)
        if logo is None:log(name+': расталған логотип табылмады; бейтарап белгі.')
        result.append(logo)
    return result
