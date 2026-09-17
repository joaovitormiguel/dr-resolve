# Resolve

Renders the Drayrates data-layer motif from any image or video.

The idea: under every drayage lane there is a layer of numbers nobody could read. Drayrates is the act of that layer becoming legible. The tool renders the three states of that idea and the transition between them.

| State | What it is |
|---|---|
| `field` | Dim two-digit numbers in JetBrains Mono whose brightness follows the source. Data nobody can read. |
| `dither` | One block per number cell, on the same grid as the field, ordered-dithered in the lime ramp. A shape emerges. Partial legibility. |
| `clear` | The source itself, graded dark. Legibility. |
| `sequence` | Animates field → dither → clear. Each number cell lights up into its block, then each block resolves to the picture, in Bayer order. It reads as data resolving, not a crossfade. |

## Install

Python 3.9+, `pip install pillow numpy`, and `ffmpeg` on the PATH for video.

## Use (web UI)

```bash
python3 app.py
```

Opens http://localhost:8765 in your browser. Drop an image or video, pick a state, adjust the sliders, press Render. Results preview on the page with download links. Everything runs locally; uploads and renders land in `jobs/`.

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

Options: `--width` output width (source by default) · `--cols` numbers per row in the field (72) · `--fill` how much of each cell a dither block fills (0.82) · `--levels` tones in the dither (4) · `--fps` (24) · `--reroll` share of field cells that change each frame (0.05) · `--lime` accent hex (#CDFE7C).

## Rules that make it look right

- Subjects must fill the frame and sit against dark backgrounds. A small object in a mid-gray scene resolves as noise.
- Lime only appears in the dither and clear states, and only where the source is brightest. Never use the lime as a flat field.
- Use one resolve per scene. The order is always field, dither, clear; reverse it to leave a scene.
- Every frame is auto-leveled (darkest 2% to black, brightest 0.5% to full lime) so exposure differences between shots do not change the look.

Font: JetBrains Mono (SIL Open Font License), bundled in `fonts/`.
