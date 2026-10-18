"""A persistent multi-link queue window integrated with the app worker."""
import tkinter as tk
from tkinter import ttk,messagebox
import workflow


LABELS={'queued':'Кезекте','running':'Өңделуде','done':'Дайын','error':'Қате','cancelled':'Тоқтатылды'}


class BatchWindow(tk.Toplevel):
    def __init__(self,owner,model):
        super().__init__(owner);self.owner=owner;self.model=model
        self.title('Матчтарды кезекпен өңдеу');self.geometry('1000x620');self.minsize(800,480)
        self.protocol('WM_DELETE_WINDOW',self.withdraw)
        frame=ttk.Frame(self,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Әр жолға бір YouTube сілтемесі. Барлығына негізгі терезедегі баптаулар қолданылады.').pack(anchor='w')
        self.urls=tk.Text(frame,height=5,wrap='none');self.urls.pack(fill='x',pady=6)
        row=ttk.Frame(frame);row.pack(fill='x',pady=(0,6))
        for text,fn in [('Кезекке қосу',self.add),('Бәрін өңдеу',self.run),
                        ('Тоқтату',owner.cancel_event.set),('Қателерді қайта кезекке қою',self.retry),
                        ('Дайындарын тазалау',self.clear)]:
            ttk.Button(row,text=text,command=fn).pack(side='left',padx=2)
        self.table=ttk.Treeview(frame,columns=('status','title','url','error'),show='headings')
        for key,label,width in [('status','Күйі',100),('title','Матч',180),('url','Сілтеме',270),('error','Мәлімет',320)]:
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=60)
        self.table.pack(fill='both',expand=True)
        self.table.bind('<Double-1>',lambda _:self.open_selected())
        ttk.Button(frame,text='Таңдалған жобаны ашу',command=self.open_selected).pack(anchor='e',pady=6)
        self.status=ttk.Label(frame,text='');self.status.pack(anchor='w');self.refresh()

    def refresh(self,items=None):
        if not self.winfo_exists():return
        items=items if items is not None else self.model.snapshot()
        selected=self.table.selection()
        self.table.delete(*self.table.get_children())
        for item in items:
            self.table.insert('', 'end',iid=item['id'],values=(LABELS.get(item['status'],item['status']),
                item.get('title',''),item['url'],item.get('error','') or item.get('directory','')))
        if selected and self.table.exists(selected[0]):self.table.selection_set(selected[0])
        done=sum(i['status']=='done' for i in items);errors=sum(i['status']=='error' for i in items)
        self.status.configure(text=f'Барлығы: {len(items)} • Дайын: {done} • Қате: {errors}')

    def add(self):
        try:self.model.add(self.urls.get('1.0','end'));self.urls.delete('1.0','end');self.refresh()
        except Exception as e:messagebox.showerror('Кезек',str(e),parent=self)

    def retry(self):self.model.retry_failed();self.refresh()
    def clear(self):self.model.clear_done();self.refresh()

    def run(self):
        if self.owner.busy or self.owner.review_open:
            messagebox.showinfo('Кезек','Ағымдағы жұмысты аяқтаңыз немесе редакторды жабыңыз.',parent=self);return
        try:
            settings=self.owner.settings();music=self.owner.music.get().strip()
            pending=[i for i in self.model.snapshot() if i['status']=='queued']
            if not pending:raise ValueError('Кезекте сілтеме жоқ. Алдымен қосыңыз.')
            base=self.owner.app_base
            def process(url):
                return workflow.create_project(base,url=url,music=music,settings=settings,
                    log=self.owner.log,cancel=self.owner.cancel_event,
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
        self.owner.status.set('Кезек аяқталды. Дайын: '+str(sum(i['status']=='done' for i in items))+
                              ' • Қате: '+str(sum(i['status']=='error' for i in items)))
        self.deiconify()

    def open_selected(self):
        if self.owner.busy:return
        chosen=self.table.selection()
        if not chosen:return
        item=next((i for i in self.model.snapshot() if i['id']==chosen[0]),None)
        if item and item.get('directory'):
            try:self.owner.open_project_path(item['directory']);self.owner.review()
            except Exception as e:messagebox.showerror('Жоба',str(e),parent=self)
