#!/usr/bin/env bash
set -euo pipefail
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
REG='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
W=1920
H=1080
FPS=24
DUR=10.7
WORK='viral-render/work/dbv2'
OUT='renders/db-cooper-longform-v2.mp4'
SRT='renders/db-cooper-longform-v2.srt'
mkdir -p "$WORK/voice" renders

asset(){ curl -L --fail --retry 3 "$1" -o "$2"; }

# Rights-cleared evidence and period visuals.
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/FBI-CompositeB-DBCooper.jpg' "$WORK/sketch.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/July%202016%20D.B.%20Cooper%20Plane%20Ticket%20(28379315406).jpg' "$WORK/ticket.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/Money%20stolen%20by%20D.%20B.%20Cooper.jpg' "$WORK/money.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/DB%20Cooper%20Wanted%20Poster.jpg' "$WORK/wanted.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/DB-Cooper-age-progress.jpg' "$WORK/age.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/Richard%20McCoy%2C%20Jr..jpg' "$WORK/mccoy.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/UDF-Boeing-727-ground.png' "$WORK/727ground.png"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/B-727%20in%20flight%20during%20vortex%20study%20with%20wingtip%20smoke%20generators%20ECN-3831.jpg' "$WORK/727flight.jpg"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/D.%20B.%20Cooper%20jump.gif' "$WORK/jump.gif"
asset 'https://commons.wikimedia.org/wiki/Special:Redirect/file/John%20Bartmann%20-%20broken-suspense-master.ogg' "$WORK/music.ogg"

# Preserve the V1 story and voice character that tested well.
python3 -m pip install --quiet piper-tts
python3 -m piper.download_voices --data-dir "$WORK/voice" en_US-ljspeech-high
python3 -m piper --data-dir "$WORK/voice" -m en_US-ljspeech-high -f "$WORK/narration.wav" -- "$(cat viral-render/db-cooper-script.txt)"
NARR_DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$WORK/narration.wav")
python3 viral-render/db-cooper-v2-subtitles.py viral-render/db-cooper-script.txt "$NARR_DUR" "$SRT"

img_scene(){
  local IMG="$1" TITLE="$2" SUB="$3" OUTFILE="$4" ZOOM="${5:-in}"
  if [ "$ZOOM" = 'out' ]; then Z="max(1.16-0.00062*on,1.02)"; else Z="min(1.02+0.00062*on,1.16)"; fi
  ffmpeg -y -loop 1 -framerate 1 -i "$IMG" -t "$DUR" -filter_complex "
    [0:v]split=2[bg][fg];
    [bg]scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},boxblur=35:3,eq=brightness=-0.24:saturation=0.52[bg2];
    [fg]scale=1580:850:force_original_aspect_ratio=decrease[fg2];
    [bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1,zoompan=z='${Z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=257:s=${W}x${H}:fps=${FPS},
    drawbox=x=0:y=0:w=${W}:h=122:color=black@0.72:t=fill,
    drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=57:x=65:y=31,
    drawbox=x=0:y=930:w=${W}:h=150:color=black@0.68:t=fill,
    drawtext=fontfile=${REG}:text='${SUB}':fontcolor=white:fontsize=35:x=65:y=970,
    fade=t=in:st=0:d=.35,fade=t=out:st=10.25:d=.45[v]" \
    -map '[v]' -an -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p "$OUTFILE"
}

card_scene(){
  local TITLE="$1" L1="$2" L2="$3" OUTFILE="$4" ACCENT="${5:-0xD6DCE5}"
  ffmpeg -y -f lavfi -i "color=c=0x080C12:s=${W}x${H}:r=${FPS}:d=${DUR}" -vf "
    noise=alls=4:allf=t+u,drawgrid=width=96:height=96:thickness=1:color=white@0.025,
    drawbox=x=0:y=0:w=18:h=${H}:color=${ACCENT}@0.85:t=fill,
    drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=94:x=(w-text_w)/2:y=300+8*sin(t*0.9),
    drawtext=fontfile=${REG}:text='${L1}':fontcolor=0xE6E9EE:fontsize=46:x=(w-text_w)/2:y=510,
    drawtext=fontfile=${REG}:text='${L2}':fontcolor=0xAEB8C5:fontsize=36:x=(w-text_w)/2:y=585,
    fade=t=in:st=0:d=.3,fade=t=out:st=10.2:d=.5" \
    -an -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p "$OUTFILE"
}

map_scene(){
  local TITLE="$1" SUB="$2" OUTFILE="$3" MODE="$4"
  if [ "$MODE" = 'north' ]; then
    X="260+52*t"; Y="780-31*t"; FROM='PORTLAND'; TO='SEATTLE'
  else
    X="560+60*t"; Y="300+36*t"; FROM='SEATTLE'; TO='RENO'
  fi
  ffmpeg -y -f lavfi -i "color=c=0x07111D:s=${W}x${H}:r=${FPS}:d=${DUR}" -vf "
    noise=alls=3:allf=t+u,drawgrid=width=78:height=78:thickness=1:color=0x7EA1C4@0.10,
    drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=72:x=70:y=65,
    drawtext=fontfile=${REG}:text='${SUB}':fontcolor=0xC2CBD6:fontsize=34:x=74:y=158,
    drawtext=fontfile=${FONT}:text='${FROM}':fontcolor=0xD7DEE7:fontsize=44:x=190:y=850,
    drawtext=fontfile=${FONT}:text='${TO}':fontcolor=0xD7DEE7:fontsize=44:x=1510:y=190,
    drawtext=fontfile=${REG}:text='•':fontcolor=0xFFFFFF:fontsize=82:x='${X}':y='${Y}',
    drawtext=fontfile=${FONT}:text='FLIGHT 305':fontcolor=0xFFFFFF:fontsize=38:borderw=2:bordercolor=black:x='${X}+55':y='${Y}+18',
    drawbox=x=110:y=915:w=1700:h=4:color=0x86A9CE@0.35:t=fill,
    fade=t=in:st=0:d=.3,fade=t=out:st=10.2:d=.5" \
    -an -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p "$OUTFILE"
}

jump_scene(){
  local TITLE="$1" SUB="$2" OUTFILE="$3"
  ffmpeg -y -ignore_loop 0 -i "$WORK/jump.gif" -t "$DUR" -filter_complex "
    [0:v]fps=${FPS},scale=1640:900:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=0x090D12,
    drawbox=x=0:y=0:w=${W}:h=122:color=black@0.72:t=fill,
    drawtext=fontfile=${FONT}:text='${TITLE}':fontcolor=white:fontsize=60:x=65:y=31,
    drawbox=x=0:y=930:w=${W}:h=150:color=black@0.68:t=fill,
    drawtext=fontfile=${REG}:text='${SUB}':fontcolor=white:fontsize=35:x=65:y=970,
    fade=t=in:st=0:d=.25,fade=t=out:st=10.2:d=.45[v]" \
    -map '[v]' -an -c:v libx264 -preset veryfast -crf 21 -pix_fmt yuv420p "$OUTFILE"
}

evidence_scene(){
  local OUTFILE="$1"
  ffmpeg -y -f lavfi -i "color=c=0x0A0E14:s=${W}x${H}:r=${FPS}:d=${DUR}" \
    -loop 1 -i "$WORK/sketch.jpg" -loop 1 -i "$WORK/ticket.jpg" -loop 1 -i "$WORK/money.jpg" -loop 1 -i "$WORK/wanted.jpg" -t "$DUR" -filter_complex "
    [1:v]scale=560:410:force_original_aspect_ratio=decrease,pad=580:430:(ow-iw)/2:(oh-ih)/2:color=white[a];
    [2:v]scale=560:410:force_original_aspect_ratio=decrease,pad=580:430:(ow-iw)/2:(oh-ih)/2:color=white[b];
    [3:v]scale=560:410:force_original_aspect_ratio=decrease,pad=580:430:(ow-iw)/2:(oh-ih)/2:color=white[c];
    [4:v]scale=560:410:force_original_aspect_ratio=decrease,pad=580:430:(ow-iw)/2:(oh-ih)/2:color=white[d];
    [0:v][a]overlay=120:160[x1];[x1][b]overlay=720:160[x2];[x2][c]overlay=1320:160[x3];[x3][d]overlay=720:600,
    drawtext=fontfile=${FONT}:text='THE EVIDENCE BOARD':fontcolor=white:fontsize=66:x=70:y=54,
    drawtext=fontfile=${REG}:text='Four clues. Decades of questions. No definitive identity.':fontcolor=0xCBD3DD:fontsize=33:x=72:y=990,
    fade=t=in:st=0:d=.35,fade=t=out:st=10.2:d=.45[v]" \
    -map '[v]' -an -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p "$OUTFILE"
}

# 32 faster visual beats instead of 17 long 25-second holds.
card_scene 'NOVEMBER 24, 1971' 'A man boards a plane under a false name.' 'Hours later, he will disappear into the night.' "$WORK/s01.mp4" 0xB9C7D8
img_scene "$WORK/727flight.jpg" 'THE FLIGHT' 'A Boeing 727 becomes the stage for an unsolved mystery.' "$WORK/s02.mp4"
img_scene "$WORK/ticket.jpg" 'ONE-WAY TO SEATTLE' 'Cash ticket. Name: Dan Cooper.' "$WORK/s03.mp4" out
img_scene "$WORK/sketch.jpg" 'THE MAN WITH NO NAME' 'Witnesses remember the suit, tie and calm manner.' "$WORK/s04.mp4"
card_scene 'SEAT 18C' 'Near the rear of the cabin.' 'A bourbon and soda. Then a note.' "$WORK/s05.mp4" 0x8AA5C1
card_scene 'I HAVE A BOMB' 'The flight attendant reads the message.' 'Cooper quietly opens an attaché case.' "$WORK/s06.mp4" 0xB96D6D
card_scene '$200,000' 'FOUR PARACHUTES' 'A fuel truck waiting in Seattle.' "$WORK/s07.mp4" 0xB9A36D
img_scene "$WORK/money.jpg" 'THE RANSOM' 'Serial numbers are recorded before the cash is delivered.' "$WORK/s08.mp4"
map_scene 'FLIGHT 305' 'Portland to Seattle • authorities race to assemble the ransom' "$WORK/s09.mp4" north
card_scene 'THE EXCHANGE' '36 passengers walk free.' 'Cooper keeps the money, parachutes and part of the crew.' "$WORK/s10.mp4" 0x6F927D
img_scene "$WORK/727ground.png" 'WHY A 727?' 'Its rear airstair could be lowered in flight.' "$WORK/s11.mp4" out
map_scene 'SOUTHBOUND' 'Low altitude • slow speed • cabin unpressurized' "$WORK/s12.mp4" south
card_scene '8:00 PM' 'Darkness. Rain. Rough terrain.' 'The rear stairs deploy somewhere over the Northwest.' "$WORK/s13.mp4" 0x667A93
jump_scene 'THE JUMP' 'A reenactment of the rear stair deployment and escape.' "$WORK/s14.mp4"
card_scene 'RENO' 'The plane lands.' 'Cooper is gone. So is the money.' "$WORK/s15.mp4" 0x6B7180
img_scene "$WORK/wanted.jpg" 'NORJAK' 'The FBI launches a massive manhunt.' "$WORK/s16.mp4"
evidence_scene "$WORK/s17.mp4"
card_scene 'WHAT HE LEFT' 'A clip-on tie. Witness memories.' 'Fingerprints and cigarette butts that never solved the case.' "$WORK/s18.mp4" 0x7D8896
img_scene "$WORK/sketch.jpg" 'THE FACE' 'People sitting feet away helped build the famous composite.' "$WORK/s19.mp4" out
card_scene '1980' 'Nine years after the hijacking...' 'A child finds decaying $20 bills by the Columbia River.' "$WORK/s20.mp4" 0x7D9B87
img_scene "$WORK/money.jpg" '$5,800 FOUND' 'The serial numbers match the Cooper ransom.' "$WORK/s21.mp4" out
map_scene 'THE RIVER MYSTERY' 'How did ransom money reach the Columbia River bank?' "$WORK/s22.mp4" south
card_scene 'DID HE SURVIVE?' 'Night. Bad weather. Dress shoes.' 'A dangerous jump with a non-steerable parachute.' "$WORK/s23.mp4" 0xA37979
img_scene "$WORK/727flight.jpg" 'THE CONDITIONS' 'Wind, darkness and forest below made survival uncertain.' "$WORK/s24.mp4" out
card_scene 'NO BODY' 'NO CONFIRMED PARACHUTE' 'And no definitive identification.' "$WORK/s25.mp4" 0x78879A
img_scene "$WORK/mccoy.jpg" 'RICHARD McCOY' 'A similar 1972 hijacking made him a major suspect.' "$WORK/s26.mp4"
card_scene 'RULED OUT' 'The FBI investigated McCoy.' 'Witness differences and other evidence did not fit.' "$WORK/s27.mp4" 0x7C8794
card_scene '800+ SUSPECTS' 'Thousands of hours of investigation.' 'No name ever closed the case.' "$WORK/s28.mp4" 0x8F7C67
card_scene 'DAN COOPER' 'He never called himself D.B.' 'Those initials came from an early reporting mistake.' "$WORK/s29.mp4" 0x7C8391
img_scene "$WORK/age.jpg" 'THE FACE THAT AGED' 'Investigators imagined how Cooper might look years later.' "$WORK/s30.mp4"
card_scene '2016' 'The FBI redirects active investigative resources.' 'Physical evidence remains preserved.' "$WORK/s31.mp4" 0x6F7F8F
card_scene 'THE FINAL SCENE IS MISSING' 'Who was he? Did he survive?' 'Where did the rest of the ransom go?' "$WORK/s32.mp4" 0x8795A6

: > "$WORK/list.txt"
for i in $(seq -w 1 32); do echo "file 's${i}.mp4'" >> "$WORK/list.txt"; done
(cd "$WORK" && ffmpeg -y -f concat -safe 0 -i list.txt -c copy visual.mp4)

# Narration remains foreground; music ducks underneath and fades gently.
ffmpeg -y -i "$WORK/narration.wav" -stream_loop -1 -i "$WORK/music.ogg" -filter_complex "
[0:a]volume=1.0,highpass=f=65[n];
[1:a]volume=0.075,highpass=f=70,lowpass=f=9500,afade=t=in:st=0:d=3[m];
[n][m]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=0.96[a]" \
-map '[a]' -c:a aac -b:a 160k "$WORK/audio.m4a"

# Burn clean documentary subtitles while also preserving the separate SRT file.
ffmpeg -y -i "$WORK/visual.mp4" -i "$WORK/audio.m4a" \
-vf "subtitles=${SRT}:force_style='FontName=DejaVu Sans,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H78000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=48,Alignment=2'" \
-map 0:v -map 1:a -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a copy -shortest -movflags +faststart "$OUT"

ffprobe -v error -show_entries stream=codec_name,width,height -show_entries format=duration,size -of default=noprint_wrappers=1 "$OUT"
ffmpeg -y -i "$OUT" -vf "fps=0.03,scale=480:270,tile=4x3" -frames:v 1 -q:v 4 renders/db-cooper-longform-v2-contact.jpg

cat > renders/db-cooper-longform-v2-sources.txt <<'EOF'
FACT SOURCES
FBI: D.B. Cooper Hijacking
FBI: D.B. Cooper Plane Ticket
FBI: 2016 investigation update

PUBLIC-DOMAIN / REUSABLE VISUALS
FBI composite sketch — U.S. federal government / public domain
D.B. Cooper plane ticket — U.S. federal government / public domain
Ransom money photo — U.S. federal government / public domain
Wanted poster — U.S. federal government / public domain
Age-progression image — U.S. federal government / public domain
Richard McCoy Jr. image — FBI / public domain
UDF Boeing 727 ground image — NASA / public domain
B-727 vortex-study flight image — NASA / public domain
D. B. Cooper jump.gif — derivative by Furfur of work by Anynobody — CC BY 2.5; attribution required

MUSIC
John Bartmann - broken-suspense-master.ogg — CC0 1.0

NARRATION
Original script from V1, locally synthesized with Piper en_US-ljspeech-high. Underlying LJSpeech dataset is public domain.

V2 EDIT
32 faster visual beats; 1920x1080; evidence board; animated routes; Boeing 727 visuals; jump reenactment; timed documentary subtitles; stronger opening; upgraded typography, motion and audio mix.
EOF
