"""A persistent multi-link queue window integrated with the app worker."""
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import workflow


LABELS={'queued':'Кезекте','running':'Өңделуде','done':'Дайын','error':'Қате','cancelled':'Тоқтатылды'}
STAGES={'download':'Жүктеу','analyze':'Талдау','logos':'Логотип','render':'Монтаж','save':'Сақтау',
        'new':'Дайындау','source':'Видео дайын','analysis':'Талдау дайын','ready':'Дайын'}


class BatchWindow(tk.Toplevel):
    def __init__(self,owner,model):
        super().__init__(owner);self.owner=owner;self.model=model
        self.title('Матчтарды кезекпен өңдеу');self.geometry('1000x620');self.minsize(800,480)
        self.protocol('WM_DELETE_WINDOW',self.withdraw)
        frame=ttk.Frame(self,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='YouTube сілтемелерін әр жолға жазыңыз немесе бірнеше видео файлын қосыңыз. Баптаулар барлығына ортақ.').pack(anchor='w')
        self.urls=tk.Text(frame,height=5,wrap='none');self.urls.pack(fill='x',pady=6)
        row=ttk.Frame(frame);row.pack(fill='x',pady=(0,6))
        manage=ttk.Frame(frame);manage.pack(fill='x',pady=(0,6))
        for text,fn in [('Кезекке қосу',self.add),('Видео файлдарын қосу…',self.add_files),('Кезекті бастау',self.run),
                        ('Тоқтату',owner.cancel_event.set),('Қателерді қайта кезекке қою',self.retry),
                        ('Дайындарын тазалау',self.clear)]:
            ttk.Button(manage if fn in (self.retry,self.clear) else row,text=text,command=fn).pack(side='left',padx=2)
        self.table=ttk.Treeview(frame,columns=('status','title','url','error'),show='headings')
        for key,label,width in [('status','Күйі',100),('title','Матч',180),('url','Сілтеме / видео файлы',270),('error','Мәлімет',320)]:
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=60)
        self.table.pack(fill='both',expand=True)
        self.table.bind('<Double-1>',lambda _:self.open_selected())
        ttk.Button(frame,text='Таңдалғанды кезектен өшіру',command=self.remove_selected).pack(anchor='e',pady=3)
        ttk.Button(frame,text='Таңдалған жобаны ашу',command=self.open_selected).pack(anchor='e',pady=6)
        self.status=ttk.Label(frame,text='');self.status.pack(anchor='w');self.refresh()
        ttk.Button(manage,text='Таңдалғанды басынан өңдеу',command=self.restart_selected).pack(side='left',padx=2)
        self.timer=None;self.bind('<Destroy>',self.stop_timer);self.tick_status()

    def refresh(self,items=None):
        if not self.winfo_exists():return
        items=items if items is not None else self.model.snapshot()
        selected=self.table.selection()
        self.table.delete(*self.table.get_children())
        for item in items:
            stage=item.get('stage',item.get('checkpoint',''));stage=STAGES.get(stage,stage)
            self.table.insert('', 'end',iid=item['id'],values=(LABELS.get(item['status'],item['status']),
                item.get('title',''),item['url'],item.get('error','') or
                (str(round(item.get('progress',0)))+'% • '+stage+' • '+item.get('directory',''))))
        if selected and self.table.exists(selected[0]):self.table.selection_set(selected[0])
        done=sum(i['status']=='done' for i in items);errors=sum(i['status']=='error' for i in items)
        self.update_summary()

    def update_summary(self):
        s=self.model.summary();eta=s['eta_seconds']
        remaining=('Шамамен қалғаны: '+f'{int(eta)//60:02}:{int(eta)%60:02}'+' (дайын видеолардың орташа уақытымен)') if eta is not None else 'Қалған уақыт: алғашқы видео бойынша есептелуде' if s['estimating'] else 'Өңделетін тапсырма жоқ'
        self.status.configure(text=f"Барлығы: {s['total']} • Дайын: {s['done']} • Қате: {s['errors']} • {remaining}")

    def tick_status(self):
        self.update_summary()
        if self.model.running:self.refresh()
        self.timer=self.after(1000,self.tick_status)

    def stop_timer(self,event):
        if event.widget==self and self.timer:
            self.after_cancel(self.timer);self.timer=None

    def restart_selected(self):
        try:self.model.restart(set(self.table.selection()));self.refresh()
        except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def add(self):
        try:self.model.add(self.urls.get('1.0','end'));self.urls.delete('1.0','end');self.refresh()
        except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def add_files(self):
        paths=filedialog.askopenfilenames(parent=self,title='Кезекке видео қосу',
            filetypes=[('Видео','*.mp4 *.mkv *.mov *.avi *.webm *.m4v'),('Барлық файлдар','*.*')])
        if paths:
            try:self.model.add_files(paths);self.refresh()
            except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def remove_selected(self):
        try:self.model.remove(set(self.table.selection()));self.refresh()
        except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def retry(self):self.model.retry_failed();self.refresh()
    def clear(self):self.model.clear_done();self.refresh()

    def run(self):
        if self.owner.busy or self.owner.review_open:
            messagebox.showinfo('Кезек','Ағымдағы жұмысты аяқтаңыз немесе редакторды жабыңыз.',parent=self);return
        try:
            settings=self.owner.settings();music=self.owner.music.get().strip()
            pending=[i for i in self.model.snapshot() if i['status']=='queued']
            if not pending:raise ValueError('Кезекте видео жоқ. Сілтеме немесе видео файлын қосыңыз.')
            base=self.owner.app_base
            def process(url):
                item=next(i for i in self.model.snapshot() if i['url']==url and i['status']=='running')
                def log(message):self.model.observe(url,message);self.owner.log(message)
                def checkpoint(info):self.model.checkpoint(url,info)
                saved=workflow.resolve_checkpoint(base,item)
                if saved:return workflow.resume_project(saved,log=log,cancel=self.owner.cancel_event,
                    on_source=lambda info:self.owner.jobs.put(('project_source',info)),on_checkpoint=checkpoint)
                if item.get('project_id'):raise FileNotFoundError('Сақталған жоба табылмады. «Басынан өңдеу» таңдаңыз.')
                local=item.get('source_type')=='file'
                return workflow.create_project(base,url='' if local else url,local_video=url if local else '',music=music,settings=settings,
                    log=log,cancel=self.owner.cancel_event,on_checkpoint=checkpoint,
                    on_source=lambda info:self.owner.jobs.put(('project_source',info)))
            def job():
                return self.model.run(process,self.owner.cancel_event,
                    lambda items:self.owner.jobs.put(('batch_progress',items)))
            self.owner.start(job,self.finished)
        except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def finished(self,results):
        self.refresh()
        if results:self.owner.project_ready(results[-1])
        items=self.model.snapshot()
        self.owner.status.set(('Кезек тоқтатылды. Дайын: ' if self.owner.cancel_event.is_set() else 'Кезек аяқталды. Дайын: ')+str(sum(i['status']=='done' for i in items))+
                              ' • Қате: '+str(sum(i['status']=='error' for i in items)))
        self.deiconify()

    def open_selected(self):
        if self.owner.busy:return
        chosen=self.table.selection()
        if not chosen:return
        item=next((i for i in self.model.snapshot() if i['id']==chosen[0]),None)
        if item and item.get('directory'):
            try:
                directory=workflow.resolve_checkpoint(self.owner.app_base,item)
                if directory is None:raise FileNotFoundError('Жоба осы қалтадан табылмады. Жобаны output қалтасына көшіріңіз.')
                self.owner.open_project_path(directory);self.owner.review()
            except Exception as e:messagebox.showerror('Жоба',str(e),parent=self)
