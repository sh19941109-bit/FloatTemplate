import bpy
import bmesh
import os
from mathutils import Vector

# ============================================
# Settings
# ============================================

W = 1000
H = 1000

DESKTOP = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")

# ============================================
# Active Mesh
# ============================================

obj = bpy.context.active_object

if obj is None:
    raise RuntimeError("No active object.")

if obj.type != "MESH":
    raise RuntimeError("Active object is not a mesh.")

# ============================================
# Read Mesh
# ============================================

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()

uv_layer = bm.loops.layers.uv.active

if uv_layer is None:
    bm.free()
    raise RuntimeError("Mesh has no UV map.")

# ============================================
# Build UV BMesh
# ============================================

uv_bm = bmesh.new()

vert_map = {}
uv_face_to_normal = {}


def get_uv_vert(uv):

    key = (
        round(uv.x, 6),
        round(uv.y, 6),
    )

    if key not in vert_map:

        vert_map[key] = uv_bm.verts.new(
            (
                uv.x,
                uv.y,
                0.0,
            )
        )

    return vert_map[key]


for face in bm.faces:

    verts = []

    for loop in face.loops:

        verts.append(
            get_uv_vert(
                loop[uv_layer].uv
            )
        )

    try:

        uv_face = uv_bm.faces.new(verts)
        uv_face_to_normal[uv_face] = face.normal.copy()

    except ValueError:
        pass

bm.free()

uv_bm.verts.ensure_lookup_table()
uv_bm.edges.ensure_lookup_table()
uv_bm.faces.ensure_lookup_table()

# ============================================
# UV Island Detection
# ============================================


def find_uv_islands(faces):

    visited = set()
    islands = []

    for face in faces:

        if face in visited:
            continue

        island = []
        stack = [face]
        visited.add(face)

        while stack:

            current = stack.pop()
            island.append(current)

            for edge in current.edges:

                for linked in edge.link_faces:

                    if linked not in visited:

                        visited.add(linked)
                        stack.append(linked)

        islands.append(island)

    return islands


islands = find_uv_islands(uv_bm.faces)

print("UV islands:", len(islands))

# ============================================
# Boundary Extraction
# ============================================


def island_boundary_edges(island_faces):

    island_set = set(island_faces)
    boundary = []

    for face in island_faces:

        for edge in face.edges:

            linked_in_island = [
                linked
                for linked in edge.link_faces
                if linked in island_set
            ]

            if len(linked_in_island) == 1:

                if edge not in boundary:
                    boundary.append(edge)

    return boundary


def trace_boundary_loop(edges, start_edge):

    edge_map = {}

    for edge in edges:
        for vert in edge.verts:
            edge_map.setdefault(vert, []).append(edge)

    start_vert = start_edge.verts[0]

    loop = [start_vert]

    visited = set()

    current_vert = start_vert
    current_edge = start_edge

    while True:

        visited.add(current_edge)

        next_vert = (
            current_edge.verts[1]
            if current_edge.verts[0] == current_vert
            else current_edge.verts[0]
        )

        if next_vert == start_vert:
            break

        loop.append(next_vert)

        candidates = [
            e
            for e in edge_map[next_vert]
            if e != current_edge
        ]

        next_edge = None

        for e in candidates:
            if e not in visited:
                next_edge = e
                break

        if next_edge is None:
            break

        current_vert = next_vert
        current_edge = next_edge

    return loop, visited


def trace_all_boundary_loops(boundary_edges):

    remaining = set(boundary_edges)

    loops = []

    while remaining:

        edge = next(iter(remaining))

        loop, visited = trace_boundary_loop(
            list(remaining),
            edge,
        )

        remaining -= visited

        if len(loop) >= 3:
            loops.append(loop)

    return loops


def signed_area(loop):

    area = 0.0
    count = len(loop)

    for index in range(count):

        x1 = loop[index].co.x
        y1 = loop[index].co.y
        x2 = loop[(index + 1) % count].co.x
        y2 = loop[(index + 1) % count].co.y

        area += x1 * y2 - x2 * y1

    return area * 0.5


def classify_loops(loops):

    if not loops:
        return None, []

    scored = [
        (abs(signed_area(loop)), loop)
        for loop in loops
    ]

    for i, loop in enumerate(loops):
        print(f"loop {i+1}: area = {signed_area(loop)}")

    scored.sort(key=lambda item: item[0], reverse=True)

    outer = scored[0][1]
    holes = [loop for _, loop in scored[1:]]
    
    print("selected outer =", signed_area(outer))
    
    for i, h in enumerate(holes):
        print(f"selected hole {i+1} =", signed_area(h))

    return outer, holes



# ============================================
# SVG Path String
# ============================================


def loop_to_subpath(loop):

    area = signed_area(loop)

    # 外周は時計回り、穴は反時計回り
    if area > 0:
        loop = list(reversed(loop))

    first = loop[0].co

    parts = [
        f"M {first.x * W:.3f} {(1.0 - first.y) * H:.3f}",
    ]

    for vert in loop[1:]:
        parts.append(
            f"L {vert.co.x * W:.3f} {(1.0 - vert.co.y) * H:.3f}"
        )

    parts.append("Z")

    path = " ".join(parts)
    
    print("area =", area)
    print(path[:80])
    
    return path


def island_to_path_d(outer, holes):

    subpaths = [loop_to_subpath(outer)]

    for hole in holes:
        subpaths.append(loop_to_subpath(hole))
        
    return " ".join(subpaths)


def island_average_normal(island_faces):

    total = Vector((0.0, 0.0, 0.0))
    count = 0

    for face in island_faces:

        orig = uv_face_to_normal.get(face)

        if orig is None:
            continue

        total += orig
        count += 1

    if count == 0:
        return Vector((0.0, 0.0, 0.0))

    return total / count


def classify_panel(island_faces):

    normal = island_average_normal(island_faces)

    if normal.y >= 0.0:
        return "front"

    return "back"


# ============================================
# Build Panel Paths
# ============================================

panel_paths = {
    "front": [],
    "back": []
}

panel_json = {
    "front": [],
    "back": []
}

for index, island_faces in enumerate(islands):

    boundary_edges = island_boundary_edges(island_faces)

    print(
        f"Island {index + 1}: "
        f"faces={len(island_faces)}, "
        f"boundary_edges={len(boundary_edges)}"
    )

    loops = trace_all_boundary_loops(boundary_edges)

    print(f"  boundary loops: {len(loops)}")

    outer, holes = classify_loops(loops)

    print(type(outer[0]))
    print(type(holes[0][0]) if holes else "no holes")

    if outer is None:
        print(f"  skipped: no valid outer loop")
        continue

    print(f"  outer vertices: {len(outer)}")
    print(f"  holes: {len(holes)}")

    path_d = island_to_path_d(outer, holes)
    panel = classify_panel(island_faces)
    
    panel_paths[panel].append(path_d)
    
    # JSON用データを保存
    # JSON用データを保存（UV座標）
    panel_json[panel] = {

    "outer": [
        [
            v.co.x * W,
            (1.0 - v.co.y) * H
        ]
        for v in outer
    ],

    "holes": [
        [
            [
                v.co.x * W,
                (1.0 - v.co.y) * H
            ]
            for v in hole
        ]
        for hole in holes
    ],

    # ★追加
    "glue_edges": list(range(len(outer)))

}
    
    print(f"panel: {panel}")

# ==========================================
# Write SVG
# ==========================================

# ==========================================
# Add glue tab (5 mm offset)
# ==========================================

TAB_SIZE = 5.0  # mm

def add_glue_tab(path_d):
    # 今はダミー
    # 後でここへ5mmオフセット処理を書く
    return path_d


def write_panel_svg(filename, path_list):

    if not path_list:
        print(f"Warning: no paths for {filename}")
        path_list = [""]

    combined_d = " ".join(add_glue_tab(p) for p in path_list)

    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}">\n'
        f'  <path fill="#000000" fill-rule="evenodd" stroke="none" d="{combined_d}"/>\n'
        f'</svg>\n'
    )

    filepath = os.path.join(DESKTOP, filename)

    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(svg)

    print(f"Saved: {filepath}")
    
import json

def write_panel_json(filename, data):

    filepath = os.path.join(DESKTOP, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Saved: {filepath}")


write_panel_svg("front_panel.svg", panel_paths["front"])
write_panel_svg("back_panel.svg", panel_paths["back"])

write_panel_json("front_panel.json", panel_json["front"])
write_panel_json("back_panel.json", panel_json["back"])

uv_bm.free()

print("Done.")
