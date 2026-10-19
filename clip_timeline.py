"""Draggable montage timeline: edge trim, reorder and source-time goal markers."""
import tkinter as tk
from tkinter import ttk


def clock(t):return f'{int(t)//60:02}:{float(t)%60:04.1f}'


class ClipTimeline(ttk.Frame):
    def __init__(self,parent,model,on_select,on_edit,on_error):
        super().__init__(parent);self.model=model;self.on_select=on_select;self.on_edit=on_edit;self.on_error=on_error
        self.selected=0;self.blocks=[];self.drag=None
        ttk.Label(self,text='Таймлайн: шетін сүйреу — қысқарту • ортасын сүйреу — орнын ауыстыру').pack(anchor='w')
        self.canvas=tk.Canvas(self,height=78,bg='#111e2d',highlightthickness=0)
        self.canvas.pack(fill='x',expand=True)
        scroll=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview);scroll.pack(fill='x')
        self.canvas.configure(xscrollcommand=scroll.set)
        self.canvas.bind('<Configure>',lambda _:self.redraw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Motion>',self.hover)

    def redraw(self,selected=None):
        if selected is not None:self.selected=selected
        self.canvas.delete('all');self.blocks=[];x=12.;elapsed=0.
        for i,c in enumerate(self.model.clips):
            duration=c['end']-c['start'];width=max(90.,duration*9)
            self.blocks.append((x,x+width));goal=c.get('goal_at') is not None
            fill='#1e6e66' if goal else '#294c70'
            self.canvas.create_rectangle(x,23,x+width,69,fill=fill,outline='#ffd274' if i==self.selected else '#6a8195',width=2)
            self.canvas.create_rectangle(x+2,25,x+7,67,fill='#c5dae5',outline='')
            self.canvas.create_rectangle(x+width-7,25,x+width-2,67,fill='#c5dae5',outline='')
            self.canvas.create_text(x+width/2,36,text=f'{i+1}  {clock(c["start"])}–{clock(c["end"])}',fill='white',width=max(30,width-20),font=('Segoe UI',8))
            self.canvas.create_text(x+width/2,57,text=f'{duration:.1f} сек',fill='#d2e4ed',font=('Segoe UI',8))
            self.canvas.create_text(x,10,text=clock(elapsed),fill='#b7ccd7',anchor='w',font=('Segoe UI',8))
            for t in c.get('goal_times',[c['goal_at']] if goal else []):
                gx=x+width*(t-c['start'])/duration
                self.canvas.create_line(gx,23,gx,69,fill='#ffdd6a',width=2)
            elapsed+=duration/float(c.get('speed',1));x+=width+8
        self.canvas.configure(scrollregion=(0,0,max(x,self.canvas.winfo_width()),78))

    def hit(self,event):
        x=self.canvas.canvasx(event.x)
        if not 20<=event.y<=72:return None
        return next((i for i,(a,b) in enumerate(self.blocks) if a<=x<=b),None)

    def hover(self,event):
        i=self.hit(event);cursor='arrow'
        if i is not None:
            a,b=self.blocks[i];x=self.canvas.canvasx(event.x)
            cursor='sb_h_double_arrow' if min(x-a,b-x)<10 else 'hand2'
        self.canvas.configure(cursor=cursor)

    def press(self,event):
        i=self.hit(event)
        if i is None:return
        x=self.canvas.canvasx(event.x);a,b=self.blocks[i];c=self.model.clips[i]
        mode='start' if x-a<10 else 'end' if b-x<10 else 'move'
        self.drag=dict(index=i,x=x,mode=mode,start=c['start'],end=c['end'],scale=(c['end']-c['start'])/(b-a))
        self.on_select(i);self.redraw(i)

    def proposed(self,event):
        d=self.drag;delta=(self.canvas.canvasx(event.x)-d['x'])*d['scale']
        if d['mode']=='start':return max(0,min(d['end']-.2,d['start']+delta)),d['end']
        return d['start'],max(d['start']+.2,min(self.model.duration,d['end']+delta))

    def motion(self,event):
        if not self.drag:return
        self.canvas.delete('ghost');x=self.canvas.canvasx(event.x)
        if self.drag['mode']=='move':text='Осы орынға жылжыту'
        else:
            start,end=self.proposed(event);text=clock(start)+' – '+clock(end)
        self.canvas.create_line(x,18,x,74,fill='#ffcf63',width=3,tags='ghost')
        self.canvas.create_text(x,10,text=text,fill='#ffcf63',tags='ghost')
        if event.x<16:self.canvas.xview_scroll(-1,'units')
        elif event.x>self.canvas.winfo_width()-16:self.canvas.xview_scroll(1,'units')

    def release(self,event):
        if not self.drag:return
        d=self.drag;self.drag=None;index=d['index'];x=self.canvas.canvasx(event.x)
        try:
            if abs(x-d['x'])>2:
                if d['mode']=='move':
                    destination=sum(x>(a+b)/2 for i,(a,b) in enumerate(self.blocks) if i!=index)
                    self.model.move(index,destination);index=destination
                else:
                    # proposed() uses the original drag bounds, once per undo operation.
                    self.drag=d;start,end=self.proposed(event);self.drag=None
                    self.model.trim(index,round(start,2),round(end,2))
            self.on_edit(index)
        except Exception as e:self.drag=None;self.on_error(str(e))
        self.redraw(index)
