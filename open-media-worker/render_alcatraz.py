#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
import soundfile as sf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W,H,FPS=1920,1080,30
OUT=Path(os.environ.get("OPEN_MEDIA_OUTPUT","dist")).resolve()
TMP=OUT/"tmp"
FFMPEG=shutil.which("ffmpeg") or "ffmpeg"
FFPROBE=shutil.which("ffprobe") or "ffprobe"
UA="ALOS-Open-Media-Worker/1.0"
FBI="https://www.fbi.gov/history/cases-and-criminals/alcatraz-escape"
NPS="https://www.nps.gov/alca/learn/historyculture/escapes2.htm"
COMMONS_API="https://commons.wikimedia.org/w/api.php"

NARRATION=[
("c1","On June 11, 1962, Frank Morris and brothers John and Clarence Anglin escaped from their cells at Alcatraz.",FBI),
("c2","A fourth conspirator, Allen West, helped plan the escape but did not make it out of his cell that night.",FBI),
("c3","The men widened ventilation openings and moved into the utility corridor behind the cell block.",FBI),
("c4","Dummy heads left in their beds delayed discovery until the following morning.",FBI),
("c5","Investigators concluded the escapees built flotation equipment from raincoats before moving toward the shoreline.",FBI),
("c6","Their exact route across San Francisco Bay, and whether they reached land, remain unresolved.",FBI),
("c7","Searches recovered pieces of escape equipment, but no recovered evidence conclusively proved either survival or drowning.",FBI),
("c8","The FBI closed its active case in 1979 and transferred fugitive responsibility to the United States Marshals Service.",FBI),
]

SEARCHES=[
("dummy-head","Alcatraz dummy head escape Frank Morris"),
("cellhouse","Alcatraz cellhouse interior"),
("cells","Alcatraz prison cells interior"),
("island","Alcatraz Island prison"),
("guard","Alcatraz guard tower prison"),
("bay","Alcatraz San Francisco Bay"),
]

LICENSE_OK=("public domain","cc0","cc by","cc-by","cc by-sa","cc-by-sa","creative commons")

def run(cmd:list[str], timeout:int=1800)->subprocess.CompletedProcess:
    env=dict(os.environ)
    for k in ["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"]:
        env[k]=""
    env["NO_PROXY"]="*"; env["no_proxy"]="*"
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed ({p.returncode}): {(p.stderr or p.stdout)[-3000:]}")
    return p

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def font(size:int,bold:bool=False):
    candidates=[
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).is_file(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def clean_html(text:str)->str:
    return re.sub(r"<[^>]+>"," ",text or "").replace("&amp;","&").strip()

def commons_search(label:str,query:str)->dict:
    params={
        "action":"query","format":"json","generator":"search","gsrnamespace":"6",
        "gsrsearch":query,"gsrlimit":"12","prop":"imageinfo",
        "iiprop":"url|extmetadata|size"
    }
    r=requests.get(COMMONS_API,params=params,headers={"user-agent":UA},timeout=30)
    r.raise_for_status()
    pages=list((r.json().get("query",{}).get("pages",{}) or {}).values())
    candidates=[]
    for page in pages:
        info=(page.get("imageinfo") or [None])[0] or {}
        meta=info.get("extmetadata") or {}
        license_text=" | ".join(str(meta.get(k,{}).get("value","")) for k in ["LicenseShortName","UsageTerms","Copyrighted"])
        url=info.get("thumburl") or info.get("url")
        w=int(info.get("thumbwidth") or info.get("width") or 0)
        h=int(info.get("thumbheight") or info.get("height") or 0)
        if not url or min(w,h)<500: continue
        if not any(x in license_text.lower() for x in LICENSE_OK): continue
        score=(w*h) + (5000000 if "public domain" in license_text.lower() else 0)
        candidates.append((score,page.get("title",""),url,license_text,meta))
    if not candidates:
        raise RuntimeError(f"no admissible Commons image for {query}")
    candidates.sort(reverse=True,key=lambda x:x[0])
    _,title,url,license_text,meta=candidates[0]
    return {
        "id":label,"query":query,"title":title,"url":url,
        "license":clean_html(license_text),
        "artist":clean_html(str(meta.get("Artist",{}).get("value",""))),
        "credit":clean_html(str(meta.get("Credit",{}).get("value",""))),
        "sourcePage":"https://commons.wikimedia.org/wiki/"+requests.utils.quote(title.replace(" ","_"),safe=":/_"),
    }

def download(url:str,target:Path):
    with requests.get(url,headers={"user-agent":UA},timeout=60,stream=True) as r:
        r.raise_for_status()
        target.parent.mkdir(parents=True,exist_ok=True)
        total=0
        with target.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if not chunk: continue
                total+=len(chunk)
                if total>40*1024*1024: raise RuntimeError("archive image exceeds 40MB")
                f.write(chunk)
    if target.stat().st_size<10_000: raise RuntimeError(f"download too small: {target}")

def fit_crop(im:Image.Image,size=(W,H))->Image.Image:
    im=im.convert("RGB")
    scale=max(size[0]/im.width,size[1]/im.height)
    im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.LANCZOS)
    x=(im.width-size[0])//2; y=(im.height-size[1])//2
    return im.crop((x,y,x+size[0],y+size[1]))

def polish_image(src:Path,dst:Path):
    im=fit_crop(Image.open(src))
    im=ImageEnhance.Contrast(im).enhance(1.07)
    im=ImageEnhance.Color(im).enhance(.92)
    im=ImageEnhance.Sharpness(im).enhance(1.05)
    overlay=Image.new("RGBA",(W,H),(0,0,0,0));d=ImageDraw.Draw(overlay)
    for y in range(H):
        a=int(55*(abs(y-H/2)/(H/2))**1.8)
        d.line((0,y,W,y),fill=(0,0,0,a))
    im=Image.alpha_composite(im.convert("RGBA"),overlay).convert("RGB")
    im.save(dst,quality=94)

def make_archive_clip(image:Path,out:Path,duration:float,mode:int,title:str):
    z = "min(zoom+0.00055,1.10)" if mode%2==0 else "if(lte(on,1),1.10,max(1,zoom-0.00055))"
    x = "iw/2-(iw/zoom/2)+sin(on/70)*9"
    y = "ih/2-(ih/zoom/2)+cos(on/83)*6"
    vf=(
        f"scale=2200:-2,zoompan=z='{z}':x='{x}':y='{y}':"
        f"d=1:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.04:saturation=.93:brightness=-.015,"
        "format=yuv420p"
    )
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-loop","1","-i",str(image),
         "-t",f"{duration:.3f}","-vf",vf,"-an","-c:v","libx264","-preset","medium","-crf","18",
         "-pix_fmt","yuv420p",str(out)],timeout=900)

def write_raw_video(out:Path,duration:float,frame_fn):
    frames=max(1,round(duration*FPS))
    proc=subprocess.Popen([FFMPEG,"-hide_banner","-loglevel","error","-y",
        "-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","pipe:0",
        "-an","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",str(out)],
        stdin=subprocess.PIPE)
    for n in range(frames):
        t=n/max(1,frames-1)
        proc.stdin.write(frame_fn(n,t).convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait()!=0: raise RuntimeError(f"raw-video encode failed: {out}")

def make_map_clip(out:Path,duration:float):
    def frame(n,t):
        im=Image.new("RGB",(W,H),(7,29,45));d=ImageDraw.Draw(im,"RGBA")
        # Stylized San Francisco Bay geography, explicitly schematic.
        d.polygon([(0,610),(220,530),(430,565),(650,505),(820,610),(690,1080),(0,1080)],fill=(53,70,65,255))
        d.polygon([(1490,0),(1920,0),(1920,1080),(1740,910),(1600,670),(1660,390)],fill=(50,67,62,255))
        alca=(1110,450); sf=(460,770); angel=(1370,245); marin=(1600,620)
        d.ellipse((alca[0]-95,alca[1]-48,alca[0]+95,alca[1]+48),fill=(79,88,76,255),outline=(220,224,207,220),width=3)
        d.ellipse((angel[0]-140,angel[1]-75,angel[0]+140,angel[1]+75),fill=(64,78,68,255),outline=(130,150,136,180),width=2)
        d.text((58,54),"ESCAPE ROUTE • SCHEMATIC",font=font(42,True),fill=(245,241,232,255))
        d.text((58,112),"June 1962 • San Francisco Bay",font=font(25),fill=(190,205,212,255))
        for pos,label in [(alca,"ALCATRAZ"),(sf,"SAN FRANCISCO"),(angel,"ANGEL IS."),(marin,"MARIN")]:
            d.text((pos[0]-72,pos[1]+58 if pos==alca else pos[1]+24),label,font=font(24,True),fill=(235,238,233,245))
        routes=[(sf,(239,164,82,245),7),(angel,(196,204,206,150),4),(marin,(196,204,206,150),4)]
        for i,(target,color,width) in enumerate(routes):
            q=max(0,min(1,(t-i*.11)/.72))
            ex=alca[0]+(target[0]-alca[0])*q; ey=alca[1]+(target[1]-alca[1])*q
            d.line((alca[0],alca[1],ex,ey),fill=color,width=width)
            if q>.98:d.ellipse((target[0]-7,target[1]-7,target[0]+7,target[1]+7),fill=color)
        d.rectangle((55,H-104,W-55,H-45),fill=(2,15,25,180))
        d.text((78,H-91),"SOURCE GROUNDING: FBI + NPS • exact route and outcome unresolved",font=font(23),fill=(218,225,227,240))
        return im
    write_raw_video(out,duration,frame)

def make_evidence_clip(image:Path,out:Path,duration:float):
    base=fit_crop(Image.open(image)).filter(ImageFilter.GaussianBlur(10))
    fg=Image.open(image).convert("RGB")
    fg.thumbnail((1120,820),Image.Resampling.LANCZOS)
    def frame(n,t):
        im=base.copy().convert("RGBA");d=ImageDraw.Draw(im,"RGBA")
        d.rectangle((0,0,W,H),fill=(0,0,0,110))
        # subtle evidence-card drift
        x=W//2-fg.width//2+round(math.sin(t*math.pi)*14);y=128+round((.5-t)*10)
        card=Image.new("RGBA",(fg.width+34,fg.height+34),(238,235,225,255))
        card.alpha_composite(fg.convert("RGBA"),(17,17))
        im.alpha_composite(card,(x-17,y-17))
        d.text((70,62),"PHYSICAL EVIDENCE",font=font(38,True),fill=(247,238,219,255))
        d.text((70,111),"Dummy heads delayed discovery",font=font(25),fill=(201,211,214,255))
        d.rectangle((65,H-105,W-65,H-47),fill=(0,0,0,185))
        d.text((88,H-91),"ARCHIVAL IMAGE • RIGHTS CHECKED BEFORE RENDER",font=font(22,True),fill=(226,230,225,255))
        return im.convert("RGB")
    write_raw_video(out,duration,frame)

def make_reconstruction_clip(out:Path,duration:float):
    def frame(n,t):
        im=Image.new("RGB",(W,H),(10,14,19));d=ImageDraw.Draw(im,"RGBA")
        # perspective corridor, deliberately labeled reconstruction.
        horizon=420
        d.polygon([(0,H),(W,H),(1320,horizon),(600,horizon)],fill=(41,44,46,255))
        d.polygon([(0,0),(600,horizon),(1320,horizon),(W,0)],fill=(25,28,30,255))
        d.polygon([(0,0),(0,H),(600,horizon)],fill=(31,34,36,255))
        d.polygon([(W,0),(1320,horizon),(W,H)],fill=(30,33,35,255))
        # sliding camera parallax
        drift=(t-.5)*110
        for i in range(7):
            yy=horizon+70+i*73
            d.line((0,yy,W,yy),fill=(116,120,118,80),width=2)
        for i in range(5):
            x=610+i*145+drift
            d.rectangle((x,horizon-20,x+92,horizon+240),outline=(116,121,119,190),width=5)
            for b in range(5):
                bx=x+13+b*16
                d.line((bx,horizon-14,bx,horizon+214),fill=(145,150,147,180),width=4)
        # silhouette moving through service corridor
        sx=860+round((t-.5)*260);sy=690
        d.ellipse((sx-26,sy-112,sx+26,sy-60),fill=(8,9,10,255))
        d.rounded_rectangle((sx-35,sy-65,sx+35,sy+48),radius=20,fill=(8,9,10,255))
        d.line((sx-22,sy+40,sx-43,sy+116),fill=(8,9,10,255),width=18)
        d.line((sx+22,sy+40,sx+48,sy+116),fill=(8,9,10,255),width=18)
        # flashlight beam
        d.polygon([(sx+30,sy-30),(sx+390,sy-135),(sx+390,sy+70)],fill=(229,214,164,28))
        d.rectangle((50,48,405,108),fill=(0,0,0,190))
        d.text((70,61),"RECONSTRUCTION",font=font(31,True),fill=(245,177,92,255))
        d.text((70,H-88),"UTILITY CORRIDOR • SOURCE-GROUNDED, NOT HISTORICAL FOOTAGE",font=font(22),fill=(208,214,214,245))
        return im
    write_raw_video(out,duration,frame)

def synthesize_narration(out_wav:Path,out_srt:Path):
    from kokoro import KPipeline
    pipe=KPipeline(lang_code="a")
    rate=24000
    segments=[];timings=[];cursor=0
    gap=np.zeros(int(rate*.16),dtype=np.float32)
    for idx,(cid,text,source) in enumerate(NARRATION):
        chunks=[]
        for _,_,audio in pipe(text,voice="af_heart",speed=.94,split_pattern=r"\n+"):
            chunks.append(np.asarray(audio,dtype=np.float32))
        if not chunks: raise RuntimeError(f"Kokoro returned no audio for {cid}")
        pcm=np.concatenate(chunks)
        start=cursor/rate;end=(cursor+len(pcm))/rate
        timings.append((cid,text,source,start,end))
        segments.append(pcm);cursor+=len(pcm)
        if idx<len(NARRATION)-1:
            segments.append(gap);cursor+=len(gap)
    audio=np.concatenate(segments)
    sf.write(out_wav,audio,rate,subtype="PCM_16")
    def ts(sec:float):
        ms=max(0,round(sec*1000));h=ms//3600000;m=(ms%3600000)//60000;s=(ms%60000)//1000;r=ms%1000
        return f"{h:02}:{m:02}:{s:02},{r:03}"
    srt=[]
    for i,(_,text,_,start,end) in enumerate(timings,1):
        srt.extend([str(i),f"{ts(start)} --> {ts(end)}",text,""])
    out_srt.write_text("\n".join(srt),encoding="utf-8")
    return len(audio)/rate,timings

def duplicate_ratio(video:Path)->dict:
    p=run([FFMPEG,"-hide_banner","-loglevel","error","-i",str(video),"-map","0:v:0","-an","-f","framemd5","-"],timeout=1800)
    hashes=[]
    for line in p.stdout.splitlines():
        if not line or line.startswith("#"): continue
        parts=[x.strip() for x in line.split(",")]
        if parts and re.fullmatch(r"[a-fA-F0-9]{32}",parts[-1] or ""): hashes.append(parts[-1].lower())
    dup=sum(1 for a,b in zip(hashes,hashes[1:]) if a==b)
    return {"frameCount":len(hashes),"adjacentDuplicateFrames":dup,"adjacentDuplicateRatio":dup/max(1,len(hashes)-1)}

def main():
    OUT.mkdir(parents=True,exist_ok=True);TMP.mkdir(parents=True,exist_ok=True)
    archive_dir=OUT/"archive";archive_dir.mkdir(exist_ok=True)
    sources=[]
    for label,query in SEARCHES:
        meta=commons_search(label,query)
        raw=archive_dir/f"{label}-raw.jpg";final=archive_dir/f"{label}.jpg"
        download(meta["url"],raw);polish_image(raw,final)
        meta.update({"localPath":str(final),"sha256":sha256(final)})
        sources.append(meta)
    (OUT/"sources.json").write_text(json.dumps({"schema":"open-media.sources.v1","items":sources},indent=2)+"\n")

    wav=OUT/"narration.wav";srt=OUT/"subtitles.srt"
    audio_dur,timings=synthesize_narration(wav,srt)
    # Keep 10 visual beats and make master match narration.
    duration=max(48.0,min(78.0,audio_dur+.35))
    slot=duration/10.0
    src={x["id"]:Path(x["localPath"]) for x in sources}
    clips=[]
    plan=[
      ("archive",src["island"]),("archive",src["cellhouse"]),("map",None),("archive",src["cells"]),
      ("evidence",src["dummy-head"]),("reconstruction",None),("archive",src["guard"]),("archive",src["bay"]),
      ("map",None),("archive",src["island"])
    ]
    for i,(kind,asset) in enumerate(plan):
        clip=TMP/f"scene-{i+1:02}.mp4"
        if kind=="archive": make_archive_clip(asset,clip,slot,i,kind)
        elif kind=="map": make_map_clip(clip,slot)
        elif kind=="evidence": make_evidence_clip(asset,clip,slot)
        else: make_reconstruction_clip(clip,slot)
        clips.append(clip)
    concat=TMP/"concat.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in clips)+"\n")
    silent=TMP/"silent.mp4"
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),
         "-c","copy","-t",f"{duration:.3f}",str(silent)],timeout=1800)

    master=OUT/"alcatraz-open-media-audition.mp4"
    srt_filter_path=str(srt).replace("\\","/").replace(":","\\\\:")
    subtitle_filter=f"subtitles='{srt_filter_path}':force_style='FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=42'"
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-i",str(silent),"-i",str(wav),
         "-vf",subtitle_filter,"-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","medium","-crf","18",
         "-pix_fmt","yuv420p","-af","loudnorm=I=-16:LRA=11:TP=-1.5","-c:a","aac","-b:a","192k","-ar","48000",
         "-shortest","-movflags","+faststart",str(master)],timeout=2400)

    contact=OUT/"contact-sheet.jpg"
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-i",str(master),
         "-vf","fps=1/6,scale=480:-1,tile=4x3:padding=6:margin=6","-frames:v","1",str(contact)],timeout=600)
    probe=run([FFPROBE,"-v","error","-show_entries","format=duration:stream=width,height,r_frame_rate","-of","json",str(master)])
    cadence=duplicate_ratio(master)
    qa={
      "schema":"open-media.alcatraz-audition-qa.v1",
      "master":{"path":str(master),"sha256":sha256(master),"bytes":master.stat().st_size},
      "probe":json.loads(probe.stdout),"cadence":cadence,
      "visualRoles":{"archive":6,"map":2,"evidence":1,"reconstruction":1},
      "rightsSafeArchiveCount":len(sources),
      "narration":{"engine":"Kokoro local CPU","voice":"af_heart","durationSec":audio_dur,"humanNaturalnessReview":"PENDING"},
      "benchmark":{"id":"youtube:XO1-4FH1X1I","sideBySideStatus":"PENDING"},
      "q9Status":"FAIL_UNTIL_HUMAN_REVIEW",
      "knownGap":"No local AI-video reconstruction in this first public-worker audition; reconstruction is explicitly labeled and locally animated."
    }
    (OUT/"qa.json").write_text(json.dumps(qa,indent=2)+"\n")
    print(json.dumps(qa,indent=2))

if __name__=="__main__":
    main()
