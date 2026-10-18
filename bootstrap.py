"""Small launcher that follows the active environment without deleting .venv."""
from pathlib import Path
import os
import json
import subprocess
import sys
import updater

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    lock=root/'.updates/update.lock'
    if lock.is_file():
        try:
            if updater.process_alive(json.loads(lock.read_text()).get('pid')):
                print('Жаңарту орнатылып жатыр. Бағдарлама өзі қайта ашылады.')
                raise SystemExit(0)
        except (OSError,ValueError):pass
    python=updater.runtime_python(root,sys.executable)
    raise SystemExit(subprocess.call([python,str(root/'app.py')],cwd=root))
