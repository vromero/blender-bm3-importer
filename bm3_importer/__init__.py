import json
import struct
import zipfile
import tempfile
import os
import io

try:
    import bpy
    from bpy.props import StringProperty, CollectionProperty
    from bpy_extras.io_utils import ImportHelper
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


# ---------------------------------------------------------------------------
# BM3 format handling
# ---------------------------------------------------------------------------

def _extract_bm3(data):
    """Extract manifest.json and binary.bin from a BM3/BM3MAT ZIP archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        binary = zf.read("binary.bin")
    return manifest, binary


# ---------------------------------------------------------------------------
# BM3 -> GLB converter (pure Python, no external deps)
# ---------------------------------------------------------------------------

def _bm3_to_glb(manifest, binary, mat_manifest=None, mat_binary=None, log=None):
    if log is None:
        log = []

    gltf = {
        "asset": {"version": "2.0", "generator": "BM3 Importer for Blender"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "materials": [],
        "textures": [],
        "images": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
    }

    chunks = []
    current_offset = [0]

    def add_chunk(data):
        buf = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        padding = (4 - (len(buf) % 4)) % 4
        aligned = buf + b"\x00" * padding
        offset = current_offset[0]
        chunks.append(aligned)
        current_offset[0] += len(aligned)
        return offset, len(buf)

    texture_count = [0]

    def add_texture_from_source(tex_idx, src_manifest, src_binary, label="texture"):
        if tex_idx is None:
            return None
        textures = src_manifest.get("textures")
        images = src_manifest.get("images")
        if not textures or not images:
            log.append(("WARNING", f"{label}: source has no textures or images"))
            return None
        if tex_idx >= len(textures):
            log.append(("WARNING", f"{label}: texture index {tex_idx} out of range (source has {len(textures)})"))
            return None
        img_ref = textures[tex_idx].get("image")
        if img_ref is None or img_ref >= len(images):
            log.append(("WARNING", f"{label}: image reference missing or out of range"))
            return None
        img_info = images[img_ref]
        img_data = src_binary[img_info["byteOffset"]:img_info["byteOffset"] + img_info["byteLength"]]
        offset, length = add_chunk(img_data)

        bv_idx = len(gltf["bufferViews"])
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": length})

        img_idx = len(gltf["images"])
        mime = "image/jpeg" if img_info.get("format") == "jpg" else "image/png"
        gltf["images"].append({"bufferView": bv_idx, "mimeType": mime})

        tex_gltf_idx = len(gltf["textures"])
        gltf["textures"].append({"source": img_idx, "sampler": 0})
        texture_count[0] += 1
        return tex_gltf_idx

    # --- Materials ---
    _DEFAULT_MAT_NAMES = {"__GLTFLoader._default", "default_mat"}

    overridden_count = 0
    mat_count = len(manifest.get("materials", []))
    if mat_count == 0:
        log.append(("WARNING", "BM3 file contains no materials"))

    for i, bm3_mat in enumerate(manifest.get("materials", [])):
        mat_name = bm3_mat.get("name", f"material_{i}")
        is_overridden = mat_manifest is not None and mat_name in _DEFAULT_MAT_NAMES

        if mat_manifest is not None and not is_overridden:
            log.append(("INFO", f"Material '{mat_name}' not overridden (name not in {_DEFAULT_MAT_NAMES})"))

        if is_overridden:
            overridden_count += 1
            override_name = mat_manifest["materials"][0].get("name", "unnamed")
            log.append(("INFO", f"Material '{mat_name}' overridden by BM3MAT material '{override_name}'"))

        use_mat = mat_manifest["materials"][0] if is_overridden else bm3_mat
        tex_src = mat_manifest if is_overridden else manifest
        tex_bin = mat_binary if is_overridden else binary

        albedo = use_mat.get("albedo", {})
        albedo_val = albedo.get("value", [0.8, 0.8, 0.8])
        final_name = use_mat.get("name", f"material_{i}")

        gltf_mat = {
            "name": final_name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [albedo_val[0], albedo_val[1], albedo_val[2], 1.0],
                "metallicFactor": use_mat.get("metallic", {}).get("value", 0),
                "roughnessFactor": use_mat.get("roughness", {}).get("value", 1),
            },
        }

        src_label = "BM3MAT" if is_overridden else "BM3"
        for prop_name, gltf_key in [("albedo", "baseColorTexture"),
                                     ("roughness", "metallicRoughnessTexture")]:
            tex_id = use_mat.get(prop_name, {}).get("texture")
            if tex_id is not None:
                idx = add_texture_from_source(tex_id, tex_src, tex_bin,
                                              label=f"Material '{final_name}' {prop_name} ({src_label})")
                if idx is not None:
                    gltf_mat["pbrMetallicRoughness"][gltf_key] = {"index": idx}

        # Normal map
        tex_id = use_mat.get("normal", {}).get("texture")
        if tex_id is not None:
            idx = add_texture_from_source(tex_id, tex_src, tex_bin,
                                          label=f"Material '{final_name}' normal ({src_label})")
            if idx is not None:
                gltf_mat["normalTexture"] = {"index": idx}

        # Fallback: geometry-embedded roughness texture for non-overridden materials
        if not is_overridden and "metallicRoughnessTexture" not in gltf_mat["pbrMetallicRoughness"]:
            tex_id = bm3_mat.get("roughness", {}).get("texture")
            if tex_id is not None:
                idx = add_texture_from_source(tex_id, manifest, binary,
                                              label=f"Material '{final_name}' roughness fallback (BM3)")
                if idx is not None:
                    gltf_mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": idx}

        # Log texture summary for this material
        has_any_tex = (
            "baseColorTexture" in gltf_mat["pbrMetallicRoughness"]
            or "metallicRoughnessTexture" in gltf_mat["pbrMetallicRoughness"]
            or "normalTexture" in gltf_mat
        )
        if not has_any_tex:
            log.append(("INFO", f"Material '{final_name}' has no textures (color-only)"))

        gltf["materials"].append(gltf_mat)

    if mat_manifest is not None and overridden_count == 0:
        log.append(("WARNING",
                     "BM3MAT was loaded but no materials were overridden "
                     f"(no names matched {_DEFAULT_MAT_NAMES})"))

    # --- Geometries ---
    _MODE_MAP = {
        "POINTS": 0, "LINES": 1, "LINE_LOOP": 2, "LINE_STRIP": 3,
        "TRIANGLES": 4, "TRIANGLE_STRIP": 5, "TRIANGLE_FAN": 6,
    }

    geom_primitives = []  # list of lists: [(prim_attrs, iacc_idx, gltf_mode), ...]
    geom_double_sided = []  # per-geometry doubleSided flag
    for geom_idx, geom in enumerate(manifest.get("geometries", [])):
        layout_idx = geom.get("vertexLayout", 0)
        # vertexLayouts[idx] is an array of arrays: one attribute list per
        # vertex buffer.  Only single-buffer geometries are supported.
        vertex_layout = manifest["vertexLayouts"][layout_idx][0]
        bytes_per_vertex = sum(
            (4 if a["format"] == "FLOAT" else 2) * a["dimension"]
            for a in vertex_layout
        )

        if len(geom["vertexBuffers"]) > 1:
            raise ValueError(
                f"Geometry {geom_idx} has {len(geom['vertexBuffers'])} vertex "
                f"buffers; only 1 is currently supported"
            )

        vbuf_info = manifest["buffers"][geom["vertexBuffers"][0]]
        vertex_data = binary[vbuf_info["byteOffset"]:vbuf_info["byteOffset"] + vbuf_info["byteLength"]]
        vertex_count = vbuf_info["byteLength"] // bytes_per_vertex

        ibuf_info = manifest["buffers"][geom["indexBuffer"]]
        index_fmt = ibuf_info.get("format", "UNSIGNED_SHORT")
        index_size = {"UNSIGNED_INT": 4, "UNSIGNED_SHORT": 2, "UNSIGNED_BYTE": 1}[index_fmt]

        # Promote UNSIGNED_BYTE indices to UNSIGNED_SHORT (glTF doesn't support byte indices)
        if index_fmt == "UNSIGNED_BYTE":
            raw = binary[ibuf_info["byteOffset"]:ibuf_info["byteOffset"] + ibuf_info["byteLength"]]
            index_data = struct.pack(f"<{len(raw)}H", *raw)
            index_fmt = "UNSIGNED_SHORT"
            index_size = 2
        else:
            index_data = binary[ibuf_info["byteOffset"]:ibuf_info["byteOffset"] + ibuf_info["byteLength"]]

        v_offset, v_length = add_chunk(vertex_data)
        i_offset, i_length = add_chunk(index_data)

        # Build vertex attribute accessors (shared across all drawing groups)
        prim_attrs = {}
        attr_byte_offset = 0
        for attr in vertex_layout:
            fmt_size = 4 if attr["format"] == "FLOAT" else 2
            attr_byte_len = fmt_size * attr["dimension"]

            bv_idx = len(gltf["bufferViews"])
            gltf["bufferViews"].append({
                "buffer": 0,
                "byteOffset": v_offset + attr_byte_offset,
                "byteLength": v_length - attr_byte_offset,
                "byteStride": bytes_per_vertex,
            })

            comp_type = 5126 if attr["format"] == "FLOAT" else 5123
            acc_type = {2: "VEC2", 3: "VEC3", 4: "VEC4"}.get(attr["dimension"], "SCALAR")

            accessor = {
                "bufferView": bv_idx,
                "byteOffset": 0,
                "componentType": comp_type,
                "count": vertex_count,
                "type": acc_type,
            }

            if attr["attribute"] == "POSITION":
                mins = [float("inf")] * 3
                maxs = [float("-inf")] * 3
                for v in range(vertex_count):
                    base = v * bytes_per_vertex + attr_byte_offset
                    for d in range(3):
                        val = struct.unpack_from("<f", vertex_data, base + d * 4)[0]
                        mins[d] = min(mins[d], val)
                        maxs[d] = max(maxs[d], val)
                accessor["min"] = mins
                accessor["max"] = maxs

            acc_idx = len(gltf["accessors"])
            gltf["accessors"].append(accessor)

            attr_map = {
                "POSITION": "POSITION", "NORMAL": "NORMAL",
                "TEX_COORD_0": "TEXCOORD_0", "TEX_COORD_1": "TEXCOORD_1",
                "TANGENT": "TANGENT", "COLOR_0": "COLOR_0",
            }
            prim_attrs[attr_map.get(attr["attribute"], attr["attribute"])] = acc_idx
            attr_byte_offset += attr_byte_len

        # Build one primitive per drawing group
        idx_comp_type = 5125 if index_fmt == "UNSIGNED_INT" else 5123
        fmt_char = "I" if index_fmt == "UNSIGNED_INT" else "H"
        dg_primitives = []

        for dg in geom.get("drawingGroups", [{"start": 0, "count": len(index_data) // index_size, "mode": "TRIANGLES"}]):
            dg_start = dg["start"]
            dg_count = dg["count"]
            dg_byte_offset = dg_start * index_size
            dg_byte_length = dg_count * index_size

            # Validate index bounds
            dg_slice = index_data[dg_byte_offset:dg_byte_offset + dg_byte_length]
            indices = struct.unpack(f"<{dg_count}{fmt_char}", dg_slice)
            max_idx = max(indices) if indices else 0
            if max_idx >= vertex_count:
                raise ValueError(
                    f"Geometry {geom_idx}: index {max_idx} out of bounds "
                    f"(vertex count {vertex_count})"
                )

            ibv_idx = len(gltf["bufferViews"])
            gltf["bufferViews"].append({
                "buffer": 0,
                "byteOffset": i_offset + dg_byte_offset,
                "byteLength": dg_byte_length,
            })

            iacc_idx = len(gltf["accessors"])
            gltf["accessors"].append({
                "bufferView": ibv_idx, "byteOffset": 0,
                "componentType": idx_comp_type,
                "count": dg_count, "type": "SCALAR",
            })

            gltf_mode = _MODE_MAP.get(dg.get("mode", "TRIANGLES"), 4)
            dg_primitives.append((prim_attrs, iacc_idx, gltf_mode))

        geom_primitives.append(dg_primitives)
        geom_double_sided.append(geom.get("doubleSided", False))

    # --- Nodes ---
    for i, bm3_node in enumerate(manifest.get("nodes", [])):
        gltf_node = {"name": f"node_{i}"}
        if "matrix" in bm3_node:
            gltf_node["matrix"] = bm3_node["matrix"]
        if "children" in bm3_node:
            gltf_node["children"] = bm3_node["children"]

        if bm3_node.get("type") == "Mesh3D":
            mesh_idx = len(gltf["meshes"])
            primitives = []
            for geom_idx in bm3_node.get("geometries", []):
                if geom_double_sided[geom_idx]:
                    mat_idx = bm3_node.get("material")
                    if mat_idx is not None and mat_idx < len(gltf["materials"]):
                        gltf["materials"][mat_idx]["doubleSided"] = True
                for attrs, iacc, gltf_mode in geom_primitives[geom_idx]:
                    prim = {"attributes": attrs, "indices": iacc, "mode": gltf_mode}
                    mat_idx = bm3_node.get("material")
                    if mat_idx is not None and mat_idx < len(gltf["materials"]):
                        prim["material"] = mat_idx
                    primitives.append(prim)
            gltf["meshes"].append({
                "name": bm3_node.get("publication", f"mesh_{mesh_idx}"),
                "primitives": primitives,
            })
            gltf_node["mesh"] = mesh_idx

        gltf["nodes"].append(gltf_node)

    # Add a wrapper root node that converts mm to meters (scale 0.001).
    # BM3 uses millimeters; Blender / glTF expect meters.
    if "root" in manifest:
        wrapper_idx = len(gltf["nodes"])
        gltf["nodes"].append({
            "name": "root",
            "scale": [0.001, 0.001, 0.001],
            "children": [manifest["root"]],
        })
        gltf["scenes"][0]["nodes"] = [wrapper_idx]

    # --- Summary ---
    log.append(("INFO", f"Result: {len(gltf['materials'])} material(s), "
                f"{texture_count[0]} texture(s) embedded, "
                f"{len(gltf['meshes'])} mesh(es)"))

    # Clean up empty arrays
    for key in ("textures", "images", "samplers"):
        if not gltf.get(key):
            gltf.pop(key, None)
    if not gltf.get("textures"):
        gltf.pop("samplers", None)

    # --- Pack GLB ---
    bin_buf = b"".join(chunks)
    gltf["buffers"] = [{"byteLength": len(bin_buf)}]

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    json_chunk = json_bytes + b" " * json_pad

    bin_pad = (4 - (len(bin_buf) % 4)) % 4
    bin_chunk = bin_buf + b"\x00" * bin_pad

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray(total)
    struct.pack_into("<III", out, 0, 0x46546C67, 2, total)
    struct.pack_into("<II", out, 12, len(json_chunk), 0x4E4F534A)
    out[20:20 + len(json_chunk)] = json_chunk
    bin_start = 20 + len(json_chunk)
    struct.pack_into("<II", out, bin_start, len(bin_chunk), 0x004E4942)
    out[bin_start + 8:bin_start + 8 + len(bin_chunk)] = bin_chunk

    return bytes(out)


# ---------------------------------------------------------------------------
# Blender operator – import one or more BM3 files
# ---------------------------------------------------------------------------

def _find_bm3mat_files(directory):
    """Return a list of .BM3MAT files found in *directory*."""
    result = []
    if not directory or not os.path.isdir(directory):
        return result
    for entry in os.listdir(directory):
        if entry.upper().endswith(".BM3MAT"):
            result.append(os.path.join(directory, entry))
    return result


if _HAS_BPY:

    class IMPORT_OT_bm3(bpy.types.Operator, ImportHelper):
        """Import by.me BM3 geometry files, with optional BM3MAT material"""
        bl_idname = "import_scene.bm3"
        bl_label = "Import BM3"
        bl_options = {"REGISTER", "UNDO", "PRESET"}

        filter_glob: StringProperty(default="*.BM3;*.bm3", options={"HIDDEN"})  # type: ignore
        files: CollectionProperty(type=bpy.types.OperatorFileListElement)  # type: ignore
        directory: StringProperty(subtype="DIR_PATH")  # type: ignore

        auto_material: bpy.props.BoolProperty(
            name="Auto-detect material",
            description=(
                "Automatically apply any .BM3MAT file found next to "
                "the selected .BM3 files"
            ),
            default=True,
        )  # type: ignore

        def draw(self, context):
            layout = self.layout
            layout.prop(self, "auto_material")

        def execute(self, context):
            # Determine which files to import
            if self.files:
                paths = [os.path.join(self.directory, f.name)
                         for f in self.files if f.name]
            else:
                paths = [self.filepath]

            if not paths:
                self.report({"ERROR"}, "No files selected")
                return {"CANCELLED"}

            # Collects all messages for the popup and console
            all_log = []  # list of (level, message)

            # Auto-detect material file in the same directory
            mat_manifest = None
            mat_binary = None
            mat_file_name = None
            if self.auto_material:
                src_dir = os.path.dirname(paths[0])
                mat_files = _find_bm3mat_files(src_dir)
                if mat_files:
                    mat_path = mat_files[0]
                    mat_file_name = os.path.basename(mat_path)
                    try:
                        with open(mat_path, "rb") as f:
                            mat_manifest, mat_binary = _extract_bm3(f.read())
                        all_log.append(("INFO", f"Auto-loaded material: {mat_file_name}"))
                    except Exception as e:
                        all_log.append(("WARNING", f"Could not load material {mat_file_name}: {e}"))
                else:
                    all_log.append(("INFO", f"No .bm3mat files found in {src_dir}"))
            else:
                all_log.append(("INFO", "Material auto-detect is disabled"))

            imported = 0
            for path in paths:
                if not os.path.isfile(path):
                    continue
                name = os.path.splitext(os.path.basename(path))[0]
                all_log.append(("INFO", f"Converting: {name}"))

                try:
                    with open(path, "rb") as f:
                        manifest, binary = _extract_bm3(f.read())
                except Exception as e:
                    all_log.append(("WARNING", f"Could not read {name}: {e}"))
                    continue

                try:
                    convert_log = []
                    glb_data = _bm3_to_glb(manifest, binary, mat_manifest, mat_binary,
                                           log=convert_log)
                    for level, msg in convert_log:
                        all_log.append((level, f"[{name}] {msg}"))
                except Exception as e:
                    all_log.append(("WARNING", f"Could not convert {name}: {e}"))
                    continue

                tmp_path = os.path.join(tempfile.gettempdir(), f"_bm3_{name}.glb")
                try:
                    with open(tmp_path, "wb") as f:
                        f.write(glb_data)

                    before = set(bpy.data.objects)
                    result = bpy.ops.import_scene.gltf(filepath=tmp_path)
                    new_objects = set(bpy.data.objects) - before

                    for obj in new_objects:
                        if obj.parent is None:
                            obj.name = name

                    imported += 1
                except Exception as e:
                    all_log.append(("WARNING", f"Could not import {name}: {e}"))
                finally:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            all_log.append(("INFO", f"Imported {imported}/{len(paths)} BM3 file(s)"))

            # Print full log to Blender console
            print("\n" + "=" * 60)
            print("BM3 Import Report")
            print("=" * 60)
            for level, msg in all_log:
                print(f"  [{level}] {msg}")
            print("=" * 60 + "\n")

            # Forward to Blender's report system
            for level, msg in all_log:
                self.report({level}, msg)

            # Show popup summary
            has_warnings = any(lvl == "WARNING" for lvl, _ in all_log)
            _show_import_report(context, all_log, imported, len(paths),
                                mat_file_name, has_warnings)

            return {"FINISHED"} if imported > 0 else {"CANCELLED"}

    # -------------------------------------------------------------------
    # Import report popup
    # -------------------------------------------------------------------

    _import_report_lines = []

    def _show_import_report(context, all_log, imported, total, mat_file, has_warnings):
        lines = []
        lines.append(f"Files: {imported}/{total} imported successfully")
        if mat_file:
            lines.append(f"Material file: {mat_file}")
        else:
            lines.append("Material file: none found")
        lines.append("")

        for level, msg in all_log:
            if level == "WARNING":
                lines.append(f"WARNING: {msg}")
            elif "Result:" in msg or "overridden" in msg or "not overridden" in msg:
                lines.append(msg)
            elif "color-only" in msg or "no textures" in msg or "texture" in msg.lower():
                lines.append(msg)

        _import_report_lines.clear()
        _import_report_lines.extend(lines)

        title = "BM3 Import Report"
        if has_warnings:
            title += " (with warnings)"

        def draw_report(self, context):
            for line in _import_report_lines:
                row = self.layout.row()
                if line.startswith("WARNING:"):
                    row.alert = True
                row.label(text=line)

        context.window_manager.popup_menu(draw_report, title=title, icon="INFO")

    # -------------------------------------------------------------------
    # Registration
    # -------------------------------------------------------------------

    def menu_func_import(self, context):
        self.layout.operator(IMPORT_OT_bm3.bl_idname, text="ByMe BM3 (.bm3)")

    def register():
        bpy.utils.register_class(IMPORT_OT_bm3)
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    def unregister():
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        bpy.utils.unregister_class(IMPORT_OT_bm3)

    if __name__ == "__main__":
        register()
