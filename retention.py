"""Opt-in cleanup of completed app projects inside the real output directory."""
import json
import os
from pathlib import Path
import shutil
import stat
import time
import updater

CHOICES={'Өшірмеу':0,'7 күн':7,'14 күн':14,'30 күн':30,'60 күн':60,'90 күн':90}
ALLOWED=set(CHOICES.values())


def load_days(base):
    try:
        value=json.loads((Path(base)/'preferences.json').read_text(encoding='utf-8')).get('retention_days',0)
        return value if type(value) is int and value in ALLOWED else 0
    except (OSError,ValueError,AttributeError):return 0


def save_days(base,days):
    if type(days) is not int or days not in ALLOWED:raise ValueError('Сақтау мерзімі қате.')
    updater.atomic_json(Path(base)/'preferences.json',{'retention_days':days})


def linked(path):
    info=path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)


def cleanup(base,days,protected=(),now=None):
    """Skip unfinished, recent, active, unrecognized and linked trees."""
    if type(days) is not int or days not in ALLOWED:raise ValueError('Сақтау мерзімі қате.')
    if days==0:return [],[]
    base=Path(base).resolve();root=base/'output'
    if not root.is_dir() or linked(root):return [],[]
    protected={Path(p).resolve() for p in protected if p}
    cutoff=(time.time() if now is None else now)-days*86400
    removed=[];errors=[]
    for folder in root.iterdir():
        try:
            if linked(folder) or not folder.is_dir() or folder.resolve() in protected:continue
            manifest=folder/'source/project.json'
            # Check all paths before reading the manifest or deleting anything.
            latest=folder.stat().st_mtime;unsafe=False
            for current,dirs,files in os.walk(folder,followlinks=False):
                for name in dirs+files:
                    item=Path(current)/name
                    if linked(item):unsafe=True;break
                    latest=max(latest,item.stat().st_mtime)
                if unsafe:break
            if unsafe or latest>=cutoff or not manifest.is_file():continue
            p=json.loads(manifest.read_text(encoding='utf-8'))
            if p.get('kind')!='football_project' or p.get('status') not in {'ready','edited','error','cancelled'}:continue
            # Only a direct output child can be removed.
            if folder.parent!=root or folder.resolve().parent!=root.resolve():continue
            shutil.rmtree(folder);removed.append(folder.name)
        except (OSError,ValueError,AttributeError) as e:errors.append(folder.name+': '+str(e))
    return removed,errors
