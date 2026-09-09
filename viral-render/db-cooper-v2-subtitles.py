#!/usr/bin/env python3
import re, sys
from pathlib import Path

script = Path(sys.argv[1]).read_text(encoding='utf-8').strip()
duration = float(sys.argv[2])
out = Path(sys.argv[3])

# Split into readable caption chunks. Keep punctuation so pauses can be weighted.
sentences = re.split(r'(?<=[.!?])\s+', script.replace('\n', ' '))
chunks = []
for sentence in sentences:
    words = sentence.split()
    if not words:
        continue
    current = []
    for w in words:
        current.append(w)
        if len(current) >= 10 or (len(current) >= 6 and re.search(r'[,;:]$', w)):
            chunks.append(' '.join(current))
            current = []
    if current:
        chunks.append(' '.join(current))

weights = []
for c in chunks:
    wc = len(c.split())
    pause = 0.0
    if c.endswith(('.', '?', '!')):
        pause += 2.0
    elif c.endswith((',', ';', ':')):
        pause += 0.7
    weights.append(wc + pause)

scale = duration / sum(weights)

def stamp(t):
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

cur = 0.0
lines = []
for i, (c, w) in enumerate(zip(chunks, weights), 1):
    seg = w * scale
    start = cur
    end = min(duration, cur + seg)
    lines += [str(i), f"{stamp(start)} --> {stamp(end)}", c, ""]
    cur = end

out.write_text('\n'.join(lines), encoding='utf-8')
