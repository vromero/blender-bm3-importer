"""Fixtures that build minimal BM3 archives in memory for testing."""

import io
import json
import struct
import zipfile

import pytest


def _pack_bm3(manifest, binary):
    """Pack a manifest dict and binary bytes into a BM3 ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("binary.bin", binary)
    return buf.getvalue()


def _make_triangle(index_format="UNSIGNED_SHORT"):
    """Build a BM3 with a single triangle (3 vertices, 3 indices).

    Returns (bm3_bytes, vertex_count, index_count).
    """
    # 3 vertices: POSITION(float3) + NORMAL(float3) + TEXCOORD_0(float2) = 32 bytes each
    verts = b""
    for pos, uv in [((0, 0, 0), (0, 0)), ((1, 0, 0), (1, 0)), ((0, 1, 0), (0, 1))]:
        verts += struct.pack("<3f", *pos)       # POSITION
        verts += struct.pack("<3f", 0, 0, 1)    # NORMAL
        verts += struct.pack("<2f", *uv)        # TEXCOORD_0

    # Indices
    if index_format == "UNSIGNED_BYTE":
        indices = struct.pack("3B", 0, 1, 2)
    elif index_format == "UNSIGNED_INT":
        indices = struct.pack("<3I", 0, 1, 2)
    else:
        indices = struct.pack("<3H", 0, 1, 2)

    binary = verts + indices

    manifest = {
        "root": 0,
        "nodes": [
            {
                "type": "Mesh3D",
                "geometries": [0],
                "material": 0,
                "children": [],
            }
        ],
        "materials": [
            {
                "name": "test_material",
                "albedo": {"value": [0.8, 0.2, 0.2]},
                "metallic": {"value": 0.0},
                "roughness": {"value": 0.5},
            }
        ],
        "vertexLayouts": [[
            [
                {"attribute": "POSITION", "format": "FLOAT", "dimension": 3},
                {"attribute": "NORMAL", "format": "FLOAT", "dimension": 3},
                {"attribute": "TEX_COORD_0", "format": "FLOAT", "dimension": 2},
            ]
        ]],
        "geometries": [
            {
                "vertexLayout": 0,
                "vertexBuffers": [0],
                "indexBuffer": 1,
                "drawingGroups": [
                    {"start": 0, "count": 3, "mode": "TRIANGLES"}
                ],
            }
        ],
        "buffers": [
            {"binary": 0, "byteOffset": 0, "byteLength": len(verts)},
            {
                "binary": 0,
                "byteOffset": len(verts),
                "byteLength": len(indices),
                "format": index_format,
            },
        ],
    }

    return _pack_bm3(manifest, binary), 3, 3


def _make_two_drawing_groups():
    """Build a BM3 with one geometry split into two drawing groups.

    4 vertices forming a quad, split into 2 triangles via 2 drawing groups.
    Returns (bm3_bytes, vertex_count, dg_counts).
    """
    verts = b""
    for pos, uv in [((0, 0, 0), (0, 0)), ((1, 0, 0), (1, 0)),
                     ((1, 1, 0), (1, 1)), ((0, 1, 0), (0, 1))]:
        verts += struct.pack("<3f", *pos)
        verts += struct.pack("<3f", 0, 0, 1)
        verts += struct.pack("<2f", *uv)

    # 6 indices: two triangles
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    binary = verts + indices

    manifest = {
        "root": 0,
        "nodes": [
            {
                "type": "Mesh3D",
                "geometries": [0],
                "material": 0,
                "children": [],
            }
        ],
        "materials": [
            {"name": "mat", "albedo": {"value": [0.5, 0.5, 0.5]},
             "metallic": {"value": 0}, "roughness": {"value": 1}}
        ],
        "vertexLayouts": [[
            [
                {"attribute": "POSITION", "format": "FLOAT", "dimension": 3},
                {"attribute": "NORMAL", "format": "FLOAT", "dimension": 3},
                {"attribute": "TEX_COORD_0", "format": "FLOAT", "dimension": 2},
            ]
        ]],
        "geometries": [
            {
                "vertexLayout": 0,
                "vertexBuffers": [0],
                "indexBuffer": 1,
                "drawingGroups": [
                    {"start": 0, "count": 3, "mode": "TRIANGLES"},
                    {"start": 3, "count": 3, "mode": "TRIANGLES"},
                ],
            }
        ],
        "buffers": [
            {"binary": 0, "byteOffset": 0, "byteLength": len(verts)},
            {"binary": 0, "byteOffset": len(verts), "byteLength": len(indices),
             "format": "UNSIGNED_SHORT"},
        ],
    }

    return _pack_bm3(manifest, binary), 4, [3, 3]


def _make_multi_vertex_buffer():
    """Build a BM3 with a geometry referencing 2 vertex buffers (unsupported)."""
    verts = struct.pack("<3f", 0, 0, 0) * 3
    indices = struct.pack("<3H", 0, 1, 2)
    binary = verts + indices

    manifest = {
        "root": 0,
        "nodes": [{"type": "Mesh3D", "geometries": [0], "material": 0, "children": []}],
        "materials": [{"name": "m", "albedo": {"value": [1, 1, 1]},
                       "metallic": {"value": 0}, "roughness": {"value": 1}}],
        "vertexLayouts": [[
            [{"attribute": "POSITION", "format": "FLOAT", "dimension": 3}],
            [{"attribute": "NORMAL", "format": "FLOAT", "dimension": 3}],
        ]],
        "geometries": [{
            "vertexLayout": 0,
            "vertexBuffers": [0, 1],
            "indexBuffer": 2,
            "drawingGroups": [{"start": 0, "count": 3, "mode": "TRIANGLES"}],
        }],
        "buffers": [
            {"binary": 0, "byteOffset": 0, "byteLength": 36},
            {"binary": 0, "byteOffset": 0, "byteLength": 36},
            {"binary": 0, "byteOffset": 36, "byteLength": 6, "format": "UNSIGNED_SHORT"},
        ],
    }

    return _pack_bm3(manifest, binary)


def _make_bm3mat():
    """Build a BM3MAT with a single material (no textures)."""
    manifest = {
        "materials": [
            {
                "name": "override_material",
                "albedo": {"value": [0.1, 0.9, 0.1]},
                "metallic": {"value": 0.5},
                "roughness": {"value": 0.3},
            }
        ],
    }
    return _pack_bm3(manifest, b"")


def _make_default_material_bm3(mat_name="__GLTFLoader._default"):
    """Build a BM3 with a default/placeholder material (eligible for override)."""
    verts = b""
    for pos, uv in [((0, 0, 0), (0, 0)), ((1, 0, 0), (1, 0)), ((0, 1, 0), (0, 1))]:
        verts += struct.pack("<3f", *pos)
        verts += struct.pack("<3f", 0, 0, 1)
        verts += struct.pack("<2f", *uv)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = verts + indices

    manifest = {
        "root": 0,
        "nodes": [{"type": "Mesh3D", "geometries": [0], "material": 0, "children": []}],
        "materials": [
            {
                "name": mat_name,
                "albedo": {"value": [0.8, 0.8, 0.8]},
                "metallic": {"value": 0},
                "roughness": {"value": 1},
            }
        ],
        "vertexLayouts": [[
            [
                {"attribute": "POSITION", "format": "FLOAT", "dimension": 3},
                {"attribute": "NORMAL", "format": "FLOAT", "dimension": 3},
                {"attribute": "TEX_COORD_0", "format": "FLOAT", "dimension": 2},
            ]
        ]],
        "geometries": [{
            "vertexLayout": 0,
            "vertexBuffers": [0],
            "indexBuffer": 1,
            "drawingGroups": [{"start": 0, "count": 3, "mode": "TRIANGLES"}],
        }],
        "buffers": [
            {"binary": 0, "byteOffset": 0, "byteLength": len(verts)},
            {"binary": 0, "byteOffset": len(verts), "byteLength": len(indices),
             "format": "UNSIGNED_SHORT"},
        ],
    }

    return _pack_bm3(manifest, binary)


def parse_glb(glb_bytes):
    """Parse a GLB into (gltf_json_dict, bin_bytes)."""
    magic, version, length = struct.unpack_from("<III", glb_bytes, 0)
    assert magic == 0x46546C67, f"Bad glTF magic: {magic:#x}"
    assert version == 2

    json_len, json_type = struct.unpack_from("<II", glb_bytes, 12)
    assert json_type == 0x4E4F534A
    gltf = json.loads(glb_bytes[20:20 + json_len])

    bin_start = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", glb_bytes, bin_start)
    assert bin_type == 0x004E4942
    bin_data = glb_bytes[bin_start + 8:bin_start + 8 + bin_len]

    return gltf, bin_data


# --- pytest fixtures ---

@pytest.fixture
def triangle_bm3():
    data, vc, ic = _make_triangle()
    return data, vc, ic


@pytest.fixture
def triangle_byte_indices_bm3():
    data, vc, ic = _make_triangle(index_format="UNSIGNED_BYTE")
    return data, vc, ic


@pytest.fixture
def two_dg_bm3():
    data, vc, dg_counts = _make_two_drawing_groups()
    return data, vc, dg_counts


@pytest.fixture
def multi_vb_bm3():
    return _make_multi_vertex_buffer()


@pytest.fixture
def bm3mat_data():
    return _make_bm3mat()


@pytest.fixture
def default_material_bm3():
    return _make_default_material_bm3()


@pytest.fixture
def default_mat_bm3():
    return _make_default_material_bm3(mat_name="default_mat")
