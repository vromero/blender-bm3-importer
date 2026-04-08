# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Blender add-on that imports by.me BM3 3D model files (`.bm3`) with optional BM3MAT material overrides (`.bm3mat`). The converter translates BM3 to glTF 2.0 (GLB) in pure Python, then hands off to Blender's built-in glTF importer.

## Development

This is a Blender 4.2+ extension using the modern `blender_manifest.toml` format (not legacy `bl_info`). No external dependencies — only Python stdlib + `bpy`.

**Build extension ZIP:** `cd bm3_importer && zip -r ../bm3_importer.zip blender_manifest.toml __init__.py`

**Install for testing:** In Blender, Edit > Preferences > Get Extensions > Install from Disk > select `bm3_importer.zip`.

There is no build step, linter, or test suite configured.

## Architecture

The entire add-on lives in `bm3_importer/__init__.py` (~410 lines). Key flow:

1. **`_extract_bm3(data)`** — Unzips BM3/BM3MAT archive → returns `(manifest dict, binary bytes)`
2. **`_bm3_to_glb(manifest, binary, mat_manifest, mat_binary)`** — Core converter. Processes materials, vertex buffers, index buffers, textures, and scene graph into a valid GLB byte stream
3. **`IMPORT_OT_bm3.execute()`** — Blender operator. Reads files, calls converter, writes temp GLB, invokes `bpy.ops.import_scene.gltf`, cleans up

### BM3 Format Details

- BM3 files are ZIPs containing `manifest.json` + `binary.bin`
- Materials named `__GLTFLoader._default` in the geometry BM3 get replaced by the first material from the BM3MAT file
- Vertex data is interleaved: POSITION(float3) + NORMAL(float3) + TEXCOORD_0(float2) = 32 bytes/vertex
- BM3 uses Z-up millimeters; a wrapper root node with scale `[0.001, 0.001, 0.001]` converts to glTF meters
- DSPBR material properties (albedo, metallic, roughness, normal) map to glTF PBR

### Key Design Decisions

- No network/download functionality — user provides BM3 files
- BM3MAT auto-detection: scans the same directory as the selected BM3 files for `.bm3mat` files
- Temp GLB files are written to system temp dir and cleaned up after import
