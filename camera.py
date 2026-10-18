"""Conservative action-area framing. Heuristic tracking, not semantic ball AI."""
import math
import cv2
import numpy as np


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
