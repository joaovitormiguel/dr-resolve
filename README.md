# Resolve

**Use it in your browser, no install: https://joaovitormiguel.github.io/dr-resolve/**

The web version runs entirely on your machine (canvas + the browser's video encoder); nothing is uploaded. Stills work everywhere; MP4 export needs Chrome, Edge, or Safari 16.4+. The Python tool and local UI below do the same thing offline and are faster on long clips.

Renders the Drayrates data-layer motif from any image or video.

The idea: under every drayage lane there is a layer of numbers nobody could read. Drayrates is the act of that layer becoming legible. The tool renders the three states of that idea and the transition between them.

| State | What it is |
|---|---|
| `field` | Dim two-digit numbers in JetBrains Mono whose brightness follows the source. Data nobody can read. |
| `dither` | One block per number cell, on the same grid as the field, ordered-dithered in the lime ramp. A shape emerges. Partial legibility. |
| `clear` | The source itself, graded dark. Legibility. |
| `ascii` | Character-art render: each cell picks a glyph by brightness from a charset (`code`, `digits`, `currency`, `arrows`, `binary`, `blocks`, or any string), strong edges become line glyphs that follow the contour. Dark areas stay empty. |
| `icons` | One small icon per cell (Lucide set in `icons/`), tinted by the source brightness. `--flip "1.5:mail"` makes every cell flip to the envelope at 1.5s in a fast cascade; `4:random` flips back to the pool. |
| `sequence` | Animates field → dither → clear. Each number cell lights up into its block, then each block resolves to the picture, in Bayer order. It reads as data resolving, not a crossfade. |

## Install

Python 3.9+, `pip install pillow numpy`, and `ffmpeg` on the PATH for video.

## Use (web UI)

```bash
python3 app.py
```

Opens http://localhost:8765 in your browser. Drop an image or video, pick a state, adjust the sliders, press Render. Results preview on the page with download links. Everything runs locally; uploads and renders land in `jobs/`.

## Run on another computer

```bash
git clone https://github.com/joaovitormiguel/dr-resolve.git
cd dr-resolve
pip install pillow numpy      # plus ffmpeg on the PATH for video
python3 app.py
```

## Host it (optional)

A `Dockerfile` is included, so any container host works (Railway, Fly.io, Render, a VPS). Set `HOST=0.0.0.0` and the host's `PORT`. There is no login on the app, so put it behind the host's auth or a private URL: anyone with the link can upload and render.

## Use (command line)

```bash
# all three states as stills
python3 resolve.py photo.jpg out/

# a whole clip in one state
python3 resolve.py clip.mp4 out/ --state dither

# animate the resolve over a video: field until 1.5s, fully clear by 6s
python3 resolve.py clip.mp4 out/ --state sequence --start 1.5 --end 6

# animate the resolve on a still: 4 seconds, hold the clear frame for 1s
python3 resolve.py photo.jpg out/ --state sequence --seconds 4 --hold 1
```

Options: `--charset` ascii charset (code) · `--no-edges` · `--flat` single-colour glyphs · `--fg` glyph colour · `--icons` comma list for the pool · `--flip` timed flips · `--flip-dur` (0.5) · `--glyphs digits|ascii|icons` what the sequence's field phase renders · `--width` output width (source by default) · `--cols` numbers per row in the field (72) · `--fill` how much of each cell a dither block fills (1 = solid, default; lower adds a gap) · `--levels` tones in the dither (4) · `--fps` (24) · `--reroll` share of field cells that change each frame (0.05) · `--lime` accent hex (#CDFE7C).

## Rules that make it look right

- Subjects must fill the frame and sit against dark backgrounds. A small object in a mid-gray scene resolves as noise.
- Lime only appears in the dither and clear states, and only where the source is brightest. Never use the lime as a flat field.
- Use one resolve per scene. The order is always field, dither, clear; reverse it to leave a scene.
- Every frame is auto-leveled (darkest 2% to black, brightest 0.5% to full lime) so exposure differences between shots do not change the look.

Icons: Lucide (ISC license), rasterized in `icons/`.

Font: JetBrains Mono (SIL Open Font License), bundled in `fonts/`.
