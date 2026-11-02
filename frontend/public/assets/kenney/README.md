# Optional local Kenney assets

No artwork is bundled or fetched by MythosLive. Place your own CC0 downloads here after obtaining them from the sources listed in `docs/asset-credits.md`.

To enable the optional Phaser sprite sheets, add `asset-manifest.json` in this directory:

```json
{
  "tileSheet": "/assets/kenney/tiny-dungeon/tiles.png",
  "tileFrameWidth": 16,
  "tileFrameHeight": 16,
  "floorFrame": 0,
  "heroSheet": "/assets/kenney/tiny-town/characters.png",
  "heroFrameWidth": 16,
  "heroFrameHeight": 24,
  "heroFrame": 0
}
```

Paths must remain under `/assets/kenney/`; remote URLs are ignored. Set frame sizes and frame indices to match the files you placed. The overlay keeps its vector placeholder artwork if the manifest or either sprite sheet is missing or invalid.
