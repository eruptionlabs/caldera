# Caldera

**English** · [Português](README.pt-BR.md) · [日本語](README.ja.md)

Visual HUD editor for [Eruption Engine](https://github.com/eruptionlabs/eruption-engine).

The engine describes its HUD in CSS (`data/hud/default.css`). Caldera opens that file, draws every widget exactly where the engine will draw it, and lets you move, resize and reorder everything with the mouse. When you export, it writes the CSS back and the engine hot-reloads the HUD without a restart.

![Caldera editing the default HUD](docs/screenshot.png)

## Why it matches the game

The preview is not a mockup. Caldera uses the same layout rules as the engine's `CSSLayout` and projects the character with the same camera (60° FOV, the game's starting distance and pitch) and the same billboard as the sprite shader. Widgets attached to the player (`--bind-to-player: 1`) show up exactly where they will appear over the sprite, at any zoom and tilt.

The canvas uses the same scale on X and Y, so the window can have any aspect ratio without stretching the HUD.

## Requirements

- Python 3.10 or newer
- pygame 2.5 or newer (`run.sh` installs it into its own virtual environment)
- A checkout of Eruption Engine

## Running

Inside the engine, where it ships as a submodule:

```bash
git clone --recurse-submodules https://github.com/eruptionlabs/eruption-engine.git
cd eruption-engine
tools/caldera/run.sh
```

Outside the engine, point it at your checkout:

```bash
ERUPTION_ROOT=/path/to/eruption-engine ./run.sh
```

Without `ERUPTION_ROOT`, Caldera walks up from its own folder until it finds the engine's `CMakeLists.txt`.

## Widgets

| Selector | What it is | Positioned relative to |
|---|---|---|
| `#hero-panel` | Bottom panel | screen |
| `#hero-portrait` | Portrait | panel |
| `#hero-level` | Level badge | panel |
| `#hero-hp-bar`, `#hero-sp-bar` | HP and SP bars | panel |
| `#skill-slots`, `#attr-matrix`, `#equip-panel` | Slots filled in by the game | panel |
| `#overhead-hp-sp` | HP and SP above the character | player |
| `#cast-bar` | Cast bar | player or screen |
| `#boss-hp-bar` | Boss bar | screen |
| `#minimap`, `#minimap-info` | Minimap and map name box | screen |

Positions relative to the screen or the panel are saved as percentages. Widgets attached to the player are saved in pixels from the base of the sprite and scale with the camera zoom.

## Controls

| Action | Input |
|---|---|
| Move a widget | drag |
| Resize | drag the handles of the selected widget |
| Nudge | arrow keys (Shift moves 10 px) |
| Reorder layers | drag in the layers panel, or Ctrl + PgUp / PgDn |
| Attach to or detach from the player | B |
| Snap to grid | G |
| Layers panel | L |
| Lock layer order | K |
| Export to `default.css` | E, or the Export button |
| Clear selection | Esc |
| Preview camera zoom | + and −, 0 resets to the game default |
| Camera tilt | [ and ], P resets to 50° |

## Environment variables

| Variable | Purpose |
|---|---|
| `ERUPTION_ROOT` | Engine folder, when Caldera lives outside it |
| `CALDERA_WINDOW=1600x900` | Initial window size |
| `CALDERA_VIRTUAL=1280x720` | Emulated screen resolution (default 1920x1080) |
| `CALDERA_SCREENSHOT=out.png` | Renders a few frames, saves the image and exits. Handy for comparing against an engine capture |

To compare against the game side by side, capture the engine with its HUD and render Caldera at the same resolution:

```bash
ERUPTION_TEST_SWAP_SHOT=game.png,300 ERUPTION_TEST_EXIT_FRAME=330 ./eruption-engine --map parana_field
CALDERA_VIRTUAL=1280x720 CALDERA_SCREENSHOT=caldera.png tools/caldera/run.sh
```

## Optional images

If they exist in the engine, the preview uses `assets/hud/portrait.png` and `assets/hud/skill_1.png` through `skill_4.png`. Without them the slots are drawn empty. The character sprite comes from `assets/sprites/default.spr` (ERUPTSPR format) or, if that is missing, from `default.png`.

## License

Apache License 2.0, the same as Eruption Engine. pygame is distributed under the LGPL and is installed separately by `run.sh`.

"Eruption Engine" and its logo are trademarks of Gdg Soluções Digitais LTDA.
