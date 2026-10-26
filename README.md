# Slipway

> Assets are built here, launched into the engine.

**Slipway** is a per-project artifact manager that sits between AI generation pipelines and game engines. Like a ship's slipway — where a vessel is completed on land and then launched — assets are generated, gated, and approved in Slipway, and only the approved finals are exported to Godot/Unreal.

```
ComfyUI / WanGP / CosyVoice / YuE          Slipway                     Godot / Unreal
    (artifact generators)       ↔        (artifact manager)      ↔    (artifact consumers)
                                   generate → gate → approve → launch
```

## Why this exists

The generator ecosystem (ComfyUI et al.) lives in the world of "one image at a time"; the engine ecosystem (Godot et al.) lives with "a file that already exists". Nobody covers the middle: **project-level asset production management** — canon, lifecycle, a cross-modality registry, engine mapping. Slipway is that missing middle layer.

## Core concepts

### State machine

Every artifact follows a single lifecycle. Only `approved` artifacts can be exported.

```
brief → generated → gated → approved → exported
              ↑________________|
         failed gates bounce back into the generation loop
```

### Layout

```
forge/                      # one git repo per project, engine-agnostic
├─ canon/                   # story / world / character canon
│  ├─ story/                # synopsis, per-scene scripts (story is an asset too)
│  ├─ characters/<id>.yaml  # look, personality, ref sheets, reference voice, LoRA path
│  └─ style/                # style references, palettes
├─ assets/<id>.yaml         # ★ the registry (cross-modality)
├─ staging/<id>/<rev>/      # raw generations (ComfyUI metadata kept embedded)
├─ gates/                   # deterministic validators
├─ approved/<id>/<rev>/     # only what a human picked
└─ exports/
   ├─ godot/                # res:// mapping
   └─ unreal/               # Content/ mapping + naming conventions
```

### Registry schema

```yaml
# assets/hero_idle.yaml
id: hero_idle
type: sprite              # story | image | video | music | sfx | voice | mesh
scene_ref: canon/story/ch03.md#L12     # back-reference to the story
character: canon/characters/hero.yaml  # back-reference to canon (consistency tracking)
status: approved          # brief → generated → gated → approved → exported
revisions:
  - rev: 4
    backend: comfyui      # comfyui | wangp | yue | cosyvoice | stable-audio | llm
    params: { prompt: "...", seed: 812, workflow: forge_idle.json }
    gates: { transparency: pass, size: pass, canon_face: pass }
    checksum: sha256:...
exports:
  godot:  res://assets/generated/hero/idle_v4.png
  unreal: Content/Hero/Textures/T_Hero_Idle_v4
```

### Modality adapters

Every adapter is just `submit(params) → artifact + metadata`.

| Modality | Backend | Weight license |
|---|---|---|
| Image | ComfyUI (Qwen-Image, FLUX.1-schnell, HiDream) | Apache 2.0 / MIT |
| Video | WanGP (Wan2.2, Mochi 1) | Apache 2.0 |
| Voice | CosyVoice 2, GPT-SoVITS | Apache 2.0 / MIT |
| Music | YuE (s1/s2), ACE-Step | Apache 2.0 / MIT |
| SFX | Stable Audio Open | Stability Community |
| 3D | TRELLIS.2, Hunyuan3D-2.1 | MIT / Tencent Community |
| Story | local LLM / editor | — |

### Gates

Deterministic checks; failures bounce back into the generation loop:

- Shape: dimensions, alpha, channels, format, count
- Audio: duration, loudness, clipping
- Canon: embedding distance against reference sheets (character consistency)
- License: provenance record of base / LoRA / training data

## Design principles

1. **Loose coupling on both ends** — generators and engines expose nothing but files + REST; Slipway owns the registry, both sides degrade into pluggable backends
2. **Approved-gated export** — only human-picked artifacts ever reach the engine; unapproved output does not exist there
3. **Deterministic first** — mechanical gates catch everything catchable before any AI judgment
4. **Everything in git** — text/JSON/SQLite, so history and per-asset revision branching come for free

## Planned reuse (licenses verified)

| Source | What we take |
|---|---|
| [sprite-foundry](https://github.com/mcp-tool-shop-org/sprite-foundry) (MIT) | SQLite lifecycle, mechanical gates, canon binding, checksum export |
| [hermes-asset-pipeline](https://github.com/Limbicnation/hermes-asset-pipeline) (Apache 2.0) | staging conventions, format bridge, uv isolation |
| [godogen](https://github.com/htdt/godogen) (MIT) | canon loop (story → generate → QA → fix) |
| ComfyUI official MCP | generation queue integration |

## Status

**Design stage.** Only this README exists; implementation has not started.

- [ ] Registry schema + CLI
- [ ] ComfyUI / CosyVoice adapters
- [ ] Gates (shape × 3)
- [ ] `slip export godot`

## The name

A slipway is the ramp where a ship is built on land and launched to sea. Assets are finished here; the voyage after launch (in-engine work) belongs to you.
