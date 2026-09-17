#!/usr/bin/env python3
"""Resolve: renders the Drayrates data-layer motif from any image or video.

States
  field   dim two-digit numbers whose brightness follows the source (data nobody can read)
  dither  ordered-dither pixel blocks in the lime ramp; a shape emerges (partial legibility)
  clear   the source itself, graded dark (legibility = transparency)

Modes
  --state field|dither|clear|all   render one state (or every state) for the whole input
  --state sequence                 animate field -> dither -> clear across the timeline

Examples
  python3 resolve.py photo.jpg out/                       # field + dither + clear stills
  python3 resolve.py clip.mp4  out/ --state dither        # whole clip as dither
  python3 resolve.py clip.mp4  out/ --state sequence --start 1 --end 5
  python3 resolve.py photo.jpg out/ --state sequence --seconds 4
"""
import argparse, random, shutil, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
FONT = HERE / "fonts" / "JetBrainsMono-Medium.ttf"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}

def hex_rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def ramp_lut(lime, steps=256):
    """Luminance 0..255 -> RGB along near-black -> olive -> lime."""
    stops = [(0.0, (0, 0, 0)), (0.12, (14, 16, 10)), (0.45, (70, 78, 48)), (0.75, (150, 175, 90)), (1.0, hex_rgb(lime))]
    lut = np.zeros((steps, 3), dtype=np.uint8)
    for i in range(steps):
        t = i / (steps - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1:
                k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                lut[i] = [round(a + (b - a) * k) for a, b in zip(c0, c1)]; break
    return lut

BAYER8 = (np.array([[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26], [12, 44, 4, 36, 14, 46, 6, 38],
                    [60, 28, 52, 20, 62, 30, 54, 22], [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
                    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]) + 0.5) / 64.0

def luminance(frame, w, h, levels=(2, 99.5), blur=0.0):
    src = frame.convert("L").resize((w, h), Image.LANCZOS)
    if blur: src = src.filter(ImageFilter.GaussianBlur(blur))
    arr = np.asarray(src, dtype=np.float32)
    if levels:
        lo, hi = np.percentile(arr, levels); arr = np.clip((arr - lo) / max(hi - lo, 1), 0, 1)
    else:
        arr = arr / 255.0
    return arr

# ---------- state: clear ----------
def state_clear(frame, W, H, gamma=1.15, lift=0.0):
    im = frame.convert("RGB").resize((W, H), Image.LANCZOS)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = np.clip(arr ** gamma, 0, 1) * (1 - lift) + lift * 0.02
    return Image.fromarray((arr * 255).astype(np.uint8))

# ---------- state: field ----------
class Field:
    def __init__(self, W, H, cols, lime, gamma=1.6, floor=0.04, seed=7):
        self.W, self.H, self.cols = W, H, cols
        self.cw = W / cols; self.ch = self.cw * 0.9; self.rows = int(H / self.ch)
        self.font = ImageFont.truetype(str(FONT), size=max(6, int(self.ch * 0.62)))
        self.gw = self.font.getlength("00"); self.gamma, self.floor = gamma, floor
        self.lut = ramp_lut(lime); rng = random.Random(seed)
        self.nums = [[rng.randint(0, 99) for _ in range(cols)] for _ in range(self.rows)]
        self.rng = rng
    def reroll(self, rate):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.rng.random() < rate: self.nums[r][c] = self.rng.randint(0, 99)
    def render(self, frame, gain=1.0):
        lum = luminance(frame, self.cols, self.rows, blur=0.6) ** self.gamma * gain
        out = Image.new("RGB", (self.W, self.H), (0, 0, 0)); d = ImageDraw.Draw(out)
        for r in range(self.rows):
            for c in range(self.cols):
                v = float(lum[r, c])
                if v < self.floor: continue
                col = tuple(int(x) for x in self.lut[min(255, int(v * 255))])
                d.text((c * self.cw + (self.cw - self.gw) / 2, r * self.ch + self.ch * 0.12), f"{self.nums[r][c]:02d}", font=self.font, fill=col)
        return out

# ---------- state: dither ----------
def state_dither(frame, W, H, block, lime, levels_n=4, gamma=1.2, lut=None):
    """Ordered (Bayer 8x8) dither on a block grid, quantized to a few lime-ramp tones."""
    gw, gh = W // block, H // block
    lum = luminance(frame, gw, gh, blur=0.4) ** gamma
    tile = np.tile(BAYER8, (gh // 8 + 1, gw // 8 + 1))[:gh, :gw]
    q = np.floor(lum * (levels_n - 1) + tile) / (levels_n - 1)   # threshold with Bayer noise
    q = np.clip(q, 0, 1)
    lut = lut if lut is not None else ramp_lut(lime)
    rgb = lut[(q * 255).astype(np.uint8)]
    small = Image.fromarray(rgb, "RGB")
    return small.resize((gw * block, gh * block), Image.NEAREST).resize((W, H), Image.NEAREST)

def reveal_mask(k, W, H, block):
    """Block-wise Bayer threshold mask (H, W, 1): cells whose threshold < k are revealed."""
    gh, gw = -(-H // block), -(-W // block)
    thr = np.tile(BAYER8, (gh // 8 + 1, gw // 8 + 1))[:gh, :gw]
    return np.kron((thr < k).astype(np.float32), np.ones((block, block), np.float32))[:H, :W][..., None]

# ---------- sequence: field -> dither -> clear ----------
def sequence_frame(frame, t, field, W, H, block, lime, lut):
    """t in 0..1. 0-0.35 field brightens; 0.35-0.65 field dissolves into dither; 0.65-1 dither resolves to clear."""
    if t < 0.35:
        return field.render(frame, gain=0.35 + 0.65 * (t / 0.35))
    dith = state_dither(frame, W, H, block, lime, lut=lut)
    if t < 0.65:
        k = (t - 0.35) / 0.30
        fld = np.asarray(field.render(frame), dtype=np.float32); dth = np.asarray(dith, dtype=np.float32)
        # dissolve cell by cell using Bayer thresholds so it reads as data resolving, not a crossfade
        mask = reveal_mask(k, W, H, block)
        return Image.fromarray((fld * (1 - mask) + dth * mask).astype(np.uint8))
    k = (t - 0.65) / 0.35
    clr = np.asarray(state_clear(frame, W, H), dtype=np.float32); dth = np.asarray(dith, dtype=np.float32)
    mask = reveal_mask(k, W, H, block)
    return Image.fromarray((dth * (1 - mask) + clr * mask).astype(np.uint8))

# ---------- io ----------
def even(n): return int(n) // 2 * 2

def load_frames(inp, fps, tmp):
    frames = tmp / "in"; frames.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(inp), "-vf", f"fps={fps}", str(frames / "f%05d.png")], check=True)
    return sorted(frames.glob("f*.png"))

def encode(frames_dir, fps, outp):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", str(frames_dir / "f%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(outp)], check=True)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input"); ap.add_argument("outdir")
    ap.add_argument("--state", default="all", choices=["field", "dither", "clear", "all", "sequence"])
    ap.add_argument("--width", type=int, default=None, help="output width (default: source)")
    ap.add_argument("--cols", type=int, default=72, help="numbers per row in the field state")
    ap.add_argument("--block", type=int, default=12, help="pixel block size in the dither state, px")
    ap.add_argument("--levels", type=int, default=4, help="tone levels in the dither state")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--reroll", type=float, default=0.05, help="share of field cells that change each frame")
    ap.add_argument("--lime", default="#CDFE7C")
    ap.add_argument("--seconds", type=float, default=4.0, help="sequence length when the input is an image")
    ap.add_argument("--start", type=float, default=None, help="sequence: seconds into the video where resolve begins")
    ap.add_argument("--end", type=float, default=None, help="sequence: seconds where the clear state is fully reached")
    ap.add_argument("--hold", type=float, default=0.0, help="sequence (image): seconds to hold the clear frame at the end")
    a = ap.parse_args()
    inp, out = Path(a.input), Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    stem = inp.stem; is_video = inp.suffix.lower() in VIDEO_EXT
    if is_video and not shutil.which("ffmpeg"): raise SystemExit("ffmpeg not found")
    lut = ramp_lut(a.lime)

    if not is_video:
        im = Image.open(inp).convert("RGB")
        W = even(a.width or im.width); H = even(W * im.height / im.width)
        field = Field(W, H, a.cols, a.lime)
        if a.state in ("field", "all"): field.render(im).save(out / f"{stem}-field.png")
        if a.state in ("dither", "all"): state_dither(im, W, H, a.block, a.lime, a.levels, lut=lut).save(out / f"{stem}-dither.png")
        if a.state in ("clear", "all"): state_clear(im, W, H).save(out / f"{stem}-clear.png")
        if a.state == "sequence":
            tmp = Path(tempfile.mkdtemp()); od = tmp / "out"; od.mkdir()
            n = int(a.seconds * a.fps); hold = int(a.hold * a.fps)
            for i in range(n + hold):
                t = min(1.0, i / max(n - 1, 1))
                if i and t < 0.65: field.reroll(a.reroll)
                sequence_frame(im, t, field, W, H, a.block, a.lime, lut).save(od / f"f{i + 1:05d}.png")
            encode(od, a.fps, out / f"{stem}-resolve.mp4"); shutil.rmtree(tmp)
        print("wrote", *sorted(p.name for p in out.glob(f"{stem}-*")))
        return

    tmp = Path(tempfile.mkdtemp()); files = load_frames(inp, a.fps, tmp)
    first = Image.open(files[0]); W = even(a.width or first.width); H = even(W * first.height / first.width)
    field = Field(W, H, a.cols, a.lime)
    states = ["field", "dither", "clear"] if a.state == "all" else [a.state]
    dirs = {s: (tmp / s) for s in states}
    for d in dirs.values(): d.mkdir()
    dur = len(files) / a.fps
    t0 = a.start if a.start is not None else 0.0
    t1 = a.end if a.end is not None else dur
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        if i: field.reroll(a.reroll)
        for s in states:
            if s == "field": o = field.render(im)
            elif s == "dither": o = state_dither(im, W, H, a.block, a.lime, a.levels, lut=lut)
            elif s == "clear": o = state_clear(im, W, H)
            else:
                t = 0.0 if i / a.fps <= t0 else min(1.0, (i / a.fps - t0) / max(t1 - t0, 1e-6))
                o = sequence_frame(im, t, field, W, H, a.block, a.lime, lut)
            o.save(dirs[s] / f.name)
    for s, d in dirs.items():
        encode(d, a.fps, out / f"{stem}-{'resolve' if s == 'sequence' else s}.mp4")
    shutil.rmtree(tmp); print("wrote", *sorted(p.name for p in out.glob(f"{stem}-*")), f"({len(files)} frames)")

if __name__ == "__main__":
    main()
