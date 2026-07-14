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

# ==========================
# SVG
# ==========================

def polygon_to_path(poly):

    if len(poly) < 3:
        return ""

    d = f"M {poly[0][0]:.3f} {poly[0][1]:.3f}"

    for x, y in poly[1:]:
        d += f" L {x:.3f} {y:.3f}"

    d += " Z"

    return d


def svg_header(min_x, min_y, width, height):

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
viewBox="{min_x:.3f} {min_y:.3f} {width:.3f} {height:.3f}"
width="{width:.3f}mm"
height="{height:.3f}mm">
'''


def svg_footer():

    return "</svg>\n"
def make_svg(data, filename):

    paths = []

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for part in data:

        base = to_mm(part["outer"])

        if len(base) < 3:
            continue

        paths.append(polygon_to_path(base))

        for x, y in base:

            if x < min_x:
                min_x = x

            if y < min_y:
                min_y = y

            if x > max_x:
                max_x = x

            if y > max_y:
                max_y = y

    margin = 5.0

    min_x -= margin
    min_y -= margin
    max_x += margin
    max_y += margin

    width = max_x - min_x
    height = max_y - min_y

    svg = []

    svg.append(
        svg_header(
            min_x,
            min_y,
            width,
            height
        )
    )

    for d in paths:

        svg.append(
            f'<path d="{d}" '
            'fill="none" '
            'stroke="black" '
            'stroke-width="0.2"/>\n'
        )
            svg.append(
        svg_footer()
    )

    with open(
        os.path.join(HERE, filename),
        "w",
        encoding="utf-8"
    ) as f:

        f.writelines(svg)

    print("Saved:", filename)


# ==========================
# Main
# ==========================

def main():

    make_svg(
        front,
        "front_panel.svg"
    )

    make_svg(
        back,
        "back_panel.svg"
    )


if __name__ == "__main__":

    main()
