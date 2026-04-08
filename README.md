# BM3 Importer for Blender

A Blender add-on that imports **by.me BM3** 3D model files (`.bm3`) with optional BM3MAT material overrides (`.bm3mat`).

BM3 is the proprietary format used by the [by.me](https://by.me) 3D configurator platform.

## Features

- Imports `.bm3` geometry files (vertices, normals, UVs, indices, scene graph)
- Applies PBR materials (albedo, metallic, roughness, normal maps) with embedded textures
- Auto-detects `.bm3mat` material files placed in the same folder
- Supports multi-file selection for batch import
- Converts BM3 to glTF 2.0 internally, then imports via Blender's built-in glTF importer
- No external dependencies -- uses only Python standard library + bpy

## Installation

Requires **Blender 4.2+** (uses the modern extension format).

1. Download `bm3_importer.zip` from the [latest release](https://github.com/vromero/blender-bm3-importer/releases/latest)
2. In Blender, go to **Edit > Preferences > Get Extensions**
3. Open the drop-down menu (top-right) and choose **Install from Disk...**
4. Select the downloaded `bm3_importer.zip` file

## Usage

1. **File > Import > ByMe BM3 (.bm3)**
2. Navigate to your `.bm3` files and select one or more
3. Click **Import BM3**

### Material override

If a `.bm3mat` file is present in the same directory as the selected `.bm3` files, it is automatically loaded and applied as the structural material (e.g. wood grain, stone texture). This can be toggled off with the **Auto-detect material** checkbox in the import sidebar.

## BM3 format overview

BM3 files are ZIP archives containing:

| File | Description |
|---|---|
| `manifest.json` | Scene graph, materials (DSPBR/PBR), vertex layouts, buffer references, textures |
| `binary.bin` | Interleaved vertex data, index buffers, and embedded texture images (JPEG/PNG) |

The manifest structure maps closely to glTF 2.0:

- **Vertex layout**: POSITION (float3), NORMAL (float3), TEXCOORD_0 (float2)
- **Materials**: Dassault Systemes PBR (DSPBR) -- albedo, metallic, roughness, normal, emission
- **Textures**: JPEG/PNG embedded at byte offsets in the binary
- **Scene graph**: Hierarchical nodes with 4x4 transform matrices
- **Coordinate system**: Z-up, millimeters (converted via node transforms)

BM3MAT files share the same ZIP structure but contain only material definitions and texture data.

## Compatibility

- Blender 4.2+ (modern extension format)

## Disclaimer

This project was entirely vibe coded -- the BM3 format was reverse-engineered and the converter + add-on were written in a single AI-assisted session. It works for the files tested but there are certainly edge cases, untested material configurations, and format variations that may break things. PRs welcome.

## License

[MIT](LICENSE)
