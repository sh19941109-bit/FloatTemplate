"""Export closed front/back UV panel SVG and JSON files from the active Blender mesh.

The exporter builds topology in UV space, detects connected UV islands, extracts all
closed boundary rings (including holes), classifies panels from the source mesh
normals, and writes even-odd SVG paths plus matching JSON geometry.

Compatible with Blender 5.1/5.2 Python APIs.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from math import atan2
from typing import Iterable

import bmesh
import bpy
from mathutils import Vector

# ============================================
# Settings
# ============================================

W = 1000
H = 1000
UV_KEY_PRECISION = 6
EPSILON = 1.0e-9

DESKTOP = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
OUTPUT_DIR = DESKTOP if os.path.isdir(DESKTOP) else os.path.expanduser("~")


@dataclass(frozen=True)
class UVFace:
    """A source mesh face represented by quantized UV vertices."""

    index: int
    verts: tuple[tuple[float, float], ...]
    normal: Vector
    area: float


@dataclass(frozen=True)
class BoundaryLoop:
    """A closed ring in UV space."""

    vertices: tuple[tuple[float, float], ...]
    area: float


def uv_key(uv: Vector) -> tuple[float, float]:
    return (round(float(uv.x), UV_KEY_PRECISION), round(float(uv.y), UV_KEY_PRECISION))


def polygon_area(points: Iterable[tuple[float, float]]) -> float:
    pts = list(points)
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for idx, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(idx + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def panel_point(point: tuple[float, float]) -> list[float]:
    x, y = point
    return [x * W, (1.0 - y) * H]


def svg_point(point: tuple[float, float]) -> str:
    x, y = panel_point(point)
    return f"{x:.3f} {y:.3f}"


def read_uv_faces(obj: bpy.types.Object) -> list[UVFace]:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            raise RuntimeError("Mesh has no active UV map.")

        uv_faces: list[UVFace] = []
        for face in bm.faces:
            verts = tuple(uv_key(loop[uv_layer].uv) for loop in face.loops)
            unique_verts = tuple(dict.fromkeys(verts))
            area = polygon_area(unique_verts)
            if len(unique_verts) < 3 or abs(area) <= EPSILON:
                continue
            uv_faces.append(UVFace(face.index, unique_verts, face.normal.copy(), abs(area)))
        return uv_faces
    finally:
        bm.free()


def find_uv_islands(uv_faces: list[UVFace]) -> list[list[UVFace]]:
    """Find islands by exact UV edge connectivity, not by 3D mesh connectivity."""
    edge_to_faces: dict[tuple[tuple[float, float], tuple[float, float]], list[int]] = defaultdict(list)
    for face_idx, face in enumerate(uv_faces):
        for idx, vert in enumerate(face.verts):
            nxt = face.verts[(idx + 1) % len(face.verts)]
            edge_to_faces[tuple(sorted((vert, nxt)))].append(face_idx)

    neighbors: list[set[int]] = [set() for _ in uv_faces]
    for face_indices in edge_to_faces.values():
        if len(face_indices) < 2:
            continue
        for face_idx in face_indices:
            neighbors[face_idx].update(other for other in face_indices if other != face_idx)

    islands: list[list[UVFace]] = []
    visited: set[int] = set()
    for start_idx in range(len(uv_faces)):
        if start_idx in visited:
            continue
        queue: deque[int] = deque([start_idx])
        visited.add(start_idx)
        island: list[UVFace] = []
        while queue:
            face_idx = queue.popleft()
            island.append(uv_faces[face_idx])
            for neighbor_idx in neighbors[face_idx]:
                if neighbor_idx not in visited:
                    visited.add(neighbor_idx)
                    queue.append(neighbor_idx)
        islands.append(island)
    return islands


def boundary_edges(island: list[UVFace]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return oriented edges that are used by exactly one face in the UV island."""
    buckets: dict[tuple[tuple[float, float], tuple[float, float]], list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for face in island:
        for idx, vert in enumerate(face.verts):
            edge = (vert, face.verts[(idx + 1) % len(face.verts)])
            buckets[tuple(sorted(edge))].append(edge)
    return [edges[0] for edges in buckets.values() if len(edges) == 1]


def outgoing_angle(edge: tuple[tuple[float, float], tuple[float, float]]) -> float:
    (x1, y1), (x2, y2) = edge
    return atan2(y2 - y1, x2 - x1)


def extract_boundary_loops(edges: list[tuple[tuple[float, float], tuple[float, float]]]) -> list[BoundaryLoop]:
    """Trace all closed rings from boundary edges, preserving holes.

    Boundary edges from faces are oriented with the filled island interior on their
    left. Following those directed edges produces counter-clockwise outer rings and
    clockwise hole rings in UV coordinates. Branching/non-manifold UV boundaries are
    handled deterministically by taking the next unused outgoing edge with the
    smallest left turn.
    """
    outgoing: dict[tuple[float, float], list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for edge in edges:
        outgoing[edge[0]].append(edge)
    for start in outgoing:
        outgoing[start].sort(key=outgoing_angle)

    unused = set(edges)
    loops: list[BoundaryLoop] = []

    while unused:
        start_edge = next(iter(unused))
        current_edge = start_edge
        vertices: list[tuple[float, float]] = []
        seen_edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()

        while current_edge in unused and current_edge not in seen_edges:
            seen_edges.add(current_edge)
            unused.remove(current_edge)
            start, end = current_edge
            vertices.append(start)

            if end == start_edge[0]:
                break

            candidates = [edge for edge in outgoing.get(end, []) if edge in unused]
            if not candidates:
                break

            incoming_angle = atan2(start[1] - end[1], start[0] - end[0])
            current_edge = min(
                candidates,
                key=lambda edge: (outgoing_angle(edge) - incoming_angle) % (2.0 * 3.141592653589793),
            )

            if current_edge == start_edge:
                break

        if vertices and current_edge[1] == start_edge[0]:
            area = polygon_area(vertices)
            if len(vertices) >= 3 and abs(area) > EPSILON:
                loops.append(BoundaryLoop(tuple(vertices), area))

    return loops


def split_outer_and_holes(loops: list[BoundaryLoop]) -> tuple[BoundaryLoop | None, list[BoundaryLoop]]:
    if not loops:
        return None, []
    ordered = sorted(loops, key=lambda loop: abs(loop.area), reverse=True)
    return ordered[0], ordered[1:]


def loop_to_svg_subpath(loop: BoundaryLoop) -> str:
    points = loop.vertices
    first = points[0]
    segments = [f"M {svg_point(first)}"]
    segments.extend(f"L {svg_point(point)}" for point in points[1:])
    segments.append("Z")
    return " ".join(segments)


def island_to_path(outer: BoundaryLoop, holes: list[BoundaryLoop]) -> str:
    # One compound path with fill-rule=evenodd makes hole winding irrelevant and reliable.
    return " ".join(loop_to_svg_subpath(loop) for loop in [outer, *holes])


def classify_panel(island: list[UVFace]) -> str:
    weighted = Vector((0.0, 0.0, 0.0))
    for face in island:
        weighted += face.normal * face.area
    # Front/back panels in this template are separated by the sign of the mesh Y normal.
    # Ties are treated as front for deterministic output.
    return "front" if weighted.y >= 0.0 else "back"


def loop_json(loop: BoundaryLoop) -> list[list[float]]:
    return [panel_point(point) for point in loop.vertices]


def write_panel_svg(filename: str, paths: list[str]) -> None:
    combined_d = " ".join(paths)
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
        f'  <path fill="#000000" fill-rule="evenodd" stroke="none" d="{combined_d}"/>\n'
        '</svg>\n'
    )
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print(f"Saved: {filepath}")


def write_panel_json(filename: str, islands: list[dict[str, object]]) -> None:
    payload = {"width": W, "height": H, "islands": islands}
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(f"Saved: {filepath}")


def main() -> None:
    obj = bpy.context.active_object
    if obj is None:
        raise RuntimeError("No active object.")
    if obj.type != "MESH":
        raise RuntimeError("Active object is not a mesh.")

    uv_faces = read_uv_faces(obj)
    if not uv_faces:
        raise RuntimeError("Active mesh has no non-degenerate UV faces.")

    islands = find_uv_islands(uv_faces)
    print(f"UV islands: {len(islands)}")

    panel_paths: dict[str, list[str]] = {"front": [], "back": []}
    panel_json: dict[str, list[dict[str, object]]] = {"front": [], "back": []}

    for island_index, island in enumerate(islands, start=1):
        edges = boundary_edges(island)
        loops = extract_boundary_loops(edges)
        outer, holes = split_outer_and_holes(loops)
        print(
            f"Island {island_index}: faces={len(island)}, "
            f"boundary_edges={len(edges)}, boundary_loops={len(loops)}"
        )

        if outer is None:
            print(f"  skipped island {island_index}: no closed boundary loop")
            continue

        panel = classify_panel(island)
        panel_paths[panel].append(island_to_path(outer, holes))
        panel_json[panel].append(
            {
                "outer": loop_json(outer),
                "holes": [loop_json(hole) for hole in holes],
                "glue_edges": list(range(len(outer.vertices))),
                "source_face_indices": [face.index for face in island],
            }
        )
        print(f"  panel={panel}, outer_vertices={len(outer.vertices)}, holes={len(holes)}")

    write_panel_svg("front_panel.svg", panel_paths["front"])
    write_panel_svg("back_panel.svg", panel_paths["back"])
    write_panel_json("front_panel.json", panel_json["front"])
    write_panel_json("back_panel.json", panel_json["back"])
    print("Done.")


if __name__ == "__main__":
    main()
