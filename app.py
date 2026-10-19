"""Football Shorts — Windows desktop UI (also works with Tk on Linux/macOS)."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import core
import downloader
import publishing
import workflow
import updater
import retention
from progress import Progress
from timeline import plan_timeline

BASE=Path(__file__).resolve().parent

def timestamp(s):
    s=float(s);return f'{int(s)//60:02}:{s%60:05.2f}'

def seconds(s):
    parts=s.strip().replace(',','.').split(':')
    if len(parts)>3:raise ValueError('Уақыт форматы: 01:25.50')
    v=0.
    for p in parts:v=v*60+float(p)
    return v

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        import branding
        self.brand_icon=tk.PhotoImage(data=branding.PNG)
        self.iconphoto(True,self.brand_icon)
        self.title('Football Shorts '+updater.local_version(BASE)+' • YouTube → Шорт')
        width=min(1180,self.winfo_screenwidth()-40);height=min(800,self.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}');self.minsize(860,580)
        self.app_base=BASE;self.review_open=False;self.review_window=None;self.batch_window=None;self.batch_model=None
        self.clip_details={}
        self.jobs=queue.Queue();self.cancel_event=threading.Event();self.busy=False
        self.pending_update=None;self.update_checking=False;self.update_installing=False
        self.plan=None;self.source_url='';self.title_score='';self.source_video='';self.project_dir=None
        self.video=tk.StringVar();self.music=tk.StringVar(value=str(BASE/('music/Stadium_Ignition.mp3' if (BASE/'music/Stadium_Ignition.mp3').is_file() else 'music/Stadium_Ignition.wav')))
        self.title_text=tk.StringVar(value='')
        self.youtube=tk.StringVar();self.quality=tk.StringVar(value='1080')
        self.youtube_login=tk.StringVar(value='Аккаунтсыз');self.youtube_cookie_file=tk.StringVar()
        self.cookie_label=tk.StringVar(value='Cookies файлы таңдалмаған')
        self.intro=tk.BooleanVar(value=True)
        self.show_final=tk.BooleanVar(value=True)
        self.action_camera=tk.BooleanVar(value=False)
        self.replays=tk.BooleanVar(value=True);self.replay_speed=tk.StringVar(value='0.5')
        self.score=tk.StringVar();self.target=tk.StringVar(value='180')
        self.music_volume=tk.IntVar(value=18);self.source_volume=tk.IntVar(value=20)
        self.crop=tk.StringVar(value='15');self.roi=tk.StringVar(value='0, 0, 50, 17')
        self.use_ocr=tk.BooleanVar(value=True);self.score_verified=tk.BooleanVar(value=False)
        self.recent=tk.StringVar();self.project_paths=[]
        self.progress_model=Progress();self.progress_model.running=False
        self.progress_value=tk.DoubleVar(value=0);self.progress_text=tk.StringVar(value='Жүктеу → Талдау → Логотип іздеу → Монтаж → Сақтау')
        self.progress_detail=tk.StringVar();self.update_status=tk.StringVar(value='Жаңарту: тексеру күтілуде…')
        days=retention.load_days(BASE)
        self.retention_choice=tk.StringVar(value=next(k for k,v in retention.CHOICES.items() if v==days))
        self.status=tk.StringVar(value='Видеоны таңдаңыз → Талдау → Үзінділерді тексеру → MP4 сақтау')
        outer=ttk.Frame(self);outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        self.main_canvas=canvas
        frame=ttk.Frame(canvas,padding=10);window=canvas.create_window((0,0),window=frame,anchor='nw')
        frame.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            if isinstance(event.widget,(tk.Text,ttk.Combobox,ttk.Spinbox)):return
            delta=(-1 if event.num==4 else 1) if event.num in (4,5) else -int(event.delta/120)
            canvas.yview_scroll(delta,'units')
        self.bind_all('<MouseWheel>',wheel)
        self.bind_all('<Button-4>',wheel);self.bind_all('<Button-5>',wheel)
        brand=ttk.Frame(frame);brand.pack(fill='x')
        self.brand_small=self.brand_icon.subsample(4)
        ttk.Label(brand,image=self.brand_small).pack(side='left',padx=(0,8))
        ttk.Label(brand,text='FOOTBALL SHORTS',font=('Segoe UI',19,'bold')).pack(side='left')
        ttk.Label(frame,text='Компьютерде өңдеу • Соңғы есепті тексеру • 9:16 MP4',font=('Segoe UI',10)).pack(anchor='w',pady=(0,5))
        yt=ttk.LabelFrame(frame,text='Сілтемені қойыңыз → бір батырмамен дайын MP4 + TXT',padding=6);yt.pack(fill='x',pady=(0,5))
        ttk.Entry(yt,textvariable=self.youtube).pack(side='left',fill='x',expand=True)
        ttk.Combobox(yt,textvariable=self.quality,values=['720','1080'],width=5,state='readonly').pack(side='left',padx=5)
        self.download_btn=ttk.Button(yt,text='ШОРТС ЖАСАУ',command=self.download);self.download_btn.pack(side='left')
        auth=ttk.Frame(frame);auth.pack(fill='x',pady=(0,3))
        ttk.Button(auth,text='Видеолар кезегі…',command=self.open_batch).pack(side='right',padx=(6,0))
        ttk.Label(auth,text='YouTube кіруі:').pack(side='left')
        ttk.Combobox(auth,textvariable=self.youtube_login,values=['Аккаунтсыз','Chrome','Cookies файлы'],width=16,state='readonly').pack(side='left',padx=6)
        ttk.Button(auth,text='Cookies файлын таңдау…',command=self.pick_cookie_file).pack(side='left')
        ttk.Label(auth,textvariable=self.cookie_label,width=23).pack(side='left',padx=6)
        projects=ttk.Frame(frame);projects.pack(fill='x',pady=2)
        ttk.Label(projects,text='Жобалар:').pack(side='left')
        self.project_combo=ttk.Combobox(projects,textvariable=self.recent,state='readonly');self.project_combo.pack(side='left',fill='x',expand=True,padx=5)
        ttk.Button(projects,text='Жобаны ашу',command=self.load_plan).pack(side='left')
        ttk.Button(projects,text='Нәтижені көру',command=self.open_result).pack(side='left',padx=5)
        ttk.Button(projects,text='Жаңа жоба',command=self.new_project).pack(side='left')
        ttk.Button(projects,text='Жаңартуды тексеру',command=lambda:self.check_updates(True)).pack(side='left',padx=5)
        ttk.Label(frame,textvariable=self.update_status,foreground='#246090').pack(anchor='w')
        storage=ttk.Frame(frame);storage.pack(fill='x',pady=4)
        ttk.Label(storage,text='Жобаларды сақтау:').pack(side='left')
        storage_choice=ttk.Combobox(storage,textvariable=self.retention_choice,values=list(retention.CHOICES),state='readonly',width=14)
        storage_choice.pack(side='left',padx=6);storage_choice.bind('<<ComboboxSelected>>',self.change_retention)
        ttk.Label(storage,text='Мерзімі өткен жоба source, MP4 және TXT файлдарымен бірге өшіріледі.').pack(side='left')
        ttk.Progressbar(frame,variable=self.progress_value,maximum=100).pack(fill='x')
        ttk.Label(frame,textvariable=self.progress_text).pack(anchor='w')

        for label,var,kind in [('Футбол видеосы',self.video,'video'),('Фондық музыка',self.music,'music')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=2)
            ttk.Label(row,text=label,width=19).pack(side='left')
            ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='Таңдау…',command=lambda v=var,k=kind:self.pick(v,k)).pack(side='left',padx=(6,0))
        row=ttk.Frame(frame);row.pack(fill='x',pady=3)
        ttk.Label(row,text='Матч атауы',width=19).pack(side='left')
        ttk.Entry(row,textvariable=self.title_text,width=30).pack(side='left',fill='x',expand=True)
        ttk.Label(row,text='Ең ұзақ, сек:').pack(side='left',padx=(12,4))
        ttk.Combobox(row,textvariable=self.target,values=['60','90','120','180'],width=5,state='readonly').pack(side='left')
        self.option_columns=ttk.Frame(frame);self.option_columns.pack(fill='x',pady=3)
        self.analysis_panel=ttk.LabelFrame(self.option_columns,text='Талдау және дыбыс',padding=6)
        self.visual_panel=ttk.LabelFrame(self.option_columns,text='Көрініс және кіріспе',padding=6)
        opt=self.analysis_panel
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        ttk.Checkbutton(r,text='Есепті автоматты оқу (OCR)',variable=self.use_ocr).pack(side='left')
        ttk.Label(r,text='Аймақ %, x,y,w,h:').pack(side='left',padx=(8,4))
        ttk.Entry(r,textvariable=self.roi,width=16).pack(side='left')
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        ttk.Label(r,text='Музыка %').pack(side='left');ttk.Spinbox(r,from_=0,to=100,textvariable=self.music_volume,width=5).pack(side='left',padx=6)
        ttk.Label(r,text='Видео дыбысы %').pack(side='left');ttk.Spinbox(r,from_=0,to=100,textvariable=self.source_volume,width=5).pack(side='left',padx=6)
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        ttk.Checkbutton(r,text='Голды толық қайталау',variable=self.replays).pack(side='left')
        ttk.Combobox(r,textvariable=self.replay_speed,values=['0.5','0.75','1.0'],width=5,state='readonly').pack(side='left',padx=6)
        ttk.Label(r,text='× • ГООЛ! анимациясымен').pack(side='left')
        opt=self.visual_panel
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        self.no_zoom_btn=ttk.Radiobutton(r,text='Зумсыз — толық алаң',variable=self.action_camera,value=False)
        self.no_zoom_btn.pack(side='left')
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        self.zoom_btn=ttk.Radiobutton(r,text='Зуммен — ойынды қадағалау',variable=self.action_camera,value=True)
        self.zoom_btn.pack(side='left')
        ttk.Label(r,text='Жоғарыдан қию %').pack(side='left',padx=(8,4))
        ttk.Spinbox(r,from_=0,to=35,textvariable=self.crop,width=5).pack(side='left')
        ttk.Checkbutton(opt,text='3 секундтық кіріспе: логотиптер мен атаулар',variable=self.intro).pack(anchor='w',pady=2)
        self.show_final_btn=ttk.Checkbutton(opt,text='Видео соңында есепті көрсету',variable=self.show_final)
        self.show_final_btn.pack(anchor='w',pady=2)
        r=ttk.Frame(opt);r.pack(fill='x',pady=2)
        ttk.Button(r,text='1-команда логосы…',command=lambda:self.pick_logo(0)).pack(side='left')
        ttk.Button(r,text='2-команда логосы…',command=lambda:self.pick_logo(1)).pack(side='left',padx=6)
        controls=ttk.Frame(frame);controls.pack(fill='x',pady=4)
        ttk.Button(controls,text='Видеоны көру және өңдеу',command=self.review).pack(side='left',padx=(0,8))
        self.analyze_btn=ttk.Button(controls,text='Қайта талдау (қажет болса)',command=self.analyze);self.analyze_btn.pack(side='left')
        self.export_btn=ttk.Button(controls,text='Есепті түзетіп, қайта жасау',command=self.export);self.export_btn.pack(side='left',padx=8)
        ttk.Button(controls,text='Тоқтату',command=self.cancel_event.set).pack(side='left')
        self.output_columns=ttk.Frame(frame);self.output_columns.pack(fill='both',expand=True,pady=3)
        self.clips_panel=ttk.LabelFrame(self.output_columns,text='Үзінділер және соңғы есеп',padding=6)
        self.messages_panel=ttk.LabelFrame(self.output_columns,text='Жұмыс хабарламалары',padding=6)
        ttk.Label(self.clips_panel,text='01:10 - 01:25 | Гол | goal=01:18 (бастапқы уақыт)').pack(anchor='w')
        editor_area=ttk.Frame(self.clips_panel);editor_area.pack(fill='both',expand=True,pady=3)
        self.editor=tk.Text(editor_area,height=4,width=30,font=('Consolas',10),wrap='none')
        editor_scroll=ttk.Scrollbar(editor_area,orient='vertical',command=self.editor.yview)
        editor_scroll.pack(side='right',fill='y');self.editor.pack(side='left',fill='both',expand=True)
        self.editor.configure(yscrollcommand=editor_scroll.set)
        editor_xscroll=ttk.Scrollbar(self.clips_panel,orient='horizontal',command=self.editor.xview)
        editor_xscroll.pack(fill='x');self.editor.configure(xscrollcommand=editor_xscroll.set)
        r=ttk.Frame(self.clips_panel);r.pack(fill='x',pady=3)
        ttk.Button(r,text='Үзіндіні көру',command=self.preview).pack(side='left')
        ttk.Button(r,text='Жобаны сақтау (JSON)',command=self.save_plan).pack(side='left',padx=6)
        r=ttk.Frame(self.clips_panel);r.pack(fill='x',pady=2)
        ttk.Label(r,text='Соңғы есеп:').pack(side='left')
        self.score_entry=ttk.Entry(r,textvariable=self.score,width=9);self.score_entry.pack(side='left',padx=6)
        ttk.Label(r,text='Қате болса түзетіп, қайта жасаңыз.').pack(side='left')
        ttk.Label(self.messages_panel,textvariable=self.progress_detail,wraplength=440).pack(anchor='w')
        log_area=ttk.Frame(self.messages_panel);log_area.pack(fill='both',expand=True,pady=3)
        self.logs=tk.Text(log_area,height=4,width=30,font=('Segoe UI',9),state='disabled',wrap='word')
        log_scroll=ttk.Scrollbar(log_area,orient='vertical',command=self.logs.yview)
        log_scroll.pack(side='right',fill='y');self.logs.pack(side='left',fill='both',expand=True)
        self.logs.configure(yscrollcommand=log_scroll.set)
        ttk.Label(self.messages_panel,text='Голдарды, VAR шешімін және есепті тексеріңіз.',foreground='#a05b00').pack(anchor='w')
        self.status_label=ttk.Label(self.messages_panel,textvariable=self.status,wraplength=440)
        self.status_label.pack(anchor='w',pady=2)
        self._wide_layout=None
        frame.bind('<Configure>',lambda e:(canvas.configure(scrollregion=canvas.bbox('all')),self.arrange_columns(e.width)))
        self.arrange_columns(width-40)
        self.refresh_projects()
        self.after(100,self.poll)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(0,self.restore_state)
        self.after_idle(self.confirm_startup)
        self.after(200,self.check_updates)
        self.after(1500,self.cleanup_projects)
        self.after(500,self.refresh_progress)

    def confirm_startup(self):
        try:updater.mark_healthy(BASE)
        except Exception as e:self.log('Жаңартудың іске қосылуын растау қатесі: '+str(e))

    def arrange_columns(self,width):
        # Use actual requested widths so Windows display scaling cannot clip controls.
        minimum=max(self.analysis_panel.winfo_reqwidth(),self.visual_panel.winfo_reqwidth())
        wide=width>=max(1000,2*minimum+36)
        if wide!=self._wide_layout:
            self._wide_layout=wide
            for parent,left,right in [(self.option_columns,self.analysis_panel,self.visual_panel),
                                      (self.output_columns,self.clips_panel,self.messages_panel)]:
                parent.columnconfigure(0,weight=1,uniform='columns')
                parent.columnconfigure(1,weight=1 if wide else 0,uniform='columns' if wide else '')
                left.grid(row=0,column=0,sticky='nsew',padx=(0,5 if wide else 0),pady=(0,0 if wide else 4))
                right.grid(row=0 if wide else 1,column=1 if wide else 0,sticky='nsew',padx=(5 if wide else 0,0))
        self.status_label.configure(wraplength=max(250,int(width/2)-40 if wide else width-40))

    def refresh_progress(self):
        if self.progress_model.running:
            state=self.progress_model.snapshot()
            self.progress_value.set(state['percent']);self.progress_text.set(state['text']);self.progress_detail.set(state['detail'])
        self.after(500,self.refresh_progress)

    def change_retention(self,event=None):
        days=retention.CHOICES[self.retention_choice.get()]
        if days and not messagebox.askyesno('Ескі жобаларды автоматты өшіру',
            f'{days} күн қолданылмаған жобалар бастапқы видео, MP4 және TXT файлдарымен бірге өшіріледі.\nОсы мерзімді қосайын ба?',parent=self):
            old=retention.load_days(BASE)
            self.retention_choice.set(next(k for k,v in retention.CHOICES.items() if v==old));return
        try:retention.save_days(BASE,days)
        except Exception as e:messagebox.showerror('Сақтау мерзімі',str(e),parent=self);return
        self.log('Жобаларды сақтау: '+self.retention_choice.get())
        self.after(0,lambda:self.cleanup_projects(reschedule=False))

    def cleanup_projects(self,reschedule=True):
        # Never delete while an editor, worker or update is active.
        if not (self.busy or self.review_open or self.update_installing):
            try:
                removed,errors=retention.cleanup(BASE,retention.load_days(BASE),protected=[self.project_dir])
                for name in removed:self.log('Мерзімі өткен жоба өшірілді: '+name)
                for error in errors:self.log('Жоба тазаланбады: '+error)
                if removed:self.refresh_projects()
            except Exception as e:self.log('Жобаларды тазалау: '+str(e))
        if reschedule:self.after(3600000,self.cleanup_projects)

    def save_state(self):
        state=dict(project=self.project_dir,youtube=self.youtube.get(),video=self.video.get(),music=self.music.get(),
                   title=self.title_text.get(),score=self.score.get(),editor=self.editor.get('1.0','end'),settings=self.settings())
        updater.atomic_json(BASE/'ui_state.json',state)

    def restore_state(self):
        try:
            path=BASE/'ui_state.json'
            if not path.is_file():return
            state=json.loads(path.read_text(encoding='utf-8'));settings=state.get('settings',{})
            project=state.get('project')
            if project and Path(project).is_dir():self.project_ready(workflow.output_files(workflow.load_project(project)))
            for key,var in [('youtube',self.youtube),('video',self.video),('music',self.music),('title',self.title_text),('score',self.score)]:
                if key in state:var.set(state[key])
            if 'editor' in state:self.editor.delete('1.0','end');self.editor.insert('1.0',state['editor'])
            self.target.set(str(settings.get('target',180)));self.quality.set(str(settings.get('quality',1080)))
            self.youtube_cookie_file.set(settings.get('youtube_cookie_file',''))
            self.youtube_login.set('Chrome' if settings.get('youtube_browser')=='chrome' else 'Cookies файлы' if settings.get('youtube_cookie_file') else 'Аккаунтсыз')
            if self.youtube_cookie_file.get():self.cookie_label.set(Path(self.youtube_cookie_file.get()).name)
            self.music_volume.set(round(settings.get('music_level',.18)*100));self.source_volume.set(round(settings.get('source_level',.2)*100))
            self.crop.set(str(settings.get('crop_top',.15)*100));self.roi.set(', '.join(str(v*100) for v in settings.get('roi',[0,0,.5,.17])))
            self.intro.set(settings.get('intro',True))
            self.show_final.set(settings.get('show_final',True))
            self.action_camera.set(settings.get('action_camera',False))
            self.use_ocr.set(settings.get('use_ocr',True));self.replays.set(settings.get('replays',True));self.replay_speed.set(str(settings.get('replay_speed',.5)))
        except Exception as e:self.log('Баптауларды қалпына келтіру: '+str(e))

    def check_updates(self,force=False):
        if self.update_checking or self.pending_update or self.update_installing:return
        self.update_checking=True
        self.update_status.set('Жаңарту тексерілуде… Қазіргі нұсқа: '+updater.local_version(BASE))
        def worker():
            try:
                release=updater.find_update(BASE,force)
                self.jobs.put(('update_available',release) if release else ('update_none',force))
            except Exception as e:self.jobs.put(('update_error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def offer_update(self,release):
        version=release['tag_name'].removeprefix('v')
        if hasattr(self,'update_status'):self.update_status.set('Жаңа нұсқа бар: '+version)
        message=('Жаңа нұсқа шықты: '+version+'\nҚазіргі нұсқа: '+updater.local_version(BASE)+
                 '\n\nЖаңартайын ба?\n\n«Жоқ» таңдасаңыз, осы нұсқамен жұмысты жалғастырасыз.')
        if self.busy:message+='\nЖаңарту ағымдағы жұмыс аяқталған соң орнатылады.'
        if not messagebox.askyesno('Жаңа нұсқа шықты',message,parent=self):
            self.log('Жаңарту кейінге қалдырылды: '+version)
            return
        self.update_checking=True
        if hasattr(self,'update_status'):self.update_status.set('Жаңарту жүктелуде: '+version)
        self.log('Жаңарту мақұлданды: '+version+'. Жүктелуде…')
        def worker():
            try:self.jobs.put(('update_ready',updater.download_update(BASE,release,self.log)))
            except Exception as e:self.jobs.put(('update_error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def install_pending_update(self):
        if not self.pending_update or self.busy or self.update_installing or getattr(self,'review_open',False):return False
        self.update_installing=True
        try:
            self.save_state()
            updater.launch_helper(BASE,self.pending_update)
            self.destroy()
            return True
        except Exception as e:
            self.log('Жаңарту орнатылмады; бағдарлама жалғасады: '+str(e))
            self.pending_update=None;self.update_installing=False
            return False

    def pick_cookie_file(self):
        path=filedialog.askopenfilename(title='YouTube cookies.txt (тек осы компьютерде)',
            filetypes=[('Cookies мәтіні','*.txt'),('Барлық файлдар','*.*')])
        if not path:return
        try:downloader.authentication_args(cookie_file=path)
        except ValueError as e:messagebox.showerror('Cookies файлы',str(e),parent=self);return
        self.youtube_cookie_file.set(path);self.cookie_label.set(Path(path).name);self.youtube_login.set('Cookies файлы')

    def settings(self):
        roi=tuple(float(x.strip())/100 for x in self.roi.get().split(','))
        if len(roi)!=4 or any(v<0 for v in roi) or roi[2]<=0 or roi[3]<=0 or roi[0]+roi[2]>1 or roi[1]+roi[3]>1:
            raise ValueError('Есеп аймағы: 0, 0, 50, 17 сияқты пайызбен жазыңыз.')
        mv=float(self.music_volume.get())/100;sv=float(self.source_volume.get())/100;crop=float(self.crop.get())/100
        if not 0<=mv<=1 or not 0<=sv<=1 or not 0<=crop<=.35:raise ValueError('Дыбыс: 0–100%, қию: 0–35%.')
        cookie_file=self.youtube_cookie_file.get() if self.youtube_login.get()=='Cookies файлы' else ''
        if self.youtube_login.get()=='Cookies файлы' and not cookie_file:raise ValueError('Cookies файлын таңдаңыз.')
        return dict(youtube_browser='chrome' if self.youtube_login.get()=='Chrome' else '',youtube_cookie_file=cookie_file,
                    target=int(self.target.get()),quality=int(self.quality.get()),roi=roi,use_ocr=self.use_ocr.get(),
                    music_level=mv,source_level=sv,crop_top=crop,replays=self.replays.get(),replay_speed=float(self.replay_speed.get()),action_camera=self.action_camera.get(),intro=self.intro.get(),show_final=self.show_final.get())

    def refresh_projects(self):
        self.project_paths=workflow.recent_projects(BASE)
        self.project_combo['values']=[p.name for p in self.project_paths]

    def new_project(self):
        if self.busy:return
        self.clip_details={}
        self.action_camera.set(False)
        self.project_dir=None;self.plan=None;self.source_url='';self.source_video='';self.title_score=''
        self.youtube.set('');self.video.set('');self.title_text.set('');self.score.set('');self.recent.set('')
        self.editor.delete('1.0','end');self.status.set('Жаңа жоба. Сілтемені қойып, «ШОРТС ЖАСАУ» басыңыз. Бұрынғы жобалар сақталды.')
        self.refresh_projects()

    def open_result(self):
        self.review(result=True)

    def review(self,result=False):
        if self.busy or self.review_open:return
        try:
            if not self.project_dir:raise ValueError('Алдымен жоба жасаңыз немесе сақталған жобаны ашыңыз.')
            p=workflow.load_project(self.project_dir)
            p['clips']=self.parse();p['settings'].update(self.settings())
            p['title']=self.title_text.get().strip() or p['title']
            score=self.score.get().strip().replace('-',':')
            if score and not re.fullmatch(r'\d{1,2}:\d{1,2}',score):raise ValueError('Есепті 1:3 түрінде енгізіңіз.')
            p['score']=score or None
            from review_ui import ReviewWindow
            self.review_window=ReviewWindow(self,p,self.review_saved,self.review_closed)
            self.review_open=True
            if result:self.review_window.open_video('result')
        except Exception as e:messagebox.showerror('Қате',str(e))

    def review_closed(self):
        self.review_open=False;self.review_window=None

    def review_saved(self,project,render):
        try:
            settings={**workflow.DEFAULTS,**project.get('settings',{})}
            self.action_camera.set(settings['action_camera'])
            self.project_ready(workflow.output_files(project))
            if render:
                path=project['directory']
                self.start(lambda:workflow.render_project(workflow.load_project(path),self.log,self.cancel_event),self.project_ready)
        except Exception as e:messagebox.showerror('Қате',str(e))

    def open_batch(self):
        try:
            if self.batch_window and self.batch_window.winfo_exists():
                self.batch_window.deiconify();self.batch_window.lift();return
            from batch_queue import BatchQueue
            from batch_ui import BatchWindow
            if self.batch_model is None:self.batch_model=BatchQueue(BASE/'queue.json')
            self.batch_window=BatchWindow(self,self.batch_model)
        except Exception as e:messagebox.showerror('Кезек',str(e))

    def open_project_path(self,path):
        p=workflow.load_project(path);settings={**workflow.DEFAULTS,**p.get('settings',{})}
        self.target.set(str(settings['target']));self.crop.set(str(settings['crop_top']*100))
        self.music_volume.set(round(settings['music_level']*100));self.source_volume.set(round(settings['source_level']*100))
        self.roi.set(', '.join(str(x*100) for x in settings['roi']))
        self.show_final.set(settings['show_final']);self.intro.set(settings['intro']);self.action_camera.set(settings['action_camera'])
        self.replays.set(settings['replays']);self.replay_speed.set(str(settings['replay_speed']));self.use_ocr.set(settings['use_ocr'])
        self.project_ready(workflow.output_files(p))

    def download(self):
        if self.busy:return
        try:
            url=self.youtube.get().strip();video=self.video.get().strip();music=self.music.get().strip()
            if url:url=downloader.normalize_url(url)
            elif not Path(video).is_file():raise ValueError('YouTube сілтемесін қойыңыз немесе видео таңдаңыз.')
            settings=self.settings();title=self.title_text.get().strip()
            self.project_dir=None
            self.start(lambda:workflow.create_project(BASE,url,video,music,settings,title,self.log,self.cancel_event,
                on_source=lambda info:self.jobs.put(('project_source',info))),self.project_ready)
        except Exception as e:messagebox.showerror('Қате',str(e))

    def project_ready(self,result):
        p=result['project'];self.project_dir=p['directory'];self.source_url=p.get('source_url','')
        self.source_video=str(workflow.media_path(p,p['source_file']));self.video.set(self.source_video)
        self.title_text.set(p['title']);self.title_score=p.get('title_score') or ''
        self.youtube.set(self.source_url)
        self.analyzed(dict(score=p.get('score'),clips=p.get('clips',[]),warnings=p.get('warnings',[])))
        self.score.set(p.get('score') or '')
        self.refresh_projects();self.recent.set(Path(self.project_dir).name)
        self.status.set(('Дайын: ' if p.get('status')=='ready' else 'Жоба ашылды: ')+self.project_dir+(' • Есеп анықталмады — қолмен түзете аласыз.' if not p.get('score') else ' • Нәтижені көріңіз. Қате болса, есепті өзгертіп қайта жасаңыз.'))
        self.log('MP4: '+result['video']);self.log('TXT: '+result['text'])

    def pick_logo(self,index):
        if self.busy:return
        try:
            if not self.project_dir:raise ValueError('Алдымен жоба жасаңыз немесе бұрынғы жобаны ашыңыз.')
            teams=publishing.parse_match_title(self.title_text.get().strip())
            if not teams:raise ValueError('Матч атауын «A — B» түрінде енгізіңіз.')
            name=teams['team_a' if index==0 else 'team_b']
            path=filedialog.askopenfilename(title=name+' — логотип',filetypes=[('Logo','*.png *.jpg *.jpeg *.webp'),('All','*.*')])
            if path:
                import logos
                logos.install(name,path,Path(self.project_dir)/'source/logos')
                self.log(name+': логотип сақталды. Қайта жасау батырмасын басыңыз.')
        except Exception as e:messagebox.showerror('Қате',str(e))

    def pick(self,var,kind):
        path=filedialog.askopenfilename(filetypes=[('Media','*.mp4 *.mkv *.mov *.avi *.wav *.mp3 *.m4a'),('All','*.*')])
        if path:
            var.set(path)
            if kind=='video':
                self.clip_details={}
                self.plan=None;self.project_dir=None;self.score.set('');self.score_verified.set(False);self.source_url='';self.title_score='';self.source_video=''
                self.youtube.set('');self.recent.set('');self.editor.delete('1.0','end')
                self.title_text.set('')

    def refresh_progress_values(self):
        state=self.progress_model.snapshot()
        self.progress_value.set(state['percent']);self.progress_text.set(state['text']);self.progress_detail.set(state['detail'])

    def log(self,s):self.jobs.put(('log',str(s)))

    def start(self,fn,callback):
        if self.busy:return
        self.busy=True;self.cancel_event.clear()
        self.progress_model.reset();self.refresh_progress_values()
        self.analyze_btn.state(['disabled']);self.export_btn.state(['disabled']);self.download_btn.state(['disabled'])
        self.status.set('Жұмыс жүріп жатыр…')
        def worker():
            try:self.jobs.put(('done',(callback,fn())))
            except core.Cancelled:self.jobs.put(('cancel',None))
            except Exception as e:self.jobs.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,payload=self.jobs.get_nowait()
                if kind.startswith('update_'):
                    self.update_checking=False
                    if kind=='update_available':
                        self.offer_update(payload)
                    elif kind=='update_ready':
                        self.update_status.set('Жаңарту дайын. Орнату үшін жұмыстың аяқталуын күтуде…')
                        self.pending_update=payload
                        self.status.set('Жаңа нұсқа дайын. Жұмыс аяқталған соң жаңарып, бағдарлама қайта ашылады.')
                    elif kind=='update_error':
                        self.update_status.set('Жаңарту тексерілмеді — «Жаңартуды тексеру» басып қайталаңыз.')
                        self.log('Жаңартуды тексеру мүмкін болмады; ағымдағы нұсқа жұмыс істейді: '+payload)
                    else:
                        self.update_status.set('Соңғы жарияланған нұсқа орнатылған: '+updater.local_version(BASE))
                        self.log('Жаңартуды тексеру аяқталды; жаңа нұсқа жоқ.')
                        if payload:messagebox.showinfo('Жаңарту','Сізде соңғы нұсқа орнатылған: '+updater.local_version(BASE),parent=self)
                    continue
                if kind=='batch_progress':
                    if self.batch_window and self.batch_window.winfo_exists():self.batch_window.refresh(payload)
                    continue
                if kind=='project_source':
                    if self.project_dir!=payload['directory']:
                        self.clip_details={};self.plan=None;self.score.set('');self.editor.delete('1.0','end')
                    self.project_dir=payload['directory'];self.source_video=payload['video']
                    self.video.set(payload['video']);self.title_text.set(payload['title'])
                    self.refresh_projects();self.recent.set(Path(self.project_dir).name)
                    continue
                if kind=='log':
                    if self.busy and self.progress_model.observe(payload):continue
                    self.logs.configure(state='normal');self.logs.insert('end',payload+'\n');self.logs.see('end');self.logs.configure(state='disabled')
                else:
                    self.progress_model.finish(kind=='done');self.refresh_progress_values()
                    if kind!='done':self.progress_text.set('Тоқтатылды' if kind=='cancel' else 'Қате — журналды қараңыз')
                    self.busy=False;self.refresh_projects();self.analyze_btn.state(['!disabled']);self.export_btn.state(['!disabled']);self.download_btn.state(['!disabled'])
                    if kind=='done':
                        cb,result=payload;self.status.set('Дайын')
                        try:cb(result)
                        except Exception as e:messagebox.showerror('Қате',str(e))
                    elif kind=='error':self.status.set('Қате');messagebox.showerror('Қате',payload)
                    else:self.status.set('Тоқтатылды')
        except queue.Empty:pass
        if self.install_pending_update():return
        self.after(100,self.poll)

    def analyze(self):
        try:
            video=self.video.get();target=max(4,int(self.target.get())-(3 if self.intro.get() else 0))
            if str(Path(video).resolve())!=str(Path(self.source_video or '.').resolve()):
                self.source_url='';self.title_score=''
            if not Path(video).is_file():raise ValueError('Видеоны таңдаңыз.')
            roi=tuple(float(x.strip())/100 for x in self.roi.get().split(','))
            if len(roi)!=4 or any(v<0 for v in roi) or roi[2]<=0 or roi[3]<=0 or roi[0]+roi[2]>1 or roi[1]+roi[3]>1:
                raise ValueError('Есеп аймағы: 0, 0, 50, 17 сияқты пайызбен жазыңыз.')
            ocr=self.use_ocr.get()
            self.score_verified.set(False)
            self.start(lambda:core.analyze(video,target,roi,ocr,self.log,self.cancel_event),self.analyzed)
        except Exception as e:messagebox.showerror('Қате',str(e))

    def analyzed(self,p):
        self.clip_details={(round(c['start'],2),round(c['end'],2)):dict(c) for c in p['clips']}
        self.plan=p;self.score.set(p['score'] or self.title_score or '')
        self.editor.delete('1.0','end')
        self.editor.insert('1.0','\n'.join(f"{timestamp(c['start'])} - {timestamp(c['end'])} | {c['reason']}"+(f" | goal={timestamp(c['goal_at'])}" if c.get('goal_at') is not None else '') for c in p['clips']))
        for warning in p['warnings']:self.log(warning)
        try:
            timeline=plan_timeline(p['clips'],int(self.target.get()),self.show_final.get(),self.replays.get(),float(self.replay_speed.get()),intro_seconds=3 if self.intro.get() else 0)
            self.status.set(f"Жалпы ұзақтығы: {timeline['duration']:.1f} сек. goal= уақытын тексеріңіз.")
        except ValueError as e:self.status.set(str(e))

    def parse(self,text=None):
        clips=[]
        for line in (text if text is not None else self.editor.get('1.0','end')).splitlines():
            if not line.strip():continue
            timing,*reason=line.split('|',1)
            parts=re.split(r'\s*[-–]\s*',timing.strip())
            if len(parts)!=2:raise ValueError('Жол форматы: 01:10 - 01:22 | Гол')
            note=reason[0].strip() if reason else ''
            g=re.search(r'(?:^|\|)\s*goal=([\d:.]+)',note,re.I)
            c=dict(start=seconds(parts[0]),end=seconds(parts[1]),reason=note)
            details=self.clip_details.get((round(c['start'],2),round(c['end'],2)),{})
            merged=dict(details);merged.pop('goal_at',None);merged.pop('kind',None);merged.update(c);c=merged
            if g:c.update(kind='goal',goal_at=seconds(g.group(1)))
            clips.append(c)
        return clips

    def export(self):
        if self.busy:return
        try:
            if not self.project_dir:raise ValueError('Алдымен «ШОРТС ЖАСАУ» басыңыз немесе сақталған жобаны ашыңыз.')
            score=self.score.get().strip().replace('-',':')
            settings=self.settings()
            if (score or settings['show_final']) and not re.fullmatch(r'\d{1,2}:\d{1,2}',score):raise ValueError('Есепті 1:3 түрінде енгізіңіз.')
            clips=self.parse();title=self.title_text.get().strip();project=self.project_dir
            self.start(lambda:workflow.rerender(project,score,title,clips,settings,self.log,self.cancel_event),self.project_ready)
        except Exception as e:messagebox.showerror('Қате',str(e))

    def preview(self):
        if self.busy:return
        try:
            line=self.editor.get('insert linestart','insert lineend');clips=self.parse(line)
            core.validate_clips(clips,core.metadata(self.video.get())['duration'])
            c=clips[0];video=self.video.get()
            crop=float(self.crop.get())/100;replay=self.replays.get();speed=float(self.replay_speed.get());action_camera=self.action_camera.get()
            title=self.title_text.get()
            fd,p=tempfile.mkstemp(prefix='football-preview-',suffix='.mp4');os.close(fd)
            def job():
                core.render(video,None,[c],p,title=title,score='',show_final=False,crop_top=crop,
                            replays=replay,replay_speed=speed,action_camera=action_camera,intro=False,log=self.log,cancel=self.cancel_event)
                return p
            def opened(p):
                if os.name=='nt':os.startfile(p)
                elif sys.platform=='darwin':subprocess.Popen(['open',p])
                else:subprocess.Popen(['xdg-open',p])
            self.start(job,opened)
        except Exception as e:messagebox.showerror('Қате',str(e))

    def save_plan(self):
        if self.busy:return
        try:
            if not self.project_dir:raise ValueError('Алдымен жобаны жасаңыз.')
            p=workflow.load_project(self.project_dir);p['clips']=self.parse();p['title']=self.title_text.get().strip() or p['title']
            p['score']=self.score.get().strip() or None;p['settings'].update(self.settings());p['status']='edited'
            workflow.save_project(p);self.status.set('Жоба өз source/project.json файлына сақталды. Видео қайта жасау кезінде жаңарады.')
        except Exception as e:messagebox.showerror('Қате',str(e))

    def load_plan(self):
        if self.busy:return
        try:
            name=self.recent.get()
            path=next((p for p in self.project_paths if p.name==name),None)
            if not path:raise ValueError('Жобалар тізімінен біреуін таңдаңыз.')
            p=workflow.load_project(path);settings={**workflow.DEFAULTS,**p.get('settings',{})}
            self.target.set(str(settings['target']));self.crop.set(str(settings['crop_top']*100))
            self.music_volume.set(round(settings['music_level']*100));self.source_volume.set(round(settings['source_level']*100))
            self.roi.set(', '.join(str(x*100) for x in settings['roi']))
            self.show_final.set(settings['show_final']);self.intro.set(settings['intro'])
            self.action_camera.set(settings['action_camera'])
            self.replays.set(settings['replays']);self.replay_speed.set(str(settings['replay_speed']));self.use_ocr.set(settings['use_ocr'])
            self.project_ready(workflow.output_files(p))
        except Exception as e:messagebox.showerror('Қате',str(e))

    def close(self):
        if self.review_open:
            self.review_window.request_close()
            if self.review_open:return
        if self.busy:
            self.cancel_event.set();self.status.set('Тоқтатылуда… Терезені жұмыс тоқтаған соң жабыңыз.');return
        try:self.save_state()
        except Exception:pass
        self.destroy()

if __name__=='__main__':
    lock=BASE/'.updates/instance.lock'
    update_lock=BASE/'.updates/update.lock'
    blocked=False
    if update_lock.is_file() and os.environ.get('FOOTSHORTS_UPDATER_RESTART')!='1':
        try:blocked=updater.process_alive(json.loads(update_lock.read_text()).get('pid'))
        except Exception:pass
    if blocked or not updater.acquire_lock(lock):
        print('Бағдарлама ашық немесе жаңартылып жатыр. Бірнеше секундтан кейін көріңіз.')
    else:
        try:App().mainloop()
        finally:updater.release_lock(lock)
