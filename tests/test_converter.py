"""Tests for the BM3-to-GLB converter (no bpy dependency)."""

import struct

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bm3_importer import _extract_bm3, _bm3_to_glb
from tests.conftest import parse_glb


# ---------------------------------------------------------------------------
# Basic GLB output
# ---------------------------------------------------------------------------

def test_glb_magic_and_version(triangle_bm3):
    data, _, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)

    magic, version, length = struct.unpack_from("<III", glb, 0)
    assert magic == 0x46546C67
    assert version == 2
    assert length == len(glb)


def test_single_triangle(triangle_bm3):
    data, vc, ic = triangle_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)
    gltf, bin_data = parse_glb(glb)

    assert gltf["asset"]["version"] == "2.0"
    assert len(gltf["meshes"]) == 1
    assert len(gltf["meshes"][0]["primitives"]) == 1

    prim = gltf["meshes"][0]["primitives"][0]
    pos_acc = gltf["accessors"][prim["attributes"]["POSITION"]]
    assert pos_acc["count"] == vc

    idx_acc = gltf["accessors"][prim["indices"]]
    assert idx_acc["count"] == ic


# ---------------------------------------------------------------------------
# Index bounds validation
# ---------------------------------------------------------------------------

def test_index_bounds_valid(triangle_bm3):
    data, vc, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)
    gltf, bin_data = parse_glb(glb)

    for mesh in gltf["meshes"]:
        for prim in mesh["primitives"]:
            pos_count = gltf["accessors"][prim["attributes"]["POSITION"]]["count"]
            idx_acc = gltf["accessors"][prim["indices"]]
            idx_bv = gltf["bufferViews"][idx_acc["bufferView"]]
            idx_raw = bin_data[idx_bv["byteOffset"]:idx_bv["byteOffset"] + idx_bv["byteLength"]]

            fmt = "I" if idx_acc["componentType"] == 5125 else "H"
            indices = struct.unpack(f"<{idx_acc['count']}{fmt}", idx_raw)
            assert max(indices) < pos_count


# ---------------------------------------------------------------------------
# UNSIGNED_BYTE index promotion
# ---------------------------------------------------------------------------

def test_unsigned_byte_promotion(triangle_byte_indices_bm3):
    data, _, _ = triangle_byte_indices_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)
    gltf, bin_data = parse_glb(glb)

    prim = gltf["meshes"][0]["primitives"][0]
    idx_acc = gltf["accessors"][prim["indices"]]
    # glTF doesn't support UNSIGNED_BYTE for indices; should be promoted to UNSIGNED_SHORT (5123)
    assert idx_acc["componentType"] == 5123

    idx_bv = gltf["bufferViews"][idx_acc["bufferView"]]
    idx_raw = bin_data[idx_bv["byteOffset"]:idx_bv["byteOffset"] + idx_bv["byteLength"]]
    indices = struct.unpack(f"<{idx_acc['count']}H", idx_raw)
    assert indices == (0, 1, 2)


# ---------------------------------------------------------------------------
# Drawing groups
# ---------------------------------------------------------------------------

def test_drawing_group_slicing(two_dg_bm3):
    data, vc, dg_counts = two_dg_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)
    gltf, bin_data = parse_glb(glb)

    assert len(gltf["meshes"]) == 1
    prims = gltf["meshes"][0]["primitives"]
    assert len(prims) == 2

    for i, prim in enumerate(prims):
        idx_acc = gltf["accessors"][prim["indices"]]
        assert idx_acc["count"] == dg_counts[i]
        assert prim["mode"] == 4  # TRIANGLES


# ---------------------------------------------------------------------------
# Multiple vertex buffers (unsupported)
# ---------------------------------------------------------------------------

def test_multi_vertex_buffer_error(multi_vb_bm3):
    manifest, binary = _extract_bm3(multi_vb_bm3)
    with pytest.raises(ValueError, match="vertex buffers"):
        _bm3_to_glb(manifest, binary)


# ---------------------------------------------------------------------------
# BM3MAT material override
# ---------------------------------------------------------------------------

def test_bm3mat_override(default_material_bm3, bm3mat_data):
    manifest, binary = _extract_bm3(default_material_bm3)
    mat_manifest, mat_binary = _extract_bm3(bm3mat_data)

    glb = _bm3_to_glb(manifest, binary, mat_manifest, mat_binary)
    gltf, _ = parse_glb(glb)

    mat = gltf["materials"][0]
    # Should use override material values, not the defaults
    assert mat["name"] == "override_material"
    pbr = mat["pbrMetallicRoughness"]
    assert pbr["baseColorFactor"][1] == pytest.approx(0.9, abs=0.01)
    assert pbr["metallicFactor"] == pytest.approx(0.5)
    assert pbr["roughnessFactor"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# doubleSided geometry flag
# ---------------------------------------------------------------------------

def test_double_sided(triangle_bm3):
    data, _, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)

    # Enable doubleSided on the geometry
    manifest["geometries"][0]["doubleSided"] = True

    glb = _bm3_to_glb(manifest, binary)
    gltf, _ = parse_glb(glb)

    assert gltf["materials"][0]["doubleSided"] is True


def test_single_sided_by_default(triangle_bm3):
    data, _, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)
    glb = _bm3_to_glb(manifest, binary)
    gltf, _ = parse_glb(glb)

    assert "doubleSided" not in gltf["materials"][0]


# ---------------------------------------------------------------------------
# Converter logging / feedback
# ---------------------------------------------------------------------------

def test_log_summary_no_textures(triangle_bm3):
    data, _, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)
    log = []
    _bm3_to_glb(manifest, binary, log=log)

    messages = [msg for _, msg in log]
    # Should report 0 textures
    assert any("0 texture(s)" in m for m in messages)
    # Should report color-only material
    assert any("color-only" in m for m in messages)


def test_log_bm3mat_override(default_material_bm3, bm3mat_data):
    manifest, binary = _extract_bm3(default_material_bm3)
    mat_manifest, mat_binary = _extract_bm3(bm3mat_data)

    log = []
    _bm3_to_glb(manifest, binary, mat_manifest, mat_binary, log=log)

    messages = [msg for _, msg in log]
    assert any("overridden by BM3MAT" in m for m in messages)


def test_bm3mat_override_default_mat(default_mat_bm3, bm3mat_data):
    manifest, binary = _extract_bm3(default_mat_bm3)
    mat_manifest, mat_binary = _extract_bm3(bm3mat_data)

    glb = _bm3_to_glb(manifest, binary, mat_manifest, mat_binary)
    gltf, _ = parse_glb(glb)

    mat = gltf["materials"][0]
    assert mat["name"] == "override_material"
    pbr = mat["pbrMetallicRoughness"]
    assert pbr["baseColorFactor"][1] == pytest.approx(0.9, abs=0.01)
    assert pbr["metallicFactor"] == pytest.approx(0.5)
    assert pbr["roughnessFactor"] == pytest.approx(0.3)


def test_log_bm3mat_no_override(triangle_bm3, bm3mat_data):
    """BM3MAT loaded but material name doesn't match __GLTFLoader._default."""
    data, _, _ = triangle_bm3
    manifest, binary = _extract_bm3(data)
    mat_manifest, mat_binary = _extract_bm3(bm3mat_data)

    log = []
    _bm3_to_glb(manifest, binary, mat_manifest, mat_binary, log=log)

    levels_and_msgs = [(lvl, msg) for lvl, msg in log]
    # Should warn that BM3MAT was loaded but nothing overridden
    assert any(
        lvl == "WARNING" and "no materials were overridden" in msg
        for lvl, msg in levels_and_msgs
    )
