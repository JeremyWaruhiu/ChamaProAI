"""Stack each conversation's two recordings side by side, lay the bot's cached audio at the
moments in its timeline, add the caption bar, and join the conversations into one H.264/AAC mp4.
video.mjs runs it; on its own, to compose again from recordings already made:

    python tests/browser/capture/compose.py <scratch>/video <out.mp4> wanjiru njeri
"""
import json
import subprocess
import sys
from pathlib import Path

WORK, OUT, SLUGS = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:] or ["wanjiru", "njeri"]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MEMBER_W, PRESENT_W, H, BAR, GAP = 500, 960, 1080, 80, 4
W = MEMBER_W + GAP + PRESENT_W


def segment(slug: str) -> Path:
    tl = json.loads((WORK / slug / "timeline.json").read_text())
    t0 = tl["tReady"]
    length = (tl["tEnd"] - t0) / 1000
    sm, sp = (t0 - tl["t0Member"]) / 1000, (t0 - tl["t0Present"]) / 1000
    inputs = ["-i", tl["memberVideo"], "-i", tl["presentVideo"]]
    for a in tl["audio"]:
        inputs += ["-i", a["file"]]
    f = [f"[0:v]trim=start={sm:.3f},setpts=PTS-STARTPTS,fps=25,scale={MEMBER_W}:{H}:flags=lanczos,setsar=1,"
         f"pad={MEMBER_W + GAP}:{H}:0:0:color=0x0f3324[m]",
         f"[1:v]trim=start={sp:.3f},setpts=PTS-STARTPTS,fps=25,scale={PRESENT_W}:{H}:flags=lanczos,setsar=1[p]",
         f"[m][p]hstack=inputs=2,pad={W}:{H + BAR}:0:0:color=0x0f3324[v0]"]
    caps = tl["captions"]
    last = "v0"
    for i, c in enumerate(caps):
        start = max(0.0, (c["t"] - t0) / 1000)
        end = (caps[i + 1]["t"] - t0) / 1000 if i + 1 < len(caps) else length + 1
        txt = WORK / slug / f"caption-{i}.txt"
        txt.write_text(c["text"], encoding="utf-8")
        f.append(f"[{last}]drawtext=fontfile={FONT}:textfile={txt}:fontsize=34:fontcolor=white:"
                 f"x=(w-text_w)/2:y={H}+({BAR}-text_h)/2:enable='between(t,{start:.3f},{end:.3f})'[v{i + 1}]")
        last = f"v{i + 1}"
    mix = []
    for k, a in enumerate(tl["audio"]):
        ms = max(0, round(a["start"] - t0))
        f.append(f"[{k + 2}:a]aresample=44100,adelay={ms}:all=1[a{k}]")
        mix.append(f"[a{k}]")
    f.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,apad,atrim=0:{length:.3f}[aout]")
    out = WORK / f"{slug}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(f),
           "-map", f"[{last}]", "-map", "[aout]", "-t", f"{length:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", "25",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)
    print(slug, f"{length:.1f} s, {len(tl['audio'])} lines, {len(caps)} captions")
    return out


parts = [segment(s) for s in SLUGS]
listing = WORK / "concat.txt"
listing.write_text("".join(f"file '{p}'\n" for p in parts))
OUT.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                "-c", "copy", "-movflags", "+faststart", str(OUT)], check=True)
size = OUT.stat().st_size
print(f"wrote {OUT}: {size / 1e6:.1f} MB")
