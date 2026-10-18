"""In-app video review: source-time trims, goal markers and camera keyframes."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
import cv2
import core
import workflow
from playback import PreviewPlayer
from review_model import ReviewModel,interpolate
from timeline import plan_timeline


def clock(t):
    t=max(0,float(t));return f'{int(t)//60:02}:{t%60:05.2f}'


def seconds(text):
    value=0.
    for part in text.strip().replace(',','.').split(':'):value=value*60+float(part)
    return value


class ReviewWindow(tk.Toplevel):
    def __init__(self,owner,project,on_saved,on_closed,audio=True):
        source=workflow.media_path(project,project['source_file'])
        info=core.metadata(source)
        super().__init__(owner)
        self.project=copy.deepcopy(project);self.on_saved=on_saved;self.on_closed=on_closed
        self.source=source
        self.model=ReviewModel(project.get('clips',[]),info['duration'])
        self.baseline=copy.deepcopy(self.model.clips)
        self.audio_enabled=audio;self.player=None;self.mode='source';self.index=0
        self.alive=True;self.after_id=None;self.scrub_id=None;self.scale_guard=False;self.image_box=None;self.clip_stop=None
        self.title('Матчты көру және өңдеу — '+project['title'])
        self.geometry('1200x800');self.minsize(960,680)
        self.transient(owner)
        self.protocol('WM_DELETE_WINDOW',self.request_close)
        main=ttk.Frame(self,padding=10);main.pack(fill='both',expand=True)
        main.columnconfigure(0,weight=1);main.rowconfigure(1,weight=1)
        toolbar=ttk.Frame(main);toolbar.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,6))
        for label,fn in [('Бастапқы видео',lambda:self.open_video('source')),
                         ('Дайын нәтиже',lambda:self.open_video('result')),
                         ('Ойнату / Пауза',self.toggle),
                         ('◀ 1 кадр',lambda:self.step(-1)),
                         ('1 кадр ▶',lambda:self.step(1))]:
            ttk.Button(toolbar,text=label,command=fn).pack(side='left',padx=2)
        self.mode_label=ttk.Label(toolbar,text='');self.mode_label.pack(side='right')
        self.canvas=tk.Canvas(main,bg='#0c1521',highlightthickness=0)
        self.canvas.grid(row=1,column=0,sticky='nsew')
        self.canvas.bind('<Button-1>',self.focus_click)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        side=ttk.Frame(main,padding=(10,0,0,0));side.grid(row=1,column=1,sticky='ns')
        ttk.Label(side,text='Үзінділер',font=('Segoe UI',11,'bold')).pack(anchor='w')
        self.listbox=tk.Listbox(side,width=32,height=6,exportselection=False)
        self.listbox.pack(fill='both',expand=True);self.listbox.bind('<<ListboxSelect>>',self.select_clip)
        ttk.Button(side,text='Таңдалған үзіндіні ойнату',command=self.play_clip).pack(fill='x',pady=(4,0))
        row=ttk.Frame(side);row.pack(fill='x',pady=5)
        ttk.Button(row,text='Үзіндіні өшіру',command=self.delete_clip).pack(side='left')
        ttk.Button(row,text='Кері қайтару',command=self.undo).pack(side='left',padx=4)
        self.start_text=tk.StringVar();self.end_text=tk.StringVar()
        row=ttk.Frame(side);row.pack(fill='x')
        ttk.Label(row,text='Басы').pack(side='left');ttk.Entry(row,textvariable=self.start_text,width=11).pack(side='left',padx=3)
        ttk.Label(row,text='Соңы').pack(side='left');ttk.Entry(row,textvariable=self.end_text,width=11).pack(side='left')
        ttk.Button(side,text='Шекараны қолдану',command=self.apply_trim).pack(fill='x',pady=3)
        row=ttk.Frame(side);row.pack(fill='x')
        ttk.Button(row,text='Басын осы жерге',command=lambda:self.boundary(True)).pack(side='left')
        ttk.Button(row,text='Соңын осы жерге',command=lambda:self.boundary(False)).pack(side='left',padx=3)
        row=ttk.Frame(side);row.pack(fill='x',pady=6)
        ttk.Button(row,text='Осы жерде ГОЛ',command=self.mark_goal).pack(side='left')
        ttk.Button(row,text='Гол емес',command=self.clear_goal).pack(side='left',padx=3)
        self.goal_label=ttk.Label(side,text='');self.goal_label.pack(anchor='w')
        ttk.Separator(side).pack(fill='x',pady=7)
        self.focus_mode=tk.BooleanVar(value=False)
        ttk.Checkbutton(side,text='Кадр бағыты: видеодан нүкте таңда',variable=self.focus_mode).pack(anchor='w')
        ttk.Label(side,text='Бір нүкте — бекітілген кадр.\nБірнеше нүкте — жұмсақ ауысу.',wraplength=290).pack(anchor='w')
        self.focus_list=tk.Listbox(side,height=3,width=32,exportselection=False);self.focus_list.pack(fill='x',pady=4)
        row=ttk.Frame(side);row.pack(fill='x')
        ttk.Button(row,text='Нүктені өшіру',command=self.remove_focus).pack(side='left')
        ttk.Button(row,text='Автоматты камера',command=self.reset_focus).pack(side='left',padx=3)
        row=ttk.Frame(side);row.pack(fill='x',pady=5)
        ttk.Label(row,text='Үлкейту ×').pack(side='left')
        self.zoom=tk.StringVar(value='1.0')
        ttk.Spinbox(row,from_=1,to=2,increment=.1,textvariable=self.zoom,width=5).pack(side='left',padx=4)
        ttk.Button(row,text='Қолдану',command=self.apply_zoom).pack(side='left')
        self.position_text=tk.StringVar()
        ttk.Label(main,textvariable=self.position_text).grid(row=2,column=0,sticky='w',pady=(5,0))
        self.scale=ttk.Scale(main,from_=0,to=1,command=self.scrub)
        self.scale.grid(row=3,column=0,sticky='ew')
        self.total_label=ttk.Label(main,text='',wraplength=850)
        self.total_label.grid(row=4,column=0,columnspan=2,sticky='w',pady=5)
        bottom=ttk.Frame(main);bottom.grid(row=5,column=0,columnspan=2,sticky='ew')
        ttk.Label(bottom,text='Өзгерістер қайта экспорттағаннан кейін видеоға түседі.').pack(side='left')
        ttk.Button(bottom,text='Сақтау',command=lambda:self.save(False)).pack(side='right',padx=3)
        ttk.Button(bottom,text='Сақтап, қайта жасау',command=lambda:self.save(True)).pack(side='right',padx=3)
        self.bind('<space>',self.space)
        self.update_idletasks();self.refresh_clips();self.open_video('source')
        self.grab_set()
        self.after_id=self.after(33,self.tick)

    def safe(self,fn):
        try:return fn()
        except Exception as e:messagebox.showerror('Өңдеу',str(e),parent=self)

    def current(self):
        if self.mode!='source':raise ValueError('Өңдеу үшін «Бастапқы видео» немесе үзіндіні таңдаңыз.')
        if not self.model.clips:raise ValueError('Үзінді жоқ. «Кері қайтару» басыңыз.')
        return self.model.clips[self.index]

    def open_video(self,mode):
        def run():
            path=self.source if mode=='source' else Path(workflow.output_files(self.project)['video'])
            if not path.is_file():raise ValueError('Дайын видео әлі жоқ.')
            candidate=PreviewPlayer(path,audio=self.audio_enabled)
            if self.player:self.player.close()
            self.player=candidate;self.mode=mode;self.clip_stop=None
            self.scale.configure(to=candidate.duration)
            self.mode_label.configure(text='Бастапқы видео' if mode=='source' else 'Соңғы экспорт')
            if mode=='source' and self.model.clips:candidate.seek(self.model.clips[self.index]['start'])
            self.draw()
        self.safe(run)

    def play_clip(self):
        def run():
            if self.mode!='source':self.open_video('source')
            c=self.current();self.player.pause();self.player.seek(c['start'])
            self.clip_stop=c['end'];self.player.play()
        self.safe(run)

    def toggle(self):
        if not self.player:return
        if self.player.playing:self.player.pause()
        else:self.player.play()

    def space(self,event):
        if isinstance(event.widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Spinbox)):return
        self.toggle();return 'break'

    def step(self,n):
        if self.player:self.player.pause();self.player.seek(self.player.position()+n/self.player.fps);self.draw()

    def scrub(self,value):
        if self.scale_guard or not self.player:return
        self.player.pause()
        if self.scrub_id:self.after_cancel(self.scrub_id)
        self.scrub_id=self.after(60,lambda:self.seek_scrub(float(value)))

    def seek_scrub(self,t):
        self.scrub_id=None
        if self.player:self.player.seek(t);self.draw()

    def tick(self):
        if not self.alive:return
        if self.player:
            if self.clip_stop is not None and self.player.playing and self.player.position()>=self.clip_stop:
                self.player.pause();self.player.seek(self.clip_stop-1/self.player.fps);self.clip_stop=None
            self.draw()
            self.scale_guard=True;self.scale.set(self.player.position());self.scale_guard=False
        self.after_id=self.after(33,self.tick)

    def draw(self):
        if not self.alive or not self.player:return
        frame=self.player.frame()
        t=self.player.position();audio=' • дыбыс қолжетімсіз' if self.player.audio_error else ''
        self.position_text.set(clock(t)+' / '+clock(self.player.duration)+audio)
        if frame is None:return
        im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        w=max(2,self.canvas.winfo_width());h=max(2,self.canvas.winfo_height())
        im.thumbnail((w,h));x=(w-im.width)//2;y=(h-im.height)//2
        self.image_box=(x,y,im.width,im.height)
        self.photo=ImageTk.PhotoImage(im,master=self)
        self.canvas.delete('all');self.canvas.create_image(x,y,anchor='nw',image=self.photo)
        if self.mode=='source' and self.model.clips:
            clip=self.model.clips[self.index];points=clip.get('focus_points',[])
            if points:
                import camera
                sw=self.player.info['width'];sh=self.player.info['height']
                top=float(self.project.get('settings',{}).get('crop_top',.15))
                rect=camera.manual_rectangle(clip,t,sw,sh,top)
                a,b,c,d=rect
                self.canvas.create_rectangle(x+a*im.width/sw,y+b*im.height/sh,
                    x+(a+c)*im.width/sw,y+(b+d)*im.height/sh,outline='#ffd274',width=3)

    def refresh_clips(self):
        self.index=max(0,min(self.index,len(self.model.clips)-1))
        self.listbox.delete(0,'end')
        for i,c in enumerate(self.model.clips):
            goal=' ⚽' if c.get('goal_at') is not None else ''
            self.listbox.insert('end',f"{i+1}. {clock(c['start'])}–{clock(c['end'])}{goal}")
        if self.model.clips:
            self.listbox.selection_set(self.index);c=self.model.clips[self.index]
            self.start_text.set(clock(c['start']));self.end_text.set(clock(c['end']))
            self.zoom.set(str(c.get('zoom',1)))
            self.goal_label.configure(text='Гол: '+clock(c['goal_at']) if c.get('goal_at') is not None else 'Гол белгіленбеген')
            self.focus_list.delete(0,'end')
            for p in c.get('focus_points',[]):self.focus_list.insert('end',clock(p['time'])+f"  x={p['x']:.2f}, y={p['y']:.2f}")
        try:
            settings={**workflow.DEFAULTS,**self.project.get('settings',{})}
            p=plan_timeline(self.model.clips,settings['target'],True,settings['replays'],settings['replay_speed'],
                            intro_seconds=3 if settings['intro'] else 0)
            text=f"Кіріспе, қайталау және есеппен бірге: {p['duration']:.1f} сек."
        except ValueError as e:text=str(e)
        self.total_label.configure(text=text)
        self.draw()

    def select_clip(self,event=None):
        chosen=self.listbox.curselection()
        if not chosen:return
        selected=int(chosen[0])
        if selected==self.index and self.mode=='source':return
        self.index=selected
        if self.mode!='source':self.open_video('source')
        if self.player:self.player.pause();self.player.seek(self.model.clips[self.index]['start'])
        self.refresh_clips()

    def edit(self,fn):
        def run():self.current();fn();self.refresh_clips()
        self.safe(run)

    def apply_trim(self):
        self.edit(lambda:self.model.trim(self.index,seconds(self.start_text.get()),seconds(self.end_text.get())))

    def boundary(self,start):
        def run():
            c=self.current();self.player.pause();t=self.player.position()
            self.model.trim(self.index,t if start else c['start'],c['end'] if start else t)
            self.refresh_clips()
        self.safe(run)

    def mark_goal(self):
        def run():
            self.player.pause();self.model.mark_goal(self.index,self.player.position())
        self.edit(run)

    def clear_goal(self):self.edit(lambda:self.model.clear_goal(self.index))

    def focus_click(self,event):
        if not self.focus_mode.get() or not self.image_box:return
        def run():
            self.current();self.player.pause()
            x,y,w,h=self.image_box
            if not x<=event.x<=x+w or not y<=event.y<=y+h:return
            self.model.focus(self.index,self.player.position(),(event.x-x)/w,(event.y-y)/h)
            self.refresh_clips()
        self.safe(run)

    def remove_focus(self):
        def run():
            selected=self.focus_list.curselection()
            if not selected:return
            i=int(selected[0])
            self.model.change(self.index,lambda c:c['focus_points'].pop(i))
        self.edit(run)

    def reset_focus(self):
        self.edit(lambda:self.model.change(self.index,lambda c:c.update(focus_points=[],zoom=1)))

    def apply_zoom(self):
        self.edit(lambda:self.model.change(self.index,lambda c:c.update(zoom=float(self.zoom.get()))))

    def delete_clip(self):self.edit(lambda:self.model.delete(self.index))

    def undo(self):
        self.model.undo();self.refresh_clips()

    def save(self,render):
        def run():
            clips=self.model.validate()
            settings={**workflow.DEFAULTS,**self.project.get('settings',{})}
            if any(c.get('focus_points') or c.get('zoom',1)>1 for c in clips):settings['action_camera']=True
            plan_timeline(clips,settings['target'],True,settings['replays'],settings['replay_speed'],
                          intro_seconds=3 if settings['intro'] else 0)
            self.project.update(clips=clips,settings=settings,status='edited')
            workflow.save_project(self.project)
            self.baseline=copy.deepcopy(clips)
            p=copy.deepcopy(self.project);self.shutdown();self.on_saved(p,render)
        self.safe(run)

    def request_close(self):
        if self.model.clips!=self.baseline:
            result=messagebox.askyesnocancel('Өзгерістер','Өзгерістерді сақтайсыз ба?',parent=self)
            if result is None:return
            if result:self.save(False);return
        self.shutdown()

    def shutdown(self):
        if not self.alive:return
        self.alive=False
        for token in (self.after_id,self.scrub_id):
            if token:
                try:self.after_cancel(token)
                except tk.TclError:pass
        if self.player:self.player.close();self.player=None
        self.grab_release();self.destroy();self.on_closed()
