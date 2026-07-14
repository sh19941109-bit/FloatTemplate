import json
import math
import os

import pyclipper

# ==========================
# Settings
# ==========================

HERE = os.path.dirname(os.path.abspath(__file__))

MODEL_SIZE_MM = 400.0

TAB_SIZE = 5.0

CLIPPER_SCALE = 1000

# ==========================
# JSON
# ==========================

def load_json(filename):

    with open(os.path.join(HERE, filename), "r", encoding="utf-8") as f:
        return json.load(f)

front = load_json("front_panel.json")
back = load_json("back_panel.json")

print("front :", len(front))
for i, part in enumerate(front):
    print(i, len(part["outer"]), part["outer"][0])
print("back  :", len(back))

# ==========================
# Convert
# ==========================

# Blender UV(0～1) → mm

def to_mm(points):

    out = []

    for x, y in points:

        out.append((
            x * MODEL_SIZE_MM,
            (1.0 - y) * MODEL_SIZE_MM
        ))

    return out
# ==========================
# Offset
# ==========================

def polygon_area(poly):

    s = 0.0

    n = len(poly)

    for i in range(n):

        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]

        s += x1 * y2 - x2 * y1

    return s * 0.5


def make_tabs(poly):

    tabs = []

    ccw = polygon_area(poly) > 0

    n = len(poly)

    for i in range(n):

        p1 = poly[i]
        p2 = poly[(i + 1) % n]

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]

        L = math.hypot(dx, dy)

        if L < 10:
            continue

        ux = dx / L
        uy = dy / L

        if ccw:
            nx = uy
            ny = -ux
        else:
            nx = -uy
            ny = ux

        inset = min(5.0, L * 0.2)

        a = (
            p1[0] + ux * inset,
            p1[1] + uy * inset,
        )

        b = (
            p2[0] - ux * inset,
            p2[1] - uy * inset,
        )

        c = (
            b[0] + nx * TAB_SIZE,
            b[1] + ny * TAB_SIZE,
        )

        d = (
            a[0] + nx * TAB_SIZE,
            a[1] + ny * TAB_SIZE,
        )

        tabs.append([a, b, c, d])

    return tabs

# ==========================
# SVG Path
# ==========================

def polygon_to_path(poly):

    d = f"M {poly[0][0]} {poly[0][1]} "

    for x, y in poly[1:]:

        d += f"L {x} {y} "

    d += "Z"

    return d
# ==========================
# SVG Writer
# ==========================
import math

TAB_SIZE = 5.0      # mm
TAB_STEP = 20.0     # 20mm以上の辺だけ貼り代を付ける


import math

TAB_SIZE = 5.0

def normalize(x, y):
    l = math.hypot(x, y)
    if l == 0:
        return 0.0, 0.0
    return x / l, y / l


def polygon_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s * 0.5


def offset_polygon(poly, dist):

    ccw = polygon_area(poly) > 0

    result = []

    n = len(poly)

    for i in range(n):

        p0 = poly[(i - 1) % n]
        p1 = poly[i]
        p2 = poly[(i + 1) % n]

        dx1 = p1[0] - p0[0]
        dy1 = p1[1] - p0[1]

        dx2 = p2[0] - p1[0]
        dy2 = p2[1] - p1[1]

        dx1, dy1 = normalize(dx1, dy1)
        dx2, dy2 = normalize(dx2, dy2)

        if ccw:
            nx1, ny1 = dy1, -dx1
            nx2, ny2 = dy2, -dx2
        else:
            nx1, ny1 = -dy1, dx1
            nx2, ny2 = -dy2, dx2

        bx = nx1 + nx2
        by = ny1 + ny2

        bl = math.hypot(bx, by)

        if bl < 1e-6:

            bx = nx1
            by = ny1

        else:

            bx /= bl
            by /= bl

        result.append((
            p1[0] + bx * dist,
            p1[1] + by * dist
        ))

    return result

def make_svg(data, filename):

    paths = []

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for part in data:

        base = to_mm(part["outer"])

    paths.append(polygon_to_path(base))

    # 仮に貼り代を付ける辺
    GLUE_EDGES = {0}

    tabs = make_tabs(base)

    for i in GLUE_EDGES:

        if i < len(tabs):

            paths.append(
                polygon_to_path(tabs[i])
            )
        for x, y in base:

            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    margin = TAB_SIZE + 5

    min_x -= margin
    min_y -= margin
    max_x += margin
    max_y += margin

    width = max_x - min_x
    height = max_y - min_y

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{min_x} {min_y} {width} {height}" '
        f'width="{width}mm" height="{height}mm">'
    ]

    for d in paths:
        svg.append(
            f'<path d="{d}" '
            f'fill="none" '
            f'stroke="black" '
            f'stroke-width="0.2"/>'
        )

    svg.append("</svg>")

    with open(
        os.path.join(HERE, filename),
        "w",
        encoding="utf-8"
    ) as f:
        f.write("\n".join(svg))

    print("Saved:", filename)


make_svg(front, "front.svg")
make_svg(back, "back.svg")