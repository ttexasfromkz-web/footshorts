"""Build an offline Windows installer containing Python, Tk and all dependencies."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import branding
from scripts.build_release import FILES
import runtime_manager


def prepare(root=ROOT,dest=None):
    if os.name!='nt':raise RuntimeError('Windows installer must be built on Windows.')
    root=Path(root);dest=Path(dest or root/'dist/installer/FootballShorts')
    if dest.exists():shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in FILES:shutil.copy2(root/name,dest/name)
    shutil.copytree(root/'music',dest/'music',dirs_exist_ok=True)
    branding.write_assets(dest)
    base=Path(sys.base_prefix)
    if not (base/'python.exe').is_file() or not (base/'Lib/os.py').is_file():
        raise RuntimeError('Build requires a full base Python installation, not an embeddable package.')
    # Copy the full tested base install, never a venv with an absolute pyvenv.cfg.
    shutil.copytree(base,dest/'.runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc','test','tests'))
    (dest/'.runtime/pyvenv.cfg').unlink(missing_ok=True)
    # Detect any wheel/DLL/Tk issue before producing the installer.
    missing=runtime_manager.probe(dest/'.runtime/python.exe')
    if missing:raise RuntimeError('Bundled runtime is incomplete: '+str(missing))
    return dest


def build(root=ROOT):
    root=Path(root);prepare(root)
    compiler=shutil.which('ISCC') or str(Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Inno Setup 6/ISCC.exe')
    if not Path(compiler).is_file():raise RuntimeError('Inno Setup compiler is missing.')
    version=json.loads((root/'version.json').read_text(encoding='utf-8'))['version']
    subprocess.run([compiler,'/DAppVersion='+version,str(root/'installer/FootballShorts.iss')],check=True,cwd=root)
    output=root/'dist/FootballShorts-Setup.exe'
    if not output.is_file():raise RuntimeError('Installer EXE was not created.')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    print(prepare() if args.prepare_only else build())
