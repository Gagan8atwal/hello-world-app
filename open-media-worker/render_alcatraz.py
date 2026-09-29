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
import time
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
UA="ALOS-Open-Media-Worker/1.1 (https://github.com/Gagan8atwal/hello-world-app)"
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
("cellhouse","Alcatraz cellhouse prison interior"),
("cells","Alcatraz prison cells interior"),
("island","Alcatraz Island prison"),
("guard","Alcatraz guardhouse Alcatraz Island"),
("bay","Alcatraz San Francisco Bay"),
("historic-map","San francisco bay map Alcatraz NASA"),
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
        "iiprop":"url|extmetadata|size|mime","iiurlwidth":"1800"
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
        mime=str(info.get("mime") or "")
        if not mime.startswith("image/"): continue
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

def download(url:str,target:Path,max_bytes:int=40*1024*1024):
    target.parent.mkdir(parents=True,exist_ok=True)
    last=None
    for attempt in range(5):
        try:
            with requests.get(url,headers={"user-agent":UA,"accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},timeout=60,stream=True) as r:
                if r.status_code in (429,500,502,503,504):
                    last=RuntimeError(f"transient archive HTTP {r.status_code}")
                else:
                    r.raise_for_status()
                    total=0
                    with target.open("wb") as f:
                        for chunk in r.iter_content(1024*1024):
                            if not chunk: continue
                            total+=len(chunk)
                            if total>max_bytes: raise RuntimeError(f"archive media exceeds {max_bytes} bytes")
                            f.write(chunk)
                    if target.stat().st_size<10_000: raise RuntimeError(f"download too small: {target}")
                    return
        except Exception as exc:
            last=exc
        if target.exists(): target.unlink()
        time.sleep(min(16,2**attempt))
    raise RuntimeError(f"archive download failed after retries: {url}: {last}")

def fit_crop(im:Image.Image,size=(W,H))->Image.Image:
    im=im.convert("RGB")
    scale=max(size[0]/im.width,size[1]/im.height)
    im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.LANCZOS)
    x=(im.width-size[0])//2; y=(im.height-size[1])//2
    return im.crop((x,y,x+size[0],y+size[1]))

def commons_exact_video(title:str,label:str)->dict:
    params={"action":"query","format":"json","prop":"imageinfo","titles":title,
            "iiprop":"url|extmetadata|size|mime"}
    r=requests.get(COMMONS_API,params=params,headers={"user-agent":UA},timeout=30)
    r.raise_for_status()
    page=next(iter((r.json().get("query",{}).get("pages",{}) or {}).values()),{})
    info=(page.get("imageinfo") or [None])[0] or {}
    meta=info.get("extmetadata") or {}
    license_text=" | ".join(str(meta.get(k,{}).get("value","")) for k in ["LicenseShortName","UsageTerms","Copyrighted"])
    mime=str(info.get("mime") or "")
    url=info.get("url")
    if not url or not (mime.startswith("video/") or (mime=="application/ogg" and title.lower().endswith(".ogv"))): raise RuntimeError(f"Commons video unavailable: {title} mime={mime}")
    if not any(x in license_text.lower() for x in LICENSE_OK): raise RuntimeError(f"Commons video license rejected: {license_text}")
    return {"id":label,"title":page.get("title",title),"url":url,"mime":mime,
            "license":clean_html(license_text),
            "artist":clean_html(str(meta.get("Artist",{}).get("value",""))),
            "credit":clean_html(str(meta.get("Credit",{}).get("value",""))),
            "sourcePage":"https://commons.wikimedia.org/wiki/"+requests.utils.quote(title.replace(" ","_"),safe=":/_")}

def make_broll_clip(video:Path,out:Path,duration:float,start:float):
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-ss",f"{start:.3f}","-i",str(video),
         "-t",f"{duration:.3f}","-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.05:saturation=.92:brightness=-.01,fps={FPS},format=yuv420p",
         "-an","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",str(out)],timeout=900)

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
    z = "min(zoom+0.0012,1.18)" if mode%2==0 else "if(lte(on,1),1.18,max(1,zoom-0.0012))"
    x = "iw/2-(iw/zoom/2)+sin(on/48)*28"
    y = "ih/2-(ih/zoom/2)+cos(on/57)*16"
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

def make_map_clip(map_image:Path,out:Path,duration:float):
    base=fit_crop(Image.open(map_image)).convert("RGB")
    base=ImageEnhance.Contrast(base).enhance(1.15)
    base=ImageEnhance.Color(base).enhance(.55)
    dark=Image.new("RGBA",(W,H),(3,14,24,145))
    base=Image.alpha_composite(base.convert("RGBA"),dark).convert("RGB")
    def frame(n,t):
        im=base.copy().convert("RGBA");d=ImageDraw.Draw(im,"RGBA")
        alca=(1110,468); sf=(474,805); angel=(1390,246); marin=(1608,604)
        d.rounded_rectangle((44,42,750,144),radius=14,fill=(0,8,16,205))
        d.text((66,58),"THE BAY WAS THE FINAL BARRIER",font=font(36,True),fill=(248,241,226,255))
        d.text((68,106),"June 1962 • route possibilities, not proven paths",font=font(21),fill=(190,207,214,255))
        routes=[(sf,(244,164,75,245),8),(angel,(216,222,222,155),4),(marin,(216,222,222,155),4)]
        pulse=9+round(5*(.5+.5*math.sin(n/6)))
        d.ellipse((alca[0]-pulse,alca[1]-pulse,alca[0]+pulse,alca[1]+pulse),fill=(242,171,82,70),outline=(249,189,101,255),width=4)
        d.text((alca[0]+18,alca[1]-38),"ALCATRAZ",font=font(23,True),fill=(255,245,224,255))
        for i,(target,color,width) in enumerate(routes):
            q=max(0,min(1,(t-i*.10)/.76))
            # Curved route approximation with two segments for documentary-map motion.
            mid=((alca[0]+target[0])*.5+(-55 if i==0 else 45),(alca[1]+target[1])*.5-65)
            p1=(alca[0]+(mid[0]-alca[0])*min(1,q*2),alca[1]+(mid[1]-alca[1])*min(1,q*2))
            if q<=.5:
                d.line((alca[0],alca[1],p1[0],p1[1]),fill=color,width=width)
            else:
                d.line((alca[0],alca[1],mid[0],mid[1]),fill=color,width=width)
                q2=(q-.5)*2
                ex=mid[0]+(target[0]-mid[0])*q2;ey=mid[1]+(target[1]-mid[1])*q2
                d.line((mid[0],mid[1],ex,ey),fill=color,width=width)
            if q>.98:d.ellipse((target[0]-8,target[1]-8,target[0]+8,target[1]+8),fill=color)
        d.rectangle((48,H-102,W-48,H-42),fill=(0,7,13,205))
        d.text((72,H-88),"MAP BASE: RIGHTS-CHECKED WIKIMEDIA SOURCE • ROUTES: FBI/NPS SOURCE-GROUNDED • OUTCOME UNRESOLVED",font=font(21),fill=(223,229,229,245))
        return im.convert("RGB")
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

def make_reconstruction_clip(cell_image:Path,evidence_image:Path,out:Path,duration:float):
    cell=fit_crop(Image.open(cell_image)).convert("RGB")
    cell=ImageEnhance.Contrast(cell).enhance(1.08)
    evidence=Image.open(evidence_image).convert("RGB")
    evidence.thumbnail((650,520),Image.Resampling.LANCZOS)
    def frame(n,t):
        # Slow push on real source image, with forensic overlays rather than fake historical footage.
        scale=1.0+.06*t
        resized=cell.resize((round(W*scale),round(H*scale)),Image.Resampling.LANCZOS)
        x=max(0,(resized.width-W)//2+round(math.sin(t*math.pi)*22))
        y=max(0,(resized.height-H)//2)
        im=resized.crop((x,y,x+W,y+H)).convert("RGBA")
        d=ImageDraw.Draw(im,"RGBA")
        d.rectangle((0,0,W,H),fill=(2,8,13,78))
        d.rounded_rectangle((46,42,520,132),radius=12,fill=(0,5,10,210))
        d.text((68,58),"RECONSTRUCTION DIAGRAM",font=font(34,True),fill=(244,177,91,255))
        d.text((69,101),"source-grounded • not historical footage",font=font(19),fill=(205,215,217,255))
        # Evidence inset and animated route from cell vent toward service corridor.
        card=Image.new("RGBA",(evidence.width+28,evidence.height+28),(232,229,219,245))
        card.alpha_composite(evidence.convert("RGBA"),(14,14))
        cx=W-card.width-62;cy=190+round(math.sin(t*math.pi)*8)
        im.alpha_composite(card,(cx,cy))
        d.text((cx,cy-38),"DUMMY-HEAD EVIDENCE",font=font(21,True),fill=(240,235,222,255))
        start=(620,690);turn=(900,510);end=(1240,390)
        q=max(0,min(1,t/.78))
        if q<.55:
            u=q/.55;ex=start[0]+(turn[0]-start[0])*u;ey=start[1]+(turn[1]-start[1])*u
            d.line((start[0],start[1],ex,ey),fill=(244,171,84,245),width=10)
        else:
            d.line((start[0],start[1],turn[0],turn[1]),fill=(244,171,84,245),width=10)
            u=(q-.55)/.45;ex=turn[0]+(end[0]-turn[0])*u;ey=turn[1]+(end[1]-turn[1])*u
            d.line((turn[0],turn[1],ex,ey),fill=(244,171,84,245),width=10)
        d.ellipse((start[0]-10,start[1]-10,start[0]+10,start[1]+10),fill=(252,192,106,255))
        d.text((start[0]-88,start[1]+26),"CELL VENT",font=font(20,True),fill=(246,237,218,255))
        d.text((880,458),"UTILITY CORRIDOR",font=font(20,True),fill=(246,237,218,255))
        d.rectangle((46,H-96,W-46,H-42),fill=(0,6,11,205))
        d.text((68,H-83),"VISUALIZATION OF THE DOCUMENTED ESCAPE METHOD • NOT A CLAIM ABOUT THE MEN'S FINAL FATE",font=font(20),fill=(218,226,226,245))
        return im.convert("RGB")
    write_raw_video(out,duration,frame)

def synthesize_narration(out_wav:Path,out_srt:Path):
    from kokoro import KPipeline
    pipe=KPipeline(lang_code="a")
    rate=24000
    segments=[];timings=[];cursor=0
    gap=np.zeros(int(rate*.16),dtype=np.float32)
    for idx,(cid,text,source) in enumerate(NARRATION):
        chunks=[]
        for _,_,audio in pipe(text,voice="am_michael",speed=.98,split_pattern=r"\n+"):
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
        download(meta["url"],raw);polish_image(raw,final);time.sleep(.8)
        meta.update({"localPath":str(final),"sha256":sha256(final)})
        sources.append(meta)
    video_specs=[
      ("cell-doors-video","File:Alcatraz San Francisco's Prison The Sound of the Cell Doors.webm","alcatraz-cell-doors.webm"),
      ("island-video","File:Alcatraz.webm","alcatraz-island.webm"),
      ("isle-video","File:Alcatraz Isle (1).ogv","alcatraz-isle.ogv"),
    ]
    videos={}
    for label,title,filename in video_specs:
        meta=commons_exact_video(title,label)
        target=archive_dir/filename
        download(meta["url"],target,max_bytes=100*1024*1024)
        meta.update({"localPath":str(target),"sha256":sha256(target)})
        sources.append(meta);videos[label]=target;time.sleep(.7)
    (OUT/"sources.json").write_text(json.dumps({"schema":"open-media.sources.v3","items":sources},indent=2)+"\n")

    wav=OUT/"narration.wav";srt=OUT/"subtitles.srt"
    audio_dur,timings=synthesize_narration(wav,srt)
    # Twelve sub-5-second beats: real B-roll leads motion rather than Ken Burns alone.
    duration=max(48.0,min(78.0,audio_dur+.35))
    slot=duration/12.0
    src={x["id"]:Path(x["localPath"]) for x in sources if x["id"] not in videos}
    clips=[]
    plan=[
      ("broll",videos["island-video"],0.0),("broll",videos["cell-doors-video"],0.0),("archive",src["cells"],0.0),
      ("map",src["historic-map"],0.0),("broll",videos["isle-video"],0.0),("evidence",src["dummy-head"],0.0),
      ("reconstruction",(src["cellhouse"],src["dummy-head"]),0.0),("broll",videos["cell-doors-video"],7.5),
      ("archive",src["bay"],0.0),("map",src["historic-map"],0.0),("broll",videos["island-video"],8.5),
      ("archive",src["guard"],0.0)
    ]
    for i,(kind,asset,start) in enumerate(plan):
        clip=TMP/f"scene-{i+1:02}.mp4"
        if kind=="archive": make_archive_clip(asset,clip,slot,i,kind)
        elif kind=="broll": make_broll_clip(asset,clip,slot,start)
        elif kind=="map": make_map_clip(asset,clip,slot)
        elif kind=="evidence": make_evidence_clip(asset,clip,slot)
        else: make_reconstruction_clip(asset[0],asset[1],clip,slot)
        clips.append(clip)
    concat=TMP/"concat.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in clips)+"\n")
    silent=TMP/"silent.mp4"
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),
         "-c","copy","-t",f"{duration:.3f}",str(silent)],timeout=1800)

    master=OUT/"alcatraz-open-media-audition.mp4"
    srt_filter_path=str(srt).replace("\\","/").replace(":","\\\\:")
    subtitle_filter=f"subtitles='{srt_filter_path}':force_style='FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=42'"
    audio_mix="[1:a]volume=1.0[n];[2:a]atrim=start=1:end=4,asetpts=PTS-STARTPTS,volume=0.12,adelay=14500:all=1[s];[n][s]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:LRA=11:TP=-1.5[a]"
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-i",str(silent),"-i",str(wav),"-i",str(videos["cell-doors-video"]),
         "-filter_complex",audio_mix,"-vf",subtitle_filter,"-map","0:v:0","-map","[a]","-c:v","libx264","-preset","medium","-crf","18",
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000",
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
      "visualRoles":{"archive":3,"realBroll":5,"map":2,"evidence":1,"reconstructionDiagram":1},
      "rightsSafeArchiveCount":len(sources),
      "narration":{"engine":"Kokoro local CPU","voice":"am_michael","durationSec":audio_dur,"humanNaturalnessReview":"PENDING"},
      "benchmark":{"id":"youtube:XO1-4FH1X1I","sideBySideStatus":"PENDING"},
      "q9Status":"FAIL_UNTIL_HUMAN_REVIEW",
      "knownGap":"No local AI-video reconstruction yet; this revision uses three distinct rights-checked Alcatraz motion sources, a real map-backed route treatment, and a source-image reconstruction diagram."
    }
    (OUT/"qa.json").write_text(json.dumps(qa,indent=2)+"\n")
    print(json.dumps(qa,indent=2))

if __name__=="__main__":
    main()
