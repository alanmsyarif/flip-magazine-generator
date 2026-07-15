# Magazine Forge

**Procedural magazine generator with physics-flavored page-flip animation for Blender.**

Build a fully procedural magazine in one click — or import a real PDF and watch it flip through its own pages with realistic follow-through, gravity droop, and paper flutter. Built entirely on Geometry Nodes: no baking, no simulation caches, fully art-directable, and scrubbable on the timeline in both directions.

![Magazine Forge demo](docs/demo.gif)

---

## Features

- **One-click procedural magazine** — page count, size, paper thickness, and mesh resolution all live on the modifier
- **PDF import** — rasterizes every page of a PDF and maps them onto the correct sheets, front and back, with mirrored-U backfaces so text always reads correctly mid-flip
- **Physics-flavored flip motion** — analytic per-vertex deformation that behaves like paper without a physics sim:
  - *Follow-through* — the free edge lags while the page accelerates and leads while it decelerates
  - *Gravity droop* — pages sag under their own weight, strongest at 45°, vanishing when vertical or flat
  - *Flutter* — per-page seeded 4D noise, so no two pages wobble identically
  - *Root stiffness* — the spine edge stays rigid; bend builds toward the free edge with a tunable falloff
  - *Cover stiffness* — front and back covers bend less than inner pages
- **Collision-safe by construction** — per-vertex angles are clamped to the valid flip range and stack heights hand off past vertical, so pages never slice through each other (verified numerically across parameter extremes)
- **Realistic spine behavior** — the unflipped block keeps a square, flat spine edge like a real closed magazine; landed pages curl from the binding line into the natural spine tent of an open book
- **Staggered riffle cascade** — flip start, per-page duration, and stagger are independent, from a slow page-by-page browse to a fast thumb-riffle
- **Timeline-independent** — pure function of the frame number: scrub, reverse, or render any frame in isolation

## Requirements

- Blender **4.2+** (developed and tested on 5.x — socket-name fallbacks handle API renames across versions)
- PDF import: [`pypdfium2`](https://github.com/pypdfium2-team/pypdfium2) — installable with one click from the addon panel (permissive license, no manual pip needed)

## Installation

1. Download `magazine_forge.py` from [Releases](../../releases)
2. In Blender: `Edit → Preferences → Add-ons → Install from Disk…`
3. Enable **Magazine Forge**
4. Find the panel in the 3D Viewport N-panel under the **Magazine Forge** tab

## Quick start

### Procedural magazine

1. `N-panel → Magazine Forge → Create Magazine`
2. Press **Play**

### From a PDF

1. If prompted, click **Install PDF Support (pypdfium2)** once
2. `Import PDF as Magazine`, pick your file, choose a texture size
3. Press **Play**

Sheet count, aspect ratio, and flip range are set automatically from the document. Page renders are cached as PNGs in a `<name>_mfcache` folder next to the PDF, so re-imports are instant.

## Parameters

All parameters live on the Geometry Nodes modifier and are mirrored in the N-panel.

| Parameter | What it does |
|---|---|
| Pages | Number of sheets in the stack |
| Width / Height | Sheet dimensions (auto-set from PDF aspect on import) |
| Page Gap | Paper thickness / spacing between sheets |
| Spine Ramp | Length of the binding curl on the opened (landed) side |
| Res X / Res Y | Sheet mesh resolution |
| Flip Start | Frame the first page begins to turn |
| Flip Duration | Frames per page turn |
| Stagger | Frames between consecutive page starts |
| Pages To Flip | How many sheets turn during the animation |
| Bend | Follow-through strength (tip lag / overshoot) |
| Droop | Gravity sag strength |
| Flutter | Paper wobble amount |
| Stiffness Falloff | How quickly bend builds from spine to free edge |
| Cover Stiffness | Bend multiplier for the first and last sheet |

### Tuning starting points

| Look | Bend | Droop | Flutter | Stiffness Falloff |
|---|---|---|---|---|
| Coated magazine stock | 0.35 | 0.18 | 0.05 | 1.6 |
| Thin newsprint | 0.55 | 0.40 | 0.08 | 1.2 |
| Heavy card / lookbook | 0.18 | 0.08 | 0.02 | 2.2 |

## How the motion works

There is no cloth sim. Each page's flip angle follows a staggered smoothstep from 0 to 180°, and every vertex is rotated around the spine by its **own** angle:

```
alpha(x) = theta + stiffness(x) · [ follow_through + droop + flutter ] · sin(theta)
```

- `follow_through ∝ -(1 - 2p)` — proportional to angular acceleration, so the tip lags on the way up and whips past on the way down
- `droop ∝ -cos(theta)` — gravity torque, maximal at 45°/135°
- `flutter` — 4D noise seeded per page
- everything is masked by `sin(theta)`, so resting and landed pages are perfectly clean
- rotating each vertex by its own angle preserves its distance to the spine exactly — no stretching, length-correct curl

Because it's analytic, the result is deterministic, render-farm safe, and every slider maps to one visible behavior.

## Roadmap

- Simulation Zone hinge solver — true momentum with settle bounce on landing
- Seamless riffle loop mode for turntable showcases
- Square-block end state for animations that close the magazine completely
- Per-page texture atlas / UDIM option as an alternative to per-sheet materials

## License

MIT — see [LICENSE](LICENSE).

PDF rendering is powered by [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) (Apache-2.0/BSD-3-Clause), which wraps Google's PDFium.

---

Made by [Amsy](https://alanms7.artstation.com) · [More Blender tools on Gumroad](https://amsy3d.gumroad.com)
