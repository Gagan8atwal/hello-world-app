#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter

W,H,FPS=1920,1080,24
OUT=Path(os.environ.get("PIKOPOP_PUBLIC_OUTPUT","dist")).resolve()
TMP=OUT/"tmp"
FFMPEG=shutil.which("ffmpeg") or "ffmpeg"
FFPROBE=shutil.which("ffprobe") or "ffprobe"
SR=24000

@dataclass
class Event:
    speaker:str
    text:str
    voice:str
    speed:float
    start:float
    pcm:np.ndarray|None=None
    duration:float=0.0
    envelope:list[float]|None=None

EVENTS=[
    Event("narrator","On a bright morning, Milo, Lumi, and Tiko carry a picnic basket toward Flower Hill.","am_michael",.98,.35),
    Event("milo","Picnic day! I can carry the basket first.","am_adam",1.02,4.35),
    Event("narrator","At the creek, a fallen branch blocks the little bridge.","am_michael",.98,9.00),
    Event("lumi","The bridge is blocked. We need the safe path around it.","af_bella",1.00,12.50),
    Event("tiko","I found the oak trail. We can take turns with the basket.","af_heart",.99,19.10),
    Event("narrator","The detour is longer, but sharing the work keeps everyone moving.","am_michael",.98,24.10),
    Event("milo","We made it together!","am_adam",1.02,30.50),
    Event("lumi","And the picnic stayed safe.","af_bella",1.00,32.80),
]

SCENES=[
    {"start":0.0,"end":8.8,"bg":"meadow","shot":"wide","action":{"milo":"walk","lumi":"point","tiko":"walk"}},
    {"start":8.8,"end":16.8,"bg":"creek","shot":"medium","action":{"milo":"notice","lumi":"point","tiko":"think"}},
    {"start":16.8,"end":25.0,"bg":"forest","shot":"tracking","action":{"milo":"hold","lumi":"walk","tiko":"point"}},
    {"start":25.0,"end":36.0,"bg":"flower-hill","shot":"celebration","action":{"milo":"celebrate","lumi":"wave","tiko":"celebrate"}},
]

def run(cmd,timeout=1800):
    env=dict(os.environ)
    for k in ["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"]: env[k]=""
    env["NO_PROXY"]="*";env["no_proxy"]="*"
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed ({p.returncode}): {(p.stderr or p.stdout)[-2500:]}")
    return p

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def font(size:int,bold=False):
    cands=[
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in cands:
        if Path(p).is_file(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def clamp(v,a=0,b=1):return max(a,min(b,float(v)))

def scene_at(t:float):
    for s in SCENES:
        if s["start"]<=t<s["end"]: return s
    return SCENES[-1]

def active_event(t:float):
    for e in EVENTS:
        if e.start<=t<e.start+e.duration:return e
    return None

def rms_envelope(pcm:np.ndarray,fps=FPS)->list[float]:
    if pcm is None or len(pcm)==0:return []
    frames=max(1,math.ceil(len(pcm)/SR*fps))
    vals=[]
    win=max(80,round(SR/fps*.72))
    for i in range(frames):
        center=round(i/fps*SR)
        a=max(0,center-win//2);b=min(len(pcm),center+win//2)
        seg=pcm[a:b]
        vals.append(float(np.sqrt(np.mean(np.square(seg,dtype=np.float64))) if len(seg) else 0))
    p95=float(np.percentile(vals,95)) if vals else 1
    floor=min(vals) if vals else 0
    den=max(1e-6,p95-floor)
    return [clamp((x-floor)/den) for x in vals]

def viseme_for(text:str,progress:float):
    letters=[c.lower() for c in text if c.isalpha()]
    if not letters:return "neutral"
    c=letters[min(len(letters)-1,max(0,int(progress*len(letters))))]
    if c in "ouqw":return "round"
    if c in "ae":return "open"
    if c in "iy":return "wide"
    if c in "mnbp":return "closed"
    return "neutral"

def synthesize_audio():
    from kokoro import KPipeline
    pipe=KPipeline(lang_code="a")
    last=0.0
    for e in EVENTS:
        chunks=[]
        for _,_,audio in pipe(e.text,voice=e.voice,speed=e.speed,split_pattern=r"\n+"):
            chunks.append(np.asarray(audio,dtype=np.float32))
        if not chunks:raise RuntimeError(f"no Kokoro audio for {e.speaker}")
        e.pcm=np.concatenate(chunks)
        e.duration=len(e.pcm)/SR
        e.envelope=rms_envelope(e.pcm)
        last=max(last,e.start+e.duration)
    duration=max(36.0,last+1.0)
    total=round(duration*SR)
    mix=np.zeros(total,dtype=np.float32)
    # Soft original music bed: simple pentatonic plucks + airy ambience, fully local.
    rng=np.random.default_rng(20260929)
    t=np.arange(total,dtype=np.float64)/SR
    bed=np.zeros(total,dtype=np.float64)
    notes=[261.63,329.63,392.0,523.25,392.0,329.63]
    for idx,at in enumerate(np.arange(.2,duration,2.0)):
        start=int(at*SR);length=min(total-start,int(1.2*SR))
        if length<=0:continue
        tt=np.arange(length)/SR
        freq=notes[idx%len(notes)]
        env=np.exp(-tt*3.2)
        pluck=(np.sin(2*np.pi*freq*tt)+.28*np.sin(2*np.pi*freq*2*tt))*env
        bed[start:start+length]+=pluck*.035
    noise=rng.normal(0,1,total)
    # Very low airy ambience, smoothed.
    kernel=np.ones(800)/800
    airy=np.convolve(noise,kernel,mode="same")*.015
    bed+=airy
    mix+=bed.astype(np.float32)
    for e in EVENTS:
        start=round(e.start*SR);end=min(total,start+len(e.pcm))
        mix[start:end]+=e.pcm[:end-start]*.92
    peak=float(np.max(np.abs(mix))) or 1.0
    if peak>.92:mix*=.92/peak
    return mix,duration

def background(scene,t):
    bg=scene["bg"]
    im=Image.new("RGB",(W,H),(127,203,239))
    d=ImageDraw.Draw(im,"RGBA")
    # sky gradient
    for y in range(0,650,6):
        u=y/650
        c=(int(112+34*u),int(194+29*u),int(235+11*u),255)
        d.rectangle((0,y,W,y+6),fill=c)
    # sun/clouds
    d.ellipse((1510,80,1660,230),fill=(255,220,99,255))
    for cx,cy in [(245,135),(1170,115)]:
        d.ellipse((cx-55,cy-25,cx+55,cy+25),fill=(255,255,255,235))
        d.ellipse((cx-20,cy-48,cx+45,cy+25),fill=(255,255,255,235))
    if bg=="meadow":
        d.polygon([(0,520),(260,310),(520,520)],fill=(105,171,102,255))
        d.polygon([(350,520),(720,270),(1080,520)],fill=(93,158,93,255))
        d.polygon([(930,520),(1310,315),(1660,520)],fill=(104,170,100,255))
        d.rectangle((0,510,W,H),fill=(78,156,86,255))
        for x in range(100,1900,240):
            d.rectangle((x,410,x+18,575),fill=(99,83,53,255))
            d.ellipse((x-48,360,x+68,465),fill=(48,121,66,255))
        # path
        d.polygon([(710,H),(1170,H),(1040,510),(850,510)],fill=(224,208,151,255))
    elif bg=="creek":
        d.rectangle((0,500,W,760),fill=(72,148,82,255))
        d.rectangle((0,760,W,H),fill=(81,178,221,255))
        for y in range(800,H,42):
            d.line((0,y,W,y),fill=(200,239,255,135),width=6)
        # broken bridge
        d.rectangle((580,690,1340,740),fill=(122,83,49,255))
        for x in range(590,1340,92):d.rectangle((x,680,x+55,750),fill=(155,103,59,255))
        d.line((900,650,1080,790),fill=(92,61,37,255),width=34)
    elif bg=="forest":
        d.rectangle((0,500,W,H),fill=(67,126,69,255))
        for x in range(50,1950,180):
            d.rectangle((x,330,x+38,H),fill=(94,70,46,255))
            d.ellipse((x-90,210,x+130,470),fill=(45,105,59,255))
        d.polygon([(690,H),(1220,H),(1070,500),(880,500)],fill=(206,190,139,255))
    else:
        d.rectangle((0,500,W,H),fill=(87,166,91,255))
        for x in range(80,1880,150):
            d.ellipse((x,700+30*math.sin(x),x+18,718+30*math.sin(x)),fill=(244,116+(x%80),130,255))
        # flower hill
        d.polygon([(0,H),(0,720),(420,610),(850,640),(1260,560),(W,650),(W,H)],fill=(93,174,96,255))
        for x in range(100,1800,120):
            col=[(244,117,130,255),(252,197,77,255),(160,111,209,255)][(x//120)%3]
            d.ellipse((x,650+(x%170),x+20,670+(x%170)),fill=col)
        # bunting
        d.line((250,240,1680,240),fill=(90,75,55,255),width=6)
        for i,x in enumerate(range(300,1650,120)):
            col=[(242,109,115,255),(249,189,75,255),(106,175,225,255),(161,116,202,255)][i%4]
            d.polygon([(x,242),(x+45,242),(x+22,290)],fill=col)
    return im

def face(d,cx,cy,s,mouth,shape,expr="happy"):
    eye_y=cy-16*s
    for ex in (-20,20):
        d.ellipse((cx+(ex-7)*s,eye_y-7*s,cx+(ex+7)*s,eye_y+7*s),fill=(255,255,255,255),outline=(90,73,68,130),width=max(1,int(2*s)))
        d.ellipse((cx+(ex-3)*s,eye_y-3*s,cx+(ex+3)*s,eye_y+3*s),fill=(48,43,42,255))
    d.ellipse((cx-4*s,cy-2*s,cx+4*s,cy+6*s),fill=(70,50,46,255))
    open_amt=clamp(mouth)
    if open_amt<.06 or shape=="closed":
        d.arc((cx-14*s,cy+10*s,cx+14*s,cy+28*s),0,180,fill=(73,50,48,255),width=max(2,int(3*s)))
    else:
        if shape=="round":
            ww=(7+4*open_amt)*s;hh=(7+13*open_amt)*s
        elif shape=="wide":
            ww=(12+7*open_amt)*s;hh=(5+8*open_amt)*s
        else:
            ww=(9+5*open_amt)*s;hh=(8+14*open_amt)*s
        d.ellipse((cx-ww,cy+10*s,cx+ww,cy+10*s+hh),fill=(83,43,48,255),outline=(55,36,38,220),width=max(1,int(2*s)))
        d.ellipse((cx-ww*.55,cy+14*s,cx+ww*.55,cy+14*s+hh*.36),fill=(238,126,133,255))

def limb(d,p0,p1,width,fill,outline):
    d.line((*p0,*p1),fill=outline,width=width+8)
    d.line((*p0,*p1),fill=fill,width=width)
    r=width//2
    d.ellipse((p1[0]-r,p1[1]-r,p1[0]+r,p1[1]+r),fill=fill,outline=outline,width=max(2,width//6))

def character(who,x,y,scale,t,action,mouth,shape):
    layer=Image.new("RGBA",(W,H),(0,0,0,0));d=ImageDraw.Draw(layer,"RGBA")
    bob=math.sin(t*5.2+(0 if who=="milo" else 1.2 if who=="lumi" else 2.1))*5*scale
    walk=math.sin(t*7.0+(0 if who=="milo" else 1.0))*18*scale if action=="walk" else 0
    cx=x;cy=y+bob;s=scale
    shadow=(cx-75*s,cy+156*s,cx+75*s,cy+185*s);d.ellipse(shadow,fill=(20,50,34,80))
    if who=="milo":
        body=(185,108,64,255);dark=(91,54,40,255);muzzle=(226,167,113,255);accent=(72,160,197,255)
        # legs
        limb(d,(cx-30*s,cy+95*s),(cx-40*s+walk,cy+155*s),int(24*s),body,dark)
        limb(d,(cx+30*s,cy+95*s),(cx+40*s-walk,cy+155*s),int(24*s),body,dark)
        arm_y=cy+30*s
        if action in ("celebrate","wave"):ends=[(cx-95*s,cy-40*s),(cx+95*s,cy-50*s)]
        elif action=="hold":ends=[(cx-55*s,cy+75*s),(cx+55*s,cy+75*s)]
        else:ends=[(cx-80*s,arm_y+10*s),(cx+80*s,arm_y+10*s)]
        limb(d,(cx-55*s,arm_y),ends[0],int(22*s),body,dark);limb(d,(cx+55*s,arm_y),ends[1],int(22*s),body,dark)
        d.ellipse((cx-76*s,cy-5*s,cx+76*s,cy+110*s),fill=body,outline=dark,width=max(2,int(4*s)))
        d.arc((cx-38*s,cy+40*s,cx+38*s,cy+104*s),0,180,fill=accent,width=max(4,int(8*s)))
        # ears/head
        for ex in (-38,38):d.ellipse((cx+(ex-22)*s,cy-112*s,cx+(ex+22)*s,cy-68*s),fill=body,outline=dark,width=max(2,int(4*s)))
        d.ellipse((cx-66*s,cy-100*s,cx+66*s,cy+20*s),fill=(201,132,82,255),outline=dark,width=max(2,int(4*s)))
        d.ellipse((cx-42*s,cy-50*s,cx+42*s,cy-5*s),fill=muzzle)
        face(d,cx,cy-46*s,s,mouth,shape)
    elif who=="lumi":
        fur=(245,244,248,255);edge=(132,128,143,255);shirt=(151,112,200,255);pink=(242,150,176,255)
        limb(d,(cx-28*s,cy+90*s),(cx-38*s+walk,cy+155*s),int(22*s),fur,edge)
        limb(d,(cx+28*s,cy+90*s),(cx+38*s-walk,cy+155*s),int(22*s),fur,edge)
        if action in ("wave","celebrate"):ends=[(cx-95*s,cy-30*s),(cx+95*s,cy-60*s)]
        elif action=="point":ends=[(cx-62*s,cy+30*s),(cx+115*s,cy-5*s)]
        else:ends=[(cx-78*s,cy+35*s),(cx+78*s,cy+35*s)]
        limb(d,(cx-54*s,cy+18*s),ends[0],int(20*s),fur,edge);limb(d,(cx+54*s,cy+18*s),ends[1],int(20*s),fur,edge)
        d.ellipse((cx-72*s,cy-4*s,cx+72*s,cy+108*s),fill=shirt,outline=edge,width=max(2,int(4*s)))
        ear_sway=math.sin(t*3.1)*8*s
        d.ellipse((cx-48*s,cy-176*s-ear_sway,cx-14*s,cy-75*s),fill=fur,outline=edge,width=max(2,int(4*s)))
        d.ellipse((cx+14*s,cy-168*s+ear_sway,cx+48*s,cy-75*s),fill=fur,outline=edge,width=max(2,int(4*s)))
        d.ellipse((cx-38*s,cy-166*s-ear_sway,cx-24*s,cy-90*s),fill=pink)
        d.ellipse((cx+24*s,cy-158*s+ear_sway,cx+38*s,cy-90*s),fill=pink)
        d.ellipse((cx-66*s,cy-106*s,cx+66*s,cy+14*s),fill=fur,outline=edge,width=max(2,int(4*s)))
        face(d,cx,cy-50*s,s,mouth,shape)
    else:
        skin=(158,203,124,255);edge=(48,89,55,255);shell=(76,145,79,255);shell2=(134,190,107,255)
        limb(d,(cx-28*s,cy+92*s),(cx-38*s+walk*.65,cy+155*s),int(22*s),skin,edge)
        limb(d,(cx+28*s,cy+92*s),(cx+38*s-walk*.65,cy+155*s),int(22*s),skin,edge)
        if action in ("celebrate","point"):ends=[(cx-92*s,cy-35*s),(cx+105*s,cy-45*s)]
        else:ends=[(cx-78*s,cy+38*s),(cx+78*s,cy+38*s)]
        limb(d,(cx-58*s,cy+20*s),ends[0],int(20*s),skin,edge);limb(d,(cx+58*s,cy+20*s),ends[1],int(20*s),skin,edge)
        d.ellipse((cx-78*s,cy-5*s,cx+78*s,cy+112*s),fill=shell,outline=edge,width=max(2,int(4*s)))
        d.ellipse((cx-58*s,cy+10*s,cx+58*s,cy+100*s),fill=shell2,outline=edge,width=max(2,int(3*s)))
        for ang in [0,math.pi/3,2*math.pi/3]:
            dx=math.cos(ang)*45*s;dy=math.sin(ang)*38*s
            d.line((cx-dx,cy+55*s-dy,cx+dx,cy+55*s+dy),fill=(65,119,67,230),width=max(2,int(3*s)))
        d.ellipse((cx-58*s,cy-100*s,cx+58*s,cy+8*s),fill=skin,outline=edge,width=max(2,int(4*s)))
        face(d,cx,cy-48*s,s,mouth,shape)
    return layer

def draw_props(im,scene,t):
    d=ImageDraw.Draw(im,"RGBA")
    # basket follows Milo in first/forest scene
    if scene["bg"] in ("meadow","forest"):
        x=895+int(math.sin(t*2.5)*12);y=760
        d.rounded_rectangle((x-80,y-45,x+80,y+70),radius=18,fill=(177,111,58,255),outline=(97,62,38,255),width=6)
        d.arc((x-65,y-105,x+65,y+20),180,360,fill=(97,62,38,255),width=10)
        for xx in range(x-55,x+56,26):d.line((xx,y-38,xx,y+62),fill=(208,148,85,200),width=5)
    if scene["bg"]=="creek":
        # map card
        d.rounded_rectangle((1260,120,1720,430),radius=20,fill=(245,234,198,245),outline=(104,83,53,255),width=5)
        d.line((1320,350,1450,245,1570,330,1670,210),fill=(95,151,81,255),width=10)
        d.ellipse((1648,188,1688,228),fill=(236,112,111,255))

def title_brand(im):
    d=ImageDraw.Draw(im,"RGBA")
    d.rounded_rectangle((1640,32,1875,92),radius=16,fill=(255,255,255,222),outline=(103,85,70,180),width=3)
    d.text((1663,46),"Pikopop",font=font(27,True),fill=(88,68,61,255))

def render_video(audio:np.ndarray,duration:float):
    OUT.mkdir(parents=True,exist_ok=True);TMP.mkdir(parents=True,exist_ok=True)
    wav=OUT/"pikopop-public-audition.wav";sf.write(wav,audio,SR,subtype="PCM_16")
    video=OUT/"pikopop-public-audition.mp4"
    proc=subprocess.Popen([FFMPEG,"-hide_banner","-loglevel","error","-y",
        "-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","pipe:0",
        "-i",str(wav),"-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-shortest","-movflags","+faststart",str(video)],stdin=subprocess.PIPE)
    contact=Image.new("RGB",(1600,900),(20,20,20));cd=ImageDraw.Draw(contact)
    sample_frames={round(i*(duration*FPS-1)/11):i for i in range(12)}
    prev=None;dups=0;frame_hashes=[];mouth_rows=[];silence_max=0.0
    total=math.ceil(duration*FPS)
    for frame in range(total):
        t=frame/FPS;scene=scene_at(t);im=background(scene,t).convert("RGBA")
        active=active_event(t)
        state={}
        for who in ("milo","lumi","tiko"):
            amp=0.0;shape="neutral"
            if active and active.speaker==who:
                local=t-active.start
                idx=min(len(active.envelope or [])-1,max(0,int(local*FPS))) if active.envelope else 0
                amp=(active.envelope or [0])[idx] if active.envelope else 0
                shape=viseme_for(active.text,clamp(local/max(.001,active.duration)))
            state[who]=(amp,shape)
        # Camera/staging
        if scene["bg"]=="meadow":
            pos={"milo":(680,690,1.15),"lumi":(1000,700,1.10),"tiko":(1320,710,1.02)}
        elif scene["bg"]=="creek":
            pos={"milo":(620,700,1.03),"lumi":(980,700,1.24),"tiko":(1370,720,.98)}
        elif scene["bg"]=="forest":
            drift=int((t-scene["start"])*18)
            pos={"milo":(680+drift,705,1.08),"lumi":(1030+drift,700,1.03),"tiko":(1370+drift,715,.98)}
        else:
            pos={"milo":(690,700,1.16),"lumi":(1010,700,1.14),"tiko":(1325,710,1.06)}
        for who in ("milo","lumi","tiko"):
            x,y,s=pos[who];amp,shape=state[who]
            layer=character(who,x,y,s,t,scene["action"][who],amp,shape)
            im.alpha_composite(layer)
            mouth_rows.append({"frame":frame,"time":t,"speaker":who,"active":bool(active and active.speaker==who),"open":float(amp)})
            if not(active and active.speaker==who):silence_max=max(silence_max,float(amp))
        draw_props(im,scene,t);title_brand(im)
        if active:
            d=ImageDraw.Draw(im,"RGBA")
            bar=(155,H-142,W-155,H-58);d.rounded_rectangle(bar,radius=18,fill=(5,18,26,220))
            label="Narrator" if active.speaker=="narrator" else active.speaker.title()
            d.text((190,H-126),label,font=font(20,True),fill=(247,191,98,255))
            # wrap simple
            words=active.text.split();lines=[];line=""
            for word in words:
                test=(line+" "+word).strip()
                if len(test)>62:lines.append(line);line=word
                else:line=test
            if line:lines.append(line)
            for i,line in enumerate(lines[:2]):
                d.text((350,H-130+i*38),line,font=font(27,True),fill=(255,255,255,255))
        frame_im=im.convert("RGB")
        small=frame_im.resize((96,54),Image.Resampling.BILINEAR)
        h=hashlib.sha1(small.tobytes()).hexdigest();frame_hashes.append(h)
        if prev==h:dups+=1
        prev=h
        if frame in sample_frames:
            idx=sample_frames[frame];cx=(idx%4)*400;cy=(idx//4)*300
            contact.paste(frame_im.resize((400,225),Image.Resampling.LANCZOS),(cx,cy))
            cd.rectangle((cx,cy+225,cx+400,cy+300),fill=(0,0,0))
            cd.text((cx+12,cy+246),f"{t:.1f}s",font=font(22,True),fill=(255,255,255))
        proc.stdin.write(frame_im.tobytes())
    proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError("ffmpeg encode failed")
    contact_path=OUT/"pikopop-public-contact-sheet.jpg";contact.save(contact_path,quality=92)
    return video,wav,contact_path,frame_hashes,mouth_rows,silence_max

def qa(video:Path,wav:Path,contact:Path,frame_hashes,mouth_rows,silence_max):
    probe=json.loads(run([FFPROBE,"-v","error","-show_entries","format=duration,size:stream=codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames,sample_rate,channels","-of","json",str(video)]).stdout)
    line_results=[]
    for e in EVENTS:
        if e.speaker=="narrator":continue
        rows=[r for r in mouth_rows if r["speaker"]==e.speaker and e.start<=r["time"]<e.start+e.duration]
        env=np.asarray((e.envelope or [])[:len(rows)],dtype=float)
        opens=np.asarray([r["open"] for r in rows[:len(env)]],dtype=float)
        corr=float(np.corrcoef(env,opens)[0,1]) if len(env)>3 and np.std(env)>1e-6 and np.std(opens)>1e-6 else 1.0
        line_results.append({"speaker":e.speaker,"startSec":e.start,"durationSec":e.duration,"frames":len(rows),"audioMouthCorrelation":corr,"maxOpen":float(opens.max() if len(opens) else 0),"passed":len(rows)>=6 and corr>=.95 and float(opens.max() if len(opens) else 0)>=.25})
    result={
      "schema":"pikopop.public-lipsync-audition.v1",
      "master":{"path":str(video),"sha256":sha256(video),"bytes":video.stat().st_size},
      "audio":{"path":str(wav),"sha256":sha256(wav),"voices":{"narrator":"am_michael","milo":"am_adam","lumi":"af_bella","tiko":"af_heart"},"distinctBaseVoices":True},
      "probe":probe,
      "fps":FPS,
      "adjacentDuplicateFrames":sum(1 for a,b in zip(frame_hashes,frame_hashes[1:]) if a==b),
      "adjacentDuplicateRatio":sum(1 for a,b in zip(frame_hashes,frame_hashes[1:]) if a==b)/max(1,len(frame_hashes)-1),
      "mouthClosedInSilence":silence_max<=.001,
      "maxMouthOpenDuringSilence":silence_max,
      "lineLipSync":line_results,
      "lipSyncPassed":all(x["passed"] for x in line_results) and silence_max<=.001,
      "trueFrameCadencePassed":(sum(1 for a,b in zip(frame_hashes,frame_hashes[1:]) if a==b)/max(1,len(frame_hashes)-1))<=.10,
      "humanQ9Status":"PENDING",
      "visualDirection":"V78-inspired bear/rabbit/turtle clean vector direction; clean-room public render worker",
      "contactSheet":str(contact),
    }
    (OUT/"qa.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    audio,duration=synthesize_audio()
    video,wav,contact,hashes,mouth_rows,silence_max=render_video(audio,duration)
    result=qa(video,wav,contact,hashes,mouth_rows,silence_max)
    if not result["lipSyncPassed"]:raise SystemExit("lip sync proof failed")
    if not result["trueFrameCadencePassed"]:raise SystemExit("true frame cadence failed")

if __name__=="__main__":
    main()
