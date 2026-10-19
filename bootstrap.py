"""Launch only a checked local Python; show progress while fixing missing packages."""
from pathlib import Path
import json
import os
import queue
import subprocess
import sys
import threading
import updater
import runtime_manager


def checked_python(root):
    preferred=updater.runtime_python(root,sys.executable)
    if os.name!='nt' or sys.stdout is not None:
        return runtime_manager.ensure_runtime(root,preferred)
    import tkinter as tk
    from tkinter import ttk,messagebox
    window=tk.Tk();window.title('Football Shorts — іске қосу');window.geometry('520x130');window.resizable(False,False)
    status=tk.StringVar(value='Кітапханалар тексерілуде…')
    ttk.Label(window,textvariable=status,wraplength=480).pack(padx=16,pady=16)
    bar=ttk.Progressbar(window,mode='indeterminate');bar.pack(fill='x',padx=16);bar.start()
    messages=queue.Queue();answer={}
    def worker():
        try:messages.put(('done',runtime_manager.ensure_runtime(root,preferred,lambda s:messages.put(('log',s)))))
        except Exception as e:messages.put(('error',str(e)))
    def poll():
        try:
            while True:
                kind,value=messages.get_nowait()
                if kind=='log':status.set(value[-250:])
                else:
                    if kind=='done':answer['python']=value
                    else:answer['error']=value
                    window.destroy();return
        except queue.Empty:pass
        window.after(100,poll)
    # Closing this window must not leave a half-written active runtime pointer.
    window.protocol('WM_DELETE_WINDOW',lambda:status.set('Тексеру немесе жөндеу аяқталғанша күтіңіз…'))
    threading.Thread(target=worker,daemon=True).start();window.after(100,poll);window.mainloop()
    if 'error' in answer:
        messagebox.showerror('Football Shorts',answer['error']);raise RuntimeError(answer['error'])
    return answer['python']


def main():
    root=Path(__file__).resolve().parent
    for name in ('update.lock','instance.lock'):
        lock=root/'.updates'/name
        if lock.is_file():
            try:
                if updater.process_alive(json.loads(lock.read_text()).get('pid')):
                    if sys.stdout:print('Бағдарлама ашық немесе жаңарту орнатылып жатыр.')
                    return 0
            except (OSError,ValueError):pass
    try:python=checked_python(root)
    except Exception as e:
        if sys.stderr:print(str(e),file=sys.stderr)
        return 1
    return subprocess.call([python,str(root/'app.py')],cwd=root)


if __name__=='__main__':raise SystemExit(main())
