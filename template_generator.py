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
# Bounding Box
# ==========================

def get_polygon_bounds(poly):
    """
    Calculate bounding box for a single polygon.
    Returns (min_x, min_y, max_x, max_y)
    """
    if not poly:
        return None
    
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    
    for x, y in poly:
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y
    
    return (min_x, min_y, max_x, max_y)

def get_part_bounds(part):
    """
    Calculate bounding box for a part (outer + all holes).
    Returns (min_x, min_y, max_x, max_y)
    """
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    
    # Check outer boundary
    outer = to_mm(part["outer"])
    bounds = get_polygon_bounds(outer)
    if bounds:
        min_x = min(min_x, bounds[0])
        min_y = min(min_y, bounds[1])
        max_x = max(max_x, bounds[2])
        max_y = max(max_y, bounds[3])
    
    # Check holes
    holes = part.get("holes", [])
    for hole in holes:
        hole_mm = to_mm(hole)
        bounds = get_polygon_bounds(hole_mm)
        if bounds:
            min_x = min(min_x, bounds[0])
            min_y = min(min_y, bounds[1])
            max_x = max(max_x, bounds[2])
            max_y = max(max_y, bounds[3])
    
    if min_x == float("inf"):
        return None
    
    return (min_x, min_y, max_x, max_y)

# ==========================
# Layout / Packing
# ==========================

def pack_parts(data, page_width=400.0, page_height=400.0, margin=5.0):
    """
    Pack multiple parts onto a page using a simple shelf-packing algorithm.
    Returns list of (part_index, offset_x, offset_y) tuples.
    """
    packed = []
    shelf_y = margin
    shelf_height = 0
    current_x = margin
    
    # Get bounds for all parts
    part_info = []
    for i, part in enumerate(data):
        bounds = get_part_bounds(part)
        if bounds:
            min_x, min_y, max_x, max_y = bounds
            width = max_x - min_x
            height = max_y - min_y
            part_info.append((i, width, height, min_x, min_y))
    
    # Sort by height (descending) for better packing
    part_info.sort(key=lambda x: x[2], reverse=True)
    
    # Pack each part
    for part_idx, width, height, local_min_x, local_min_y in part_info:
        # Check if part fits in current shelf
        if current_x + width + margin > page_width:
            # Start new shelf
            shelf_y += shelf_height + margin
            current_x = margin
            shelf_height = 0
        
        # Check if part fits on page vertically
        if shelf_y + height + margin > page_height:
            print(f"Warning: Part {part_idx} may not fit on page")
        
        # Calculate offset to position part at current_x, shelf_y
        # The offset should move the part's local min to the placement position
        offset_x = current_x - local_min_x
        offset_y = shelf_y - local_min_y
        
        packed.append((part_idx, offset_x, offset_y))
        
        current_x += width + margin
        shelf_height = max(shelf_height, height)
    
    return packed

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

def apply_offset(points, offset_x, offset_y):
    """
    Apply offset to a list of points.
    """
    return [(x + offset_x, y + offset_y) for x, y in points]

# ==========================
# Glue Tabs
# ==========================

def add_glue_tabs(polygon, glue_edges):
    """
    Add glue tabs to specified edges of a polygon.
    
    Args:
        polygon: List of (x, y) tuples representing polygon vertices
        glue_edges: List of edge indices (0-based) to add tabs to
    
    Returns:
        List of (x, y) tuples with glue tabs added
    """
    if not glue_edges or len(polygon) < 3:
        return polygon
    
    result = []
    n = len(polygon)
    
    for i in range(n):
        result.append(polygon[i])
        
        # Check if this edge needs a glue tab
        if i in glue_edges:
            p1 = polygon[i]
            p2 = polygon[(i + 1) % n]
            
            # Calculate edge vector
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            edge_length = math.sqrt(dx * dx + dy * dy)
            
            if edge_length > 0:
                # Normalize direction
                dx /= edge_length
                dy /= edge_length
                
                # Perpendicular vector (rotate 90 degrees)
                px = -dy
                py = dx
                
                # Tab points (add 3 points to create a rectangular tab)
                tab_depth = TAB_SIZE
                tab_width = TAB_SIZE
                
                # Start point on edge (offset from p1)
                start_offset = (edge_length - tab_width) / 2
                start_x = p1[0] + dx * start_offset
                start_y = p1[1] + dy * start_offset
                
                # Tab corners
                tab_corner1_x = start_x + dx * tab_width
                tab_corner1_y = start_y + dy * tab_width
                
                tab_outer_x = start_x + px * tab_depth
                tab_outer_y = start_y + py * tab_depth
                
                tab_corner2_x = tab_corner1_x + px * tab_depth
                tab_corner2_y = tab_corner1_y + py * tab_depth
                
                # Add tab vertices
                result.append((start_x, start_y))
                result.append((tab_outer_x, tab_outer_y))
                result.append((tab_corner2_x, tab_corner2_y))
                result.append((tab_corner1_x, tab_corner1_y))
    
    return result

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

    # Pack parts to compute layout
    packed_parts = pack_parts(data)
    
    # Build mapping of part index to offset
    part_offsets = {}
    for part_idx, offset_x, offset_y in packed_parts:
        part_offsets[part_idx] = (offset_x, offset_y)
    
    # Process each part with its offset
    for part_idx, part in enumerate(data):

        if part_idx not in part_offsets:
            continue
        
        offset_x, offset_y = part_offsets[part_idx]

        # Process outer boundary
        base = to_mm(part["outer"])
        base = apply_offset(base, offset_x, offset_y)

        if len(base) < 3:
            continue

        # Apply glue tabs if specified
        glue_edges = part.get("glue_edges", [])
        if glue_edges:
            base = add_glue_tabs(base, glue_edges)

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

        # Process holes
        holes = part.get("holes", [])
        for hole in holes:
            hole_mm = to_mm(hole)
            hole_mm = apply_offset(hole_mm, offset_x, offset_y)
            
            if len(hole_mm) >= 3:
                paths.append(polygon_to_path(hole_mm))
                
                for x, y in hole_mm:
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

    svg.append(svg_footer())

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
