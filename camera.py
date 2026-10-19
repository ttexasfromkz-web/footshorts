"""Conservative action-area framing. Heuristic tracking, not semantic ball AI."""
import math
import cv2
import numpy as np


class BallTracker:
    """Pitch-constrained round-object tracking with motion and temporal gating."""
    def __init__(self):
        self.point=None;self.velocity=np.zeros(2);self.gray=None;self.last_time=None
        self.last_seen=None;self.confidence=0.;self.moving=0;self.cuts=0

    def update(self,frame,time):
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        h,w=gray.shape;grass=cv2.inRange(hsv,(30,35,25),(95,255,255))
        old=self.gray
        if old is not None and old.shape==gray.shape:
            cut=float(np.mean(cv2.absdiff(cv2.resize(old,(32,18)),cv2.resize(gray,(32,18)))))>48
            if cut:self.point=None;self.velocity[:]=0;self.confidence=0.;self.moving=0;self.cuts+=1;old=None
        dt=max(.05,time-self.last_time) if self.last_time is not None else .25
        prediction=self.point+self.velocity*dt if self.point is not None else np.array([.5,.55])
        candidates=[]
        if np.mean(grass>0)>.22:
            near=cv2.dilate(grass,np.ones((9,9),np.uint8))
            white=cv2.inRange(hsv,(0,0,185),(179,85,255)) & near
            contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area=cv2.contourArea(contour);x,y,cw,ch=cv2.boundingRect(contour)
                if not 3<=area<=85 or not .65<cw/max(1,ch)<1.55 or not h*.08<y<h*.94:continue
                perimeter=cv2.arcLength(contour,True);roundness=4*math.pi*area/max(1,perimeter**2)
                if roundness<.6:continue
                point=np.array([(x+cw/2)/w,(y+ch/2)/h]);distance=float(np.linalg.norm(point-prediction))
                if self.point is not None and distance>max(.08,.65*dt):continue
                motion=float(np.mean(cv2.absdiff(gray[y:y+ch,x:x+cw],old[y:y+ch,x:x+cw])))/255 if old is not None else 0.
                score=.8*roundness+.3*motion-distance*(2 if self.point is not None else .3)
                if score>.3:candidates.append((score,point,motion))
        found=bool(candidates)
        if found:
            _,point,motion=max(candidates,key=lambda c:c[0])
            if self.point is not None:
                self.velocity=np.clip(.4*self.velocity+.6*(point-self.point)/dt,-.7,.7)
            self.point=point;self.last_seen=time
            if motion>.06:self.moving+=1
            self.confidence=min(1.,.7*self.confidence+.3*(.5+min(.5,motion*2)))
        else:
            self.confidence*=.65
            if self.last_seen is not None and time-self.last_seen>1.5:
                self.point=None;self.velocity[:]=0;self.moving=0;self.confidence=0.
        self.gray=gray;self.last_time=time
        return (float(self.point[0]) if self.point is not None else .5,
                found and self.confidence>=.45 and self.moving>=2)


def goal_regions(frame):
    """Conservative white post/crossbar geometry; absent evidence means no crop."""
    h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(0,0,190),(179,90,255))
    lines=cv2.HoughLinesP(cv2.Canny(mask,70,160),1,np.pi/180,14,minLineLength=max(18,int(h*.05)),maxLineGap=7)
    if lines is None:return []
    vertical=[];horizontal=[]
    for line in np.asarray(lines).reshape(-1,4)[:160]:
        x1,y1,x2,y2=map(float,line);dx=abs(x2-x1);dy=abs(y2-y1)
        if dy>max(18,h*.05) and dy<h*.5 and dx<dy*.2:
            x=(x1+x2)/2
            if x<w*.42 or x>w*.58:vertical.append((x,min(y1,y2),max(y1,y2)))
        if dx>24 and dx<w*.28 and dy<dx*.24:horizontal.append((min(x1,x2),max(x1,x2),(y1+y2)/2))
    candidates=[]
    for i,a in enumerate(vertical):
        for b in vertical[i+1:]:
            left,right=sorted((a,b));width=right[0]-left[0];height=min(a[2]-a[1],b[2]-b[1])
            if not 24<width<w*.25 or not 1.1<width/height<3.7:continue
            if abs(a[1]-b[1])>height*.35+4 or abs(a[2]-b[2])>height*.4+5:continue
            top=(a[1]+b[1])/2
            if not any(abs(x-left[0])<13 and abs(y-right[0])<13 and abs(v-top)<12 for x,y,v in horizontal):continue
            candidates.append((width*height,((left[0]-3)/w,min(a[1],b[1])/h,(right[0]+3)/w,max(a[2],b[2])/h)))
    return [max(candidates,key=lambda c:c[0])[1]] if candidates else []


def goal_fits_crop(regions,x,width_fraction,height_fraction=1.):
    left=max(0,min(1-width_fraction,x-width_fraction/2));right=left+width_fraction
    top=(1-height_fraction)/2;bottom=top+height_fraction
    return any(left<=a and b<=right and top<=y1 and y2<=bottom for a,y1,b,y2 in regions)


def track_details(video,start,end,crop_top=0,cancel=None,goal_at=None,zoom=1):
    cap=cv2.VideoCapture(str(video));tracker=BallTracker();samples=[];trusted=[]
    critical_regions=[];width_fraction=1.;height_fraction=1.
    try:
        for t in np.arange(start,end,max(.25,(end-start)/80)):
            if cancel and cancel.is_set():
                from core import Cancelled
                raise Cancelled()
            cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000);ok,frame=cap.read()
            if not ok:continue
            sw,_,available,pw,ph=geometry(frame.shape[1],frame.shape[0],crop_top,zoom);width_fraction=pw/sw;height_fraction=ph/available
            frame=frame[int(frame.shape[0]*crop_top):]
            frame=cv2.resize(frame,(640,max(2,round(frame.shape[0]*640/frame.shape[1]))))
            x,reliable=tracker.update(frame,float(t));samples.append((float(t-start),x));trusted.append((t,reliable))
            if goal_at is not None and abs(t-goal_at)<=2:critical_regions.append((len(samples)-1,goal_regions(frame)))
    finally:cap.release()
    confidence=sum(ok for _,ok in trusted)/max(1,len(trusted))
    critical=[ok for t,ok in trusted if goal_at is not None and abs(t-goal_at)<=3]
    goal_confidence=sum(critical)/len(critical) if critical else confidence
    points=smooth_targets(samples,max_rate=.3)
    visible=sum(goal_fits_crop(regions,points[index][1],width_fraction,height_fraction) for index,regions in critical_regions)/len(critical_regions) if critical_regions else 0.
    return dict(points=points,confidence=confidence,goal_confidence=goal_confidence,goal_visible_fraction=visible,
                safe_crop=bool(confidence>=.45 and goal_confidence>=.4 and tracker.cuts<=2 and (goal_at is None or visible>=.6)))


def focus(frame,previous=.5):
    """Prefer small round white objects on grass; otherwise use player groups."""
    h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    grass=cv2.inRange(hsv,(30,35,25),(95,255,255))
    if np.count_nonzero(grass)<w*h*.22:return .5,False
    near=cv2.dilate(grass,np.ones((13,13),np.uint8))
    white=cv2.inRange(hsv,(0,0,185),(179,80,255)) & near
    contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    balls=[]
    for c in contours:
        area=cv2.contourArea(c);x,y,cw,ch=cv2.boundingRect(c)
        if not 3<=area<=65 or not .6<cw/max(ch,1)<1.65 or y<h*.08 or y>h*.94:continue
        perimeter=cv2.arcLength(c,True)
        circularity=4*math.pi*area/max(perimeter*perimeter,1)
        if circularity<.58:continue
        cx=(x+cw/2)/w
        balls.append((circularity-.45*abs(cx-previous),cx))
    if balls and max(balls)[0]>.58:return max(balls)[1],True
    # Grass surrounded foreground components approximate the active player cluster.
    region=cv2.morphologyEx(grass,cv2.MORPH_CLOSE,np.ones((31,31),np.uint8))
    foreground=region & cv2.bitwise_not(grass)
    contours,_=cv2.findContours(foreground,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    players=[]
    for c in contours:
        area=cv2.contourArea(c);x,y,cw,ch=cv2.boundingRect(c)
        if 30<area<1200 and ch>cw*.8 and h*.12<y<h*.9:players.append((x+cw/2)/w)
    return (float(np.median(players)),False) if len(players)>=2 else (previous,False)


def smooth_targets(samples,max_rate=.22):
    if not samples:return [(0,.5)]
    result=[];x=samples[0][1]
    for i,(t,target) in enumerate(samples):
        median=float(np.median([s[1] for s in samples[max(0,i-1):i+2]]))
        dt=t-result[-1][0] if result else 0
        # No sudden pans when a candidate is lost or a white jersey is mistaken for a ball.
        if result:x+=max(-max_rate*dt,min(max_rate*dt,(median-x)*.65))
        result.append((float(t),max(0,min(1,x))))
    return result


def track(video,start,end,crop_top=0,cancel=None):
    cap=cv2.VideoCapture(str(video));samples=[];previous=.5
    try:
        # Work only on chosen footage, twice per source second.
        for t in np.arange(start,end,max(.5,(end-start)/80)):
            if cancel and cancel.is_set():
                from core import Cancelled
                raise Cancelled()
            cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000);ok,frame=cap.read()
            if not ok:continue
            frame=frame[int(frame.shape[0]*crop_top):]
            frame=cv2.resize(frame,(640,max(2,round(frame.shape[0]*640/frame.shape[1]))))
            x,ball=focus(frame,previous)
            # Weak observations do not pull the camera rapidly away from the last focus.
            previous=x if ball or not samples else .35*previous+.65*x
            samples.append((float(t-start),previous))
    finally:cap.release()
    return smooth_targets(samples)


def crop_expression(points,source_width,crop_width,speed=1):
    """Linear pan in output time. Crop clamps preserve the image at both edges."""
    values=[(t/speed,max(0,min(source_width-crop_width,x*source_width-crop_width/2))) for t,x in points]
    expr=f'{values[-1][1]:.3f}'
    for (a,x),(b,y) in reversed(list(zip(values,values[1:]))):
        if b<=a:continue
        expr=f'if(lt(t,{b:.3f}),{x:.3f}+({y-x:.3f})*clip((t-{a:.3f})/{b-a:.3f},0,1),{expr})'
    return expr



def geometry(width,height,crop_top=0,zoom=1):
    source_w=int(width)//2*2;top=int(height*crop_top)//2*2
    available=(int(height)-top)//2*2
    ph=max(2,int(available/float(zoom))//2*2)
    pw=max(2,min(source_w,int(ph*9/16)//2*2))
    ph=max(2,min(ph,int(pw*16/9)//2*2))
    return source_w,top,available,pw,ph


def manual_rectangle(clip,time,width,height,crop_top=0):
    from review_model import interpolate
    sw,top,available,pw,ph=geometry(width,height,crop_top,clip.get('zoom',1))
    points=clip.get('focus_points',[])
    x=interpolate(points,time,'x')*sw-pw/2
    y=interpolate(points,time,'y',crop_top+(1-crop_top)/2)*height-ph/2
    return max(0,min(sw-pw,x)),max(top,min(top+available-ph,y)),pw,ph


def manual_tracks(clip,height,top,available):
    from review_model import interpolate
    points=clip.get('focus_points',[])
    start,end=clip['start'],clip['end']
    times=sorted({start,end,*(p['time'] for p in points if start<p['time']<end)})
    xs=[(t-start,interpolate(points,t,'x')) for t in times]
    ys=[(t-start,max(0,min(1,(interpolate(points,t,'y')*height-top)/available))) for t in times]
    return xs,ys
