"""Build a bootstrap ZIP, a small update ZIP, and its SHA256 manifest."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import updater

FILES=['logos.py','visuals.py','camera.py','app.py','core.py','downloader.py','publishing.py','timeline.py','workflow.py','updater.py','update_helper.py',
       'bootstrap.py','version.json','requirements.txt','1_INSTALL.bat','2_START.bat','3_UPDATE_YOUTUBE.bat',
       'README_KZ.md','VALIDATION.md','README.md']


def build(root=ROOT,dest=None):
    root=Path(root);dest=Path(dest) if dest else root/'dist';dest.mkdir(parents=True,exist_ok=True)
    version=updater.local_version(root)
    missing=[f for f in FILES if not (root/f).is_file()]
    if missing:raise ValueError('Missing release files: '+str(missing))
    patch=dest/updater.ASSET
    with zipfile.ZipFile(patch,'w',zipfile.ZIP_DEFLATED) as z:
        for f in FILES:z.write(root/f,f)
    manifest=dict(version=version,repository=updater.REPOSITORY,asset_name=updater.ASSET,
                  sha256=updater.sha256(patch),files={f:updater.sha256(root/f) for f in FILES})
    updater.validate_archive(patch,manifest)
    (dest/'update.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    full=dest/'FootballShorts-Windows.zip'
    with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED) as z:
        for f in FILES:z.write(root/f,'FootballShorts/'+f)
        for p in sorted((root/'music').glob('*')):
            if p.is_file():z.write(p,'FootballShorts/music/'+p.name)
        z.writestr('FootballShorts/output/','')
    return manifest

if __name__=='__main__':print(json.dumps(build(),indent=2))
