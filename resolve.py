#!/usr/bin/env python3
"""Resolve: renders the Drayrates data-layer motif from any image or video.

States
  field   dim two-digit numbers whose brightness follows the source (data nobody can read)
  dither  one lime-ramp block per number cell, ordered-dithered; a shape emerges (partial legibility)
  clear   the source itself, graded dark (legibility = transparency)
  ascii   character-art render: each cell picks a glyph by brightness from a charset,
          strong edges become line glyphs that follow the contour (BUCK / Coinbase style)
  icons   one small icon per cell (Lucide set in icons/), brightness from the source;
          --flip "1.5:mail" makes every cell flip to the envelope at 1.5s (cue for "a rate request lands")

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
ICONS = HERE / "icons"
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
        self.cw = W / cols; self.ch = self.cw * 0.9
        self.rows = int(np.ceil(H / self.ch))
        # per-pixel cell index maps so every state shares exactly this grid
        self.col_of_x = np.minimum((np.arange(W) / self.cw).astype(int), cols - 1)
        self.row_of_y = np.minimum((np.arange(H) / self.ch).astype(int), self.rows - 1)
        self.thr = np.tile(BAYER8, (self.rows // 8 + 1, cols // 8 + 1))[:self.rows, :cols]
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


# ---------- state: ascii (glyph chosen by brightness; edges become line glyphs) ----------
CHARSETS = {
    "digits":   "0123456789",
    "code":     " .,:;-~=+*<>/\\|[]{}()#%&$@",
    "currency": " .:-=$#%&@",
    "arrows":   " .-<>^v=+",
    "binary":   " .01",
    "blocks":   " .:░▒▓█",
}

class Ascii:
    """Field-compatible renderer: same grid, but glyphs come from a density-sorted charset."""
    def __init__(self, field, charset="code", edges=True, fg="#CDFE7C", flat=False, seed=7):
        self.f = field; self.edges = edges; self.flat = flat
        chars = CHARSETS.get(charset, charset)
        # sort the charset by real ink density in this font so brightness maps to visual weight
        dens = []
        for ch in chars:
            im = Image.new("L", (int(field.cw * 2) + 8, int(field.ch * 2) + 8), 0)
            ImageDraw.Draw(im).text((4, 4), ch, font=field.font, fill=255)
            dens.append((np.asarray(im).mean(), ch))
        dens.sort(); self.ramp = [c for _, c in dens]
        self.lut = ramp_lut(fg); self.rng = random.Random(seed)
        self.jitter = np.zeros((field.rows, field.cols), dtype=np.int8)
    def reroll(self, rate):
        m = np.random.default_rng(self.rng.randint(0, 1 << 30)).random(self.jitter.shape) < rate
        self.jitter[m] = np.random.default_rng(self.rng.randint(0, 1 << 30)).integers(-1, 2, m.sum())
    def render(self, frame, gain=1.0, gamma=1.1, edge_thr=0.35, floor=0.12):
        f = self.f
        lum = np.clip(luminance(frame, f.cols, f.rows, blur=0.3) ** gamma * gain, 0, 1)
        n = len(self.ramp)
        # remap so everything under the floor is empty and the ramp starts just above it
        scaled = np.clip((lum - floor) / (1 - floor), 0, 1)
        idx = np.clip((scaled * (n - 1)).round().astype(int) + self.jitter, 0, n - 1)
        idx[lum < floor] = 0
        # edge orientation on the cell grid: Sobel on a 2x finer luminance, pooled back
        if self.edges:
            fine = luminance(frame, f.cols * 2, f.rows * 2, blur=0.6)
            gy, gx = np.gradient(fine)
            mag = np.hypot(gx, gy); ang = np.arctan2(gy, gx)
            mag = mag.reshape(f.rows, 2, f.cols, 2).mean(axis=(1, 3))
            ang = ang.reshape(f.rows, 2, f.cols, 2).mean(axis=(1, 3))
            strong = mag > edge_thr * mag.max() if mag.max() > 0 else np.zeros_like(mag, bool)
            # gradient is perpendicular to the edge; pick the glyph that runs along the edge
            deg = (np.degrees(ang) + 90) % 180
            edge_glyph = np.where(deg < 22.5, "-", np.where(deg < 67.5, "/", np.where(deg < 112.5, "|", np.where(deg < 157.5, "\\", "-"))))
        out = Image.new("RGB", (f.W, f.H), (0, 0, 0)); d = ImageDraw.Draw(out)
        for r in range(f.rows):
            for c in range(f.cols):
                v = float(lum[r, c])
                if self.edges and strong[r, c]:
                    ch = edge_glyph[r, c]; v = max(v, 0.75)
                else:
                    ch = self.ramp[idx[r, c]]
                if ch == " " or (v < floor and not (self.edges and strong[r, c])): continue
                col = tuple(int(x) for x in self.lut[255 if self.flat else min(255, int(v * 255))])
                gw = f.font.getlength(ch)
                d.text((c * f.cw + (f.cw - gw) / 2, r * f.ch + f.ch * 0.12), ch, font=f.font, fill=col)
        return out


# ---------- state: icons (one Lucide icon per cell; timed flips) ----------
class Icons:
    """Field-compatible renderer. Each cell shows an icon tinted by the source brightness.
    pool: icon names drawn at random per cell. flips: [(time_s, name or "random"), ...]."""
    def __init__(self, field, pool, flips=(), fg="#CDFE7C", flip_dur=0.5, size=0.78, seed=7):
        self.f = field; self.lut = ramp_lut(fg); self.flip_dur = flip_dur
        self.names = sorted({n for n in list(pool) + [n for _, n in flips] if n != "random"})
        self.masks = {}
        cw, ch = max(4, int(field.cw * size)), max(4, int(field.ch * size))
        for n in self.names:
            path = ICONS / f"{n}.png"
            if not path.exists(): raise SystemExit(f"icon not found: {path.name}; available: " + ", ".join(sorted(q.stem for q in ICONS.glob("*.png"))))
            self.masks[n] = Image.open(path).convert("RGBA").split()[3].resize((cw, ch), Image.LANCZOS)
        self.cw_i, self.ch_i = cw, ch
        rng = random.Random(seed); self.rng = rng
        pool = list(pool)
        self.cur = [[rng.choice(pool) for _ in range(field.cols)] for _ in range(field.rows)]
        self.pool = pool; self.flips = sorted(flips); self.t = 0.0
    def _target(self, t):
        name = None
        for ft, n in self.flips:
            if t >= ft: name = (ft, n)
        return name
    def render(self, frame, t=0.0, gain=1.0, gamma=1.3, floor=0.05):
        f = self.f; self.t = t
        lum = np.clip(luminance(frame, f.cols, f.rows, blur=0.5) ** gamma * gain, 0, 1)
        out = Image.new("RGB", (f.W, f.H), (0, 0, 0))
        tgt = self._target(t)
        for r in range(f.rows):
            for c in range(f.cols):
                v = float(lum[r, c])
                if v < floor: continue
                name = self.cur[r][c]; squash = 1.0
                if tgt:
                    ft, tn = tgt
                    # each cell flips at its own moment inside flip_dur, in Bayer order, with a horizontal squash
                    start = ft + f.thr[r, c] * self.flip_dur * 0.8
                    p = (t - start) / max(self.flip_dur * 0.2, 1e-6)
                    if p >= 1.0:
                        name = tn if tn != "random" else (self.cur[r][c] if self._flipped_to_random(r, c, ft) else self.cur[r][c])
                        if tn != "random": self.cur[r][c] = tn
                    elif p > 0.0:
                        squash = abs(np.cos(np.pi * p))
                        if p > 0.5: name = tn if tn != "random" else self.cur[r][c]
                m = self.masks[name]
                if squash < 0.999:
                    w = max(1, int(self.cw_i * squash)); m = m.resize((w, self.ch_i), Image.BILINEAR)
                col = tuple(int(x) for x in self.lut[min(255, int(v * 255))])
                x = int(c * f.cw + (f.cw - m.width) / 2); y = int(r * f.ch + (f.ch - m.height) / 2)
                out.paste(col, (x, y, x + m.width, y + m.height), m)
        return out
    def _flipped_to_random(self, r, c, ft):
        key = (r, c, ft)
        if key not in getattr(self, "_rand_done", set()):
            self._rand_done = getattr(self, "_rand_done", set()); self._rand_done.add(key)
            self.cur[r][c] = self.rng.choice(self.pool)
        return True
    def reroll(self, rate):
        if self._target(self.t): return  # hold the flipped icon
        for r in range(self.f.rows):
            for c in range(self.f.cols):
                if self.rng.random() < rate: self.cur[r][c] = self.rng.choice(self.pool)

def parse_flips(spec):
    out = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part: continue
        t, name = part.split(":"); out.append((float(t), name.strip()))
    return out

# ---------- state: dither (one block per number cell) ----------
def state_dither(frame, field, lime, levels_n=4, gamma=1.2, fill=1.0, lut=None):
    """Ordered (Bayer 8x8) dither on the field's own grid: each number cell becomes one block."""
    lum = luminance(frame, field.cols, field.rows, blur=0.4) ** gamma
    q = np.clip(np.floor(lum * (levels_n - 1) + field.thr) / (levels_n - 1), 0, 1)
    lut = lut if lut is not None else ramp_lut(lime)
    rgb = lut[(q * 255).astype(np.uint8)][field.row_of_y[:, None], field.col_of_x[None, :]]
    if fill >= 1.0:
        return Image.fromarray(rgb.astype(np.uint8))
    # optional inset so each block reads as a box, shifted up slightly to sit on the glyph
    fx = (np.arange(field.W) / field.cw) % 1.0; fy = (np.arange(field.H) / field.ch) % 1.0
    lo, hi = (1 - fill) / 2, 1 - (1 - fill) / 2; up = min(0.04, lo)
    inside = ((fx >= lo) & (fx <= hi))[None, :] & ((fy >= lo - up) & (fy <= hi - up))[:, None]
    return Image.fromarray((rgb * inside[..., None]).astype(np.uint8))

def reveal_mask(k, field):
    """(H, W, 1) mask on the field grid: cells whose Bayer threshold < k are revealed."""
    return (field.thr < k).astype(np.float32)[field.row_of_y[:, None], field.col_of_x[None, :]][..., None]

# ---------- sequence: field -> dither -> clear ----------
def sequence_frame(frame, t, field, W, H, lime, lut, levels_n=4, fill=1.0, glyphs=None, secs=0.0):
    """t in 0..1. 0-0.35 field brightens; 0.35-0.65 each cell's number lights up into its block; 0.65-1 blocks resolve to clear."""
    src = glyphs or field
    def rsrc(**kw):
        return src.render(frame, secs, **kw) if isinstance(src, Icons) else src.render(frame, **kw)
    if t < 0.35:
        return rsrc(gain=0.35 + 0.65 * (t / 0.35))
    dith = np.asarray(state_dither(frame, field, lime, levels_n, fill=fill, lut=lut), dtype=np.float32)
    if t < 0.65:
        k = (t - 0.35) / 0.30
        fld = np.asarray(rsrc(), dtype=np.float32); mask = reveal_mask(k, field)
        return Image.fromarray((fld * (1 - mask) + dith * mask).astype(np.uint8))
    k = (t - 0.65) / 0.35
    clr = np.asarray(state_clear(frame, W, H), dtype=np.float32); mask = reveal_mask(k, field)
    return Image.fromarray((dith * (1 - mask) + clr * mask).astype(np.uint8))

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
    ap.add_argument("--state", default="all", choices=["field", "dither", "clear", "ascii", "icons", "all", "sequence"])
    ap.add_argument("--icons", default="container,truck,ship,train-front,anchor,package,file-text,dollar-sign", help="icons: comma list drawn at random per cell (names from icons/)")
    ap.add_argument("--flip", default="", help='icons: timed flips, e.g. "1.5:mail,4:random" (seconds)')
    ap.add_argument("--flip-dur", type=float, default=0.5, help="icons: how long a flip cascade takes")
    ap.add_argument("--charset", default="code", help="ascii charset: " + ", ".join(CHARSETS) + ", or a custom string")
    ap.add_argument("--no-edges", action="store_true", help="ascii: do not trace edges with line glyphs")
    ap.add_argument("--flat", action="store_true", help="ascii: single colour glyphs instead of a brightness ramp")
    ap.add_argument("--fg", default=None, help="ascii glyph colour (default: --lime)")
    ap.add_argument("--glyphs", default="digits", choices=["digits", "ascii", "icons"], help="sequence: what the field phase renders")
    ap.add_argument("--width", type=int, default=None, help="output width (default: source)")
    ap.add_argument("--cols", type=int, default=72, help="numbers per row in the field state")
    ap.add_argument("--fill", type=float, default=1.0, help="how much of each cell a dither block fills (1 = solid, lower adds a gap)")
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
        asc = Ascii(field, a.charset, not a.no_edges, a.fg or a.lime, a.flat)
        ico = Icons(field, a.icons.split(","), parse_flips(a.flip), a.fg or a.lime, a.flip_dur) if a.state in ("icons", "all") or a.glyphs == "icons" else None
        if a.state in ("field", "all"): field.render(im).save(out / f"{stem}-field.png")
        if a.state in ("ascii", "all"): asc.render(im).save(out / f"{stem}-ascii.png")
        if a.state == "icons":
            tmp = Path(tempfile.mkdtemp()); od = tmp / "out"; od.mkdir(); n = int(a.seconds * a.fps)
            for i in range(n):
                if i: ico.reroll(a.reroll)
                ico.render(im, i / a.fps).save(od / f"f{i + 1:05d}.png")
            encode(od, a.fps, out / f"{stem}-icons.mp4"); shutil.rmtree(tmp)
        elif a.state == "all": ico.render(im).save(out / f"{stem}-icons.png")
        if a.state in ("dither", "all"): state_dither(im, field, a.lime, a.levels, fill=a.fill, lut=lut).save(out / f"{stem}-dither.png")
        if a.state in ("clear", "all"): state_clear(im, W, H).save(out / f"{stem}-clear.png")
        if a.state == "sequence":
            tmp = Path(tempfile.mkdtemp()); od = tmp / "out"; od.mkdir()
            n = int(a.seconds * a.fps); hold = int(a.hold * a.fps)
            for i in range(n + hold):
                t = min(1.0, i / max(n - 1, 1))
                if i and t < 0.65: field.reroll(a.reroll); asc.reroll(a.reroll); (ico and ico.reroll(a.reroll))
                g = {"ascii": asc, "icons": ico}.get(a.glyphs)
                sequence_frame(im, t, field, W, H, a.lime, lut, a.levels, a.fill, g, i / a.fps).save(od / f"f{i + 1:05d}.png")
            encode(od, a.fps, out / f"{stem}-resolve.mp4"); shutil.rmtree(tmp)
        print("wrote", *sorted(p.name for p in out.glob(f"{stem}-*")))
        return

    tmp = Path(tempfile.mkdtemp()); files = load_frames(inp, a.fps, tmp)
    first = Image.open(files[0]); W = even(a.width or first.width); H = even(W * first.height / first.width)
    field = Field(W, H, a.cols, a.lime)
    asc = Ascii(field, a.charset, not a.no_edges, a.fg or a.lime, a.flat)
    ico = Icons(field, a.icons.split(","), parse_flips(a.flip), a.fg or a.lime, a.flip_dur) if a.state in ("icons", "all") or a.glyphs == "icons" else None
    states = ["field", "ascii", "icons", "dither", "clear"] if a.state == "all" else [a.state]
    dirs = {s: (tmp / s) for s in states}
    for d in dirs.values(): d.mkdir()
    dur = len(files) / a.fps
    t0 = a.start if a.start is not None else 0.0
    t1 = a.end if a.end is not None else dur
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        if i: field.reroll(a.reroll); asc.reroll(a.reroll); (ico and ico.reroll(a.reroll))
        for s in states:
            if s == "field": o = field.render(im)
            elif s == "ascii": o = asc.render(im)
            elif s == "icons": o = ico.render(im, i / a.fps)
            elif s == "dither": o = state_dither(im, field, a.lime, a.levels, fill=a.fill, lut=lut)
            elif s == "clear": o = state_clear(im, W, H)
            else:
                t = 0.0 if i / a.fps <= t0 else min(1.0, (i / a.fps - t0) / max(t1 - t0, 1e-6))
                o = sequence_frame(im, t, field, W, H, a.lime, lut, a.levels, a.fill, {"ascii": asc, "icons": ico}.get(a.glyphs), i / a.fps)
            o.save(dirs[s] / f.name)
    for s, d in dirs.items():
        encode(d, a.fps, out / f"{stem}-{'resolve' if s == 'sequence' else s}.mp4")
    shutil.rmtree(tmp); print("wrote", *sorted(p.name for p in out.glob(f"{stem}-*")), f"({len(files)} frames)")

if __name__ == "__main__":
    main()
