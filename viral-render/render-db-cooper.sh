#!/usr/bin/env bash
set -euo pipefail
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
REG='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
W=1280
H=720
FPS=24
DUR=25
mkdir -p viral-render/work/db renders

asset() {
  curl -L --fail --retry 3 "$1" -o "$2"
}

asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/FBI-CompositeB-DBCooper.jpg' viral-render/work/db/sketch.jpg
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/July%202016%20D.B.%20Cooper%20Plane%20Ticket%20(28379315406).jpg' viral-render/work/db/ticket.jpg
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/Money%20stolen%20by%20D.%20B.%20Cooper.jpg' viral-render/work/db/money.jpg
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/DB%20Cooper%20Wanted%20Poster.jpg' viral-render/work/db/wanted.jpg
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/DB-Cooper-age-progress.jpg' viral-render/work/db/age.jpg
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/John%20Bartmann%20-%20broken-suspense-master.ogg' viral-render/work/db/music.ogg

python3 -m pip install --quiet piper-tts
piper --model en_US-ryan-high --output_file viral-render/work/db/narration.wav < viral-render/db-cooper-script.txt
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 viral-render/work/db/narration.wav

still_scene() {
  local IMG="$1"; local TITLE="$2"; local SUB="$3"; local OUT="$4"
  ffmpeg -y -loop 1 -framerate 1 -i "$IMG" -t "$DUR" -filter_complex "
  [0:v]split=2[bg][fg];
  [bg]scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},boxblur=30:2,eq=brightness=-0.20:saturation=0.55[bg2];
  [fg]scale=1000:590:force_original_aspect_ratio=decrease[fg2];
  [bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1,zoompan=z='min(zoom+0.00035,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=600:s=${W}x${H}:fps=${FPS},drawbox=x=0:y=0:w=${W}:h=92:color=black@0.72:t=fill,drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=44:x=46:y=24,drawbox=x=0:y=600:w=${W}:h=120:color=black@0.72:t=fill,drawtext=fontfile=${REG}:text='${SUB}':fontcolor=white:fontsize=31:x=46:y=635,fade=t=in:st=0:d=0.8,fade=t=out:st=24.0:d=1.0[v]" -map '[v]' -an -c:v libx264 -preset veryfast -crf 27 -pix_fmt yuv420p "$OUT"
}

card_scene() {
  local TITLE="$1"; local LINE1="$2"; local LINE2="$3"; local OUT="$4"
  ffmpeg -y -f lavfi -i "color=c=0x090D12:s=${W}x${H}:r=${FPS}:d=${DUR}" -vf "noise=alls=5:allf=t+u,drawgrid=width=80:height=80:thickness=1:color=white@0.035,drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=170+8*sin(t*0.9),drawtext=fontfile=${REG}:text='${LINE1}':fontcolor=0xD6DCE5:fontsize=39:x=(w-text_w)/2:y=320,drawtext=fontfile=${REG}:text='${LINE2}':fontcolor=0x99A4B3:fontsize=31:x=(w-text_w)/2:y=390,fade=t=in:st=0:d=0.8,fade=t=out:st=24:d=1" -an -c:v libx264 -preset veryfast -crf 27 -pix_fmt yuv420p "$OUT"
}

map_scene() {
  local TITLE="$1"; local SUB="$2"; local OUT="$3"; local MODE="$4"
  if [ "$MODE" = 'north' ]; then
    XEXPR="170+24*t"; YEXPR="525-10*t"
    FROM='PORTLAND'; TO='SEATTLE'
  else
    XEXPR="350+22*t"; YEXPR="230+14*t"
    FROM='SEATTLE'; TO='RENO'
  fi
  ffmpeg -y -f lavfi -i "color=c=0x07101A:s=${W}x${H}:r=${FPS}:d=${DUR}" -vf "noise=alls=3:allf=t+u,drawgrid=width=64:height=64:thickness=1:color=0x5B718A@0.12,drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=54:x=45:y=35,drawtext=fontfile=${REG}:text='${SUB}':fontcolor=0xB9C3CF:fontsize=28:x=47:y=105,drawtext=fontfile=${FONT}:text='${FROM}':fontcolor=0xB0BAC6:fontsize=34:x=130:y=555,drawtext=fontfile=${FONT}:text='${TO}':fontcolor=0xB0BAC6:fontsize=34:x=920:y=130,drawtext=fontfile=${FONT}:text='FLIGHT 305':fontcolor=0xF0F2F5:fontsize=34:borderw=2:bordercolor=black:x='${XEXPR}':y='${YEXPR}',drawtext=fontfile=${REG}:text='●':fontcolor=white:fontsize=42:x='${XEXPR}-34':y='${YEXPR}-5',fade=t=in:st=0:d=0.8,fade=t=out:st=24:d=1" -an -c:v libx264 -preset veryfast -crf 27 -pix_fmt yuv420p "$OUT"
}

still_scene viral-render/work/db/sketch.jpg 'THE MAN WITH NO NAME' 'FBI composite sketch • November 1971' viral-render/work/db/s01.mp4
still_scene viral-render/work/db/ticket.jpg 'ONE-WAY TO SEATTLE' 'A cash ticket purchased under the name Dan Cooper' viral-render/work/db/s02.mp4
card_scene '3:00 PM' 'A note. A briefcase. A quiet threat.' 'The hijacking begins after takeoff.' viral-render/work/db/s03.mp4
card_scene '$200,000' 'FOUR PARACHUTES' 'Cooper gives the crew his demands.' viral-render/work/db/s04.mp4
map_scene 'FLIGHT 305' 'Portland to Seattle • authorities assemble the ransom' viral-render/work/db/s05.mp4 north
card_scene 'THE EXCHANGE' '36 passengers walk free in Seattle.' 'Cooper keeps the money, parachutes and part of the crew.' viral-render/work/db/s06.mp4
map_scene 'INTO THE NIGHT' 'A low, slow southbound flight • rear stairs deployed' viral-render/work/db/s07.mp4 south
still_scene viral-render/work/db/wanted.jpg 'NORJAK' 'The FBI launches one of its most famous manhunts.' viral-render/work/db/s08.mp4
still_scene viral-render/work/db/sketch.jpg 'WHAT DID HE LEAVE?' 'A tie. Witness memories. Fragments of evidence.' viral-render/work/db/s09.mp4
still_scene viral-render/work/db/money.jpg '$5,800 FOUND' '1980 • ransom bills appear along the Columbia River.' viral-render/work/db/s10.mp4
card_scene 'DID HE SURVIVE?' 'Night. Bad weather. Business shoes.' 'A dangerous jump with a non-steerable parachute.' viral-render/work/db/s11.mp4
still_scene viral-render/work/db/age.jpg 'THE FACE THAT AGED' 'Investigators imagined how Cooper might look years later.' viral-render/work/db/s12.mp4
card_scene '800+ SUSPECTS' 'Hundreds of leads. No definitive identification.' 'Some theories were compelling. None closed the case.' viral-render/work/db/s13.mp4
card_scene 'DAN COOPER' 'The hijacker never called himself D.B.' 'The famous initials came from an early press mistake.' viral-render/work/db/s14.mp4
still_scene viral-render/work/db/ticket.jpg '45 YEARS OF NORJAK' 'In 2016 the FBI redirected active resources from the case.' viral-render/work/db/s15.mp4
still_scene viral-render/work/db/sketch.jpg 'STILL UNSOLVED' 'Who was he? Did he survive? Where did the money go?' viral-render/work/db/s16.mp4
card_scene 'HE STEPPED INTO THE DARKNESS' 'And more than half a century later...' 'the final scene is still missing.' viral-render/work/db/s17.mp4

: > viral-render/work/db/list.txt
for i in $(seq -w 1 17); do echo "file 's${i}.mp4'" >> viral-render/work/db/list.txt; done
(cd viral-render/work/db && ffmpeg -y -f concat -safe 0 -i list.txt -c copy visual.mp4)

ffmpeg -y -i viral-render/work/db/narration.wav -stream_loop -1 -i viral-render/work/db/music.ogg -filter_complex "[0:a]volume=1.0[n];[1:a]volume=0.085,highpass=f=60,lowpass=f=10000[m];[n][m]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=0.96[a]" -map '[a]' -c:a aac -b:a 160k viral-render/work/db/audio.m4a

ffmpeg -y -i viral-render/work/db/visual.mp4 -i viral-render/work/db/audio.m4a -map 0:v -map 1:a -c:v copy -c:a copy -shortest -movflags +faststart renders/db-cooper-longform-sample-v1.mp4
ffprobe -v error -show_entries stream=codec_name,width,height -show_entries format=duration,size -of default=noprint_wrappers=1 renders/db-cooper-longform-sample-v1.mp4
ffmpeg -y -i renders/db-cooper-longform-sample-v1.mp4 -vf "fps=0.025,scale=320:180,tile=4x3" -frames:v 1 -q:v 5 renders/db-cooper-longform-sample-v1-contact.jpg
cat > renders/db-cooper-longform-sample-v1-sources.txt <<'EOF'
FACT SOURCES
FBI: D.B. Cooper Hijacking — https://www.fbi.gov/history/cases-and-criminals/db-cooper-hijacking
FBI: D.B. Cooper Plane Ticket — https://www.fbi.gov/history/artifacts/d-b-cooper-plane-ticket
FBI: 2016 investigation update — https://www.fbi.gov/contact-us/field-offices/seattle/news/press-releases/update-on-investigation-of-1971-hijacking-by-d.b.-cooper

VISUALS — PUBLIC DOMAIN, U.S. FEDERAL GOVERNMENT
FBI-CompositeB-DBCooper.jpg — Wikimedia Commons
July 2016 D.B. Cooper Plane Ticket (28379315406).jpg — Wikimedia Commons
Money stolen by D. B. Cooper.jpg — Wikimedia Commons
DB Cooper Wanted Poster.jpg — Wikimedia Commons
DB-Cooper-age-progress.jpg — Wikimedia Commons

MUSIC
John Bartmann - broken-suspense-master.ogg — CC0 1.0 — Wikimedia Commons

NARRATION
Locally synthesized with open-source Piper TTS using the en_US-ryan-high model.

EDIT
Original script, animated route graphics, typography, timeline cards, Ken Burns motion, sound mix and assembly by the ALOS video pipeline.
EOF
