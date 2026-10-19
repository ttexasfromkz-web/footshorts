"""Shared output geometry and duration policy; None means no montage limit."""
import math

FORMATS={'Шортс — 9:16':'shorts','Кәдімгі видео — 16:9':'landscape'}
LONG_LIMITS={'3 минут':180,'5 минут':300,'10 минут':600,'Шектеусіз':None}


def normalize(value='shorts'):
    value=FORMATS.get(value,value)
    if value not in FORMATS.values():raise ValueError('Видео форматын таңдаңыз: 9:16 немесе 16:9.')
    return value


def label(value='shorts'):
    code=normalize(value)
    return next(name for name,key in FORMATS.items() if key==code)


def dimensions(output_format='shorts'):
    return (1280,720) if normalize(output_format)=='landscape' else (720,1280)


def limit_seconds(value=180,output_format='shorts'):
    wide=normalize(output_format)=='landscape'
    if value is None:
        if wide:return math.inf
        raise ValueError('Шортс ұзақтығы: 4–180 секунд.')
    value=float(value)
    if not math.isfinite(value) or value<4 or (not wide and value>180):
        raise ValueError('Ұзақтық кемінде 4 секунд; шортс үшін ең көбі 180 секунд.')
    return value


def analysis_target(settings):
    target=settings.get('target',300 if settings.get('output_format')=='landscape' else 180)
    limit_seconds(target,settings.get('output_format','shorts'))
    return None if target is None else max(4,float(target)-(3 if settings.get('intro',True) else 0))


def show_format_dialog(owner):
    import tkinter as tk
    from tkinter import ttk
    dialog=tk.Toplevel(owner);dialog.title('Видео форматын таңдаңыз')
    dialog.transient(owner);dialog.resizable(False,False)
    frame=ttk.Frame(dialog,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Қандай видео жасаймыз?',font=('Segoe UI',15,'bold')).pack(pady=(0,16))
    def choose(code):
        owner.set_output_format(code,user_change=True);dialog.destroy()
    dialog.shorts_button=ttk.Button(frame,text='Шортс жасау — 9:16',command=lambda:choose('shorts'))
    dialog.shorts_button.pack(fill='x',ipady=10,pady=4)
    dialog.landscape_button=ttk.Button(frame,text='Кәдімгі видео жасау — 16:9',command=lambda:choose('landscape'))
    dialog.landscape_button.pack(fill='x',ipady=10,pady=4)
    ttk.Label(frame,text='Форматты негізгі терезеде де ауыстыруға болады.').pack(pady=(12,0))
    dialog.update_idletasks()
    x=owner.winfo_rootx()+max(0,(owner.winfo_width()-dialog.winfo_reqwidth())//2)
    y=owner.winfo_rooty()+max(0,(owner.winfo_height()-dialog.winfo_reqheight())//2)
    dialog.geometry(f'+{x}+{y}');dialog.grab_set();dialog.focus_set()
    return dialog
