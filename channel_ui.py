"""Edit and apply channel branding without changing account/login preferences."""
import tkinter as tk
import os
from pathlib import Path
from tkinter import ttk,filedialog,messagebox,colorchooser
from channel_templates import TemplateStore,style


class ChannelWindow(tk.Toplevel):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.store=TemplateStore(owner.app_base)
        self.title('Арна шаблондары');self.geometry('690x480');self.minsize(580,450)
        self.name=tk.StringVar();self.values={k:tk.StringVar(value=v) for k,v in style(owner.channel_style).items()}
        self.music=tk.StringVar(value=owner.music.get())
        frame=ttk.Frame(self,padding=14);frame.pack(fill='both',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=3)
        ttk.Label(row,text='Шаблон атауы',width=18).pack(side='left')
        self.names=ttk.Combobox(row,textvariable=self.name,values=self.store.names());self.names.pack(side='left',fill='x',expand=True)
        self.names.bind('<<ComboboxSelected>>',lambda _:self.load())
        for key,label in [('brand_name','Арна атауы'),('brand_logo','Арна логотипі'),('music','Фондық музыка')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label,width=18).pack(side='left')
            var=self.music if key=='music' else self.values[key]
            ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
            if key!='brand_name':ttk.Button(row,text='Таңдау…',command=lambda k=key:self.pick(k)).pack(side='left',padx=(6,0))
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='Қаріп',width=18).pack(side='left')
        fonts=ttk.Combobox(row,textvariable=self.values['font_name'],values=['Стандарт','Arial','Segoe UI','Calibri'],state='readonly')
        fonts.pack(side='left',fill='x',expand=True);fonts.bind('<<ComboboxSelected>>',lambda _:self.safe(self.choose_font))
        ttk.Button(row,text='Басқа қаріп…',command=lambda:self.pick('font_file')).pack(side='left',padx=(6,0))
        for key,label in [('accent_color','Негізгі түс'),('text_color','Мәтін түсі'),('panel_color','Панель түсі'),('background_color','Фон түсі')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=3)
            ttk.Label(row,text=label,width=18).pack(side='left')
            ttk.Entry(row,textvariable=self.values[key],width=12).pack(side='left')
            ttk.Button(row,text='Түсті таңдау',command=lambda k=key:self.pick_color(k)).pack(side='left',padx=6)
        ttk.Label(frame,text='Сақтағанда негізгі терезедегі материал тілі, кіріспе, соңғы есеп, дыбыс, зум және уақыт шегі де қосылады.',wraplength=620).pack(anchor='w',pady=10)
        row=ttk.Frame(frame);row.pack(fill='x',pady=6)
        for label,fn in [('Шаблонды сақтау',self.save),('Қолдану',self.apply),('Тізімнен өшіру',self.delete)]:
            ttk.Button(row,text=label,command=lambda f=fn:self.safe(f)).pack(side='left',padx=3)

    def safe(self,fn):
        try:fn()
        except Exception as e:messagebox.showerror('Арна шаблоны',str(e),parent=self)

    def pick(self,key):
        types=[('Суреттер','*.png *.jpg *.jpeg *.webp')] if key=='brand_logo' else [('Қаріп','*.ttf *.otf')] if key=='font_file' else [('Музыка','*.mp3 *.wav *.m4a *.ogg')]
        path=filedialog.askopenfilename(parent=self,filetypes=types)
        if path:
            (self.music if key=='music' else self.values[key]).set(path)
            if key=='font_file':self.values['font_name'].set(Path(path).stem)

    def choose_font(self):
        name=self.values['font_name'].get()
        if name=='Стандарт':self.values['font_file'].set('');return
        files={'Arial':'arialbd.ttf','Segoe UI':'seguisb.ttf','Calibri':'calibrib.ttf'}
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/files[name]
        if not path.is_file():
            self.values['font_file'].set('');self.values['font_name'].set('Стандарт')
            raise FileNotFoundError('Бұл қаріп табылмады. Басқа қаріпті таңдаңыз.')
        self.values['font_file'].set(str(path))

    def pick_color(self,key):
        color=colorchooser.askcolor(self.values[key].get(),parent=self)[1]
        if color:self.values[key].set(color)

    def load(self):
        def run():
            record=self.store.get(self.name.get());self.loaded=record
            for k,v in style(record['settings'].get('channel_style')).items():self.values[k].set(v)
            self.music.set(record.get('music_file',''))
        self.safe(run)

    def save(self):
        settings=self.owner.settings(validate_auth=False);settings['channel_style']=style({k:v.get() for k,v in self.values.items()})
        self.store.save(self.name.get(),settings,self.music.get().strip());self.names.configure(values=self.store.names())
        self.load();self.owner.status.set('Арна шаблоны сақталды: '+self.name.get())

    def apply(self):
        if self.owner.busy:raise ValueError('Ағымдағы жұмыстың аяқталуын күтіңіз.')
        record=self.store.get(self.name.get());settings=dict(record['settings'])
        settings['channel_style']=style({k:v.get() for k,v in self.values.items()})
        self.owner.apply_channel_settings(settings);self.owner.music.set(self.music.get().strip())
        self.owner.status.set('Арна шаблоны қолданылды: '+record['name']+'. Дайын видеоға қолдану үшін қайта жасаңыз.')
        self.destroy()

    def delete(self):
        self.store.delete(self.name.get());self.names.configure(values=self.store.names());self.name.set('')
