# Diagram sources

The two diagrams in the main README are made with [Archify](https://github.com/tt-a1i/archify) (Apache-2.0).
These JSON files are the exact candidates that passed Archify's `validate`, `deliver`, `check` and
`browser-check` gates on 2026-11-13 (Archify 3.2.0).

| Source | README image |
|---|---|
| `architecture.archify.json` | `docs/assets/architecture.svg`, `docs/assets/architecture-motion.gif` |
| `film-pipeline.archify.json` | `docs/assets/workflow.svg` |

## Regenerate

```bash
# from a folder that contains the Archify skill (bin/archify.mjs)
node bin/archify.mjs finalize architecture architecture.archify.json out/architecture.html --quality showcase --json
node bin/archify.mjs finalize workflow film-pipeline.archify.json out/film-pipeline.html --quality showcase --json
```

Set `meta.output` in each JSON to the same relative path you pass on the command line. Open the
HTML and use **Export → SVG · Auto** for the theme-following SVG, or **Export → WebM** for the motion clip
(converted to GIF with ffmpeg).

## Other images

- `hero.svg` is hand-written SVG with CSS animation.
- `demo.gif`, `board.png`, `keyframes.jpg` and `film-frames.jpg` come from `python examples/offline_demo.py`
  (demo mode, placeholder media). The CI workflow uploads that output as the `offline-demo` artifact.
