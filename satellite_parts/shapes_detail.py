"""
Detail geometry (second level of every part). shapes.py builds the ENVELOPE: a simple, watertight hull that bounds the whole part; nesting and
packing use it. This file builds the DETAIL: the visible features (mounting ears, connectors, standoffs, chips, wall openings, bolt circles, lens
rings, weld bands, pipe stubs, valves, serpentine traces, cell busbars). Rule: every detail feature lies inside the envelope, so a bump or pipe
in the detail can never make a packed design infeasible; check_library.py verifies it.

detail_bodies(record, spec) returns [(name, color, Part), ...] or None (then the detail equals the envelope).
spec is the envelope spec after styling; record["detail_shape"] (optional) gives an explicit detail spec instead.
"""

import math
import re
import build123d as b
from shapes import bodies, ALUMINIUM, ANODIZED, STEEL, PCB, GOLD, COPPER, BLACK, WHITE, SOLAR, GLASS, TITANIUM, INSULATION, BRASS, plate_with_holes

DARK = (0.24, 0.26, 0.30)
SILVER = (0.80, 0.81, 0.83)


def _union(parts):
    result = None
    for part in parts:
        result = part if result is None else result + part
    return result


def _screw_heads(points, z_top, radius, height=0.6):
    return _union([b.Pos(px, py, z_top + height / 2 - 0.05) * b.Cylinder(radius, height) for px, py in points])


def _dsub(center, face, width, height, depth):
    """D-sub style connector on a box face: metal shell, dark insert, two jackscrew posts. face is "+x" or "+y"."""
    shell = b.Box(depth, width, height) if face == "+x" else b.Box(width, depth, height)
    insert = b.Box(depth * 0.6, width * 0.7, height * 0.55) if face == "+x" else b.Box(width * 0.7, depth * 0.6, height * 0.55)
    posts = []
    for side in (-1, 1):
        post = b.Cylinder(min(height, width) * 0.12, depth * 0.9).rotate(b.Axis.Y if face == "+x" else b.Axis.X, 90)
        posts.append(b.Pos(0, side * width * 0.42, 0) * post if face == "+x" else b.Pos(side * width * 0.42, 0, 0) * post)
    cx, cy, cz = center
    return b.Pos(cx, cy, cz) * shell, b.Pos(cx, cy, cz) * insert, b.Pos(cx, cy, cz) * _union(posts)


def module_box(x, y, z, **_):
    """Electronics unit: housing on two pairs of bolt-down feet, inset lid with corner screws, D-sub connector on +x, label plate on -y."""
    if min(x, y) < 25 or z < 8:
        body = b.Box(x, y, z)
        connector = b.Pos(x / 2 - 1.2, 0, 0) * b.Box(2.4, min(0.5 * y, 12), min(0.5 * z, 5))
        return bodies(("housing", ANODIZED, body - connector), ("connector", BLACK, connector))
    ear = min(6.0, 0.08 * x)
    foot_thickness = min(2.5, 0.15 * z)
    body_x = x - 2 * ear
    connector_depth = min(4.0, 0.06 * body_x)
    body_x_core = body_x - connector_depth
    body = b.Pos(-connector_depth / 2, 0, 0) * b.Box(body_x_core, y, z)
    feet = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            foot = b.Pos(sx * (x / 2 - ear), sy * y * 0.3, -z / 2 + foot_thickness / 2) * b.Box(2 * ear, min(0.2 * y, 14), foot_thickness)
            hole = b.Pos(sx * (x / 2 - ear / 2), sy * y * 0.3, -z / 2 + foot_thickness / 2) * b.Cylinder(min(1.7, ear * 0.25), foot_thickness + 1)
            feet.append(foot - hole)
    lid_height = min(1.2, z * 0.1)
    inset = min(2.5, 0.06 * min(body_x_core, y))
    lid = b.Pos(-connector_depth / 2, 0, z / 2 - lid_height / 2) * b.Box(body_x_core - 2 * inset, y - 2 * inset, lid_height)
    body = body - b.Pos(-connector_depth / 2, 0, z / 2 - lid_height / 2) * b.Box(body_x_core - 2 * inset + 0.2, y - 2 * inset + 0.2, lid_height + 0.01)
    screw_points = [(-connector_depth / 2 + sx * (body_x_core / 2 - inset - 3), sy * (y / 2 - inset - 3)) for sx in (-1, 1) for sy in (-1, 1)]
    screws = _screw_heads(screw_points, z / 2 - 0.55, min(1.4, 0.03 * min(x, y)), 0.5)
    connector_width = min(0.45 * y, 32.0)
    connector_height = min(0.45 * z, 12.0)
    shell, insert, posts = _dsub((body_x / 2 - connector_depth / 2 - 0.01, 0, -z * 0.05), "+x", connector_width, connector_height, connector_depth)
    label = b.Pos(-connector_depth / 2, -y / 2 + 0.15, z * 0.05) * b.Box(body_x_core * 0.4, 0.3, z * 0.3)
    return bodies(("housing", ANODIZED, body - label), ("feet", ANODIZED, _union(feet)), ("lid", SILVER, lid), ("screws", STEEL, screws), ("connector_shell", SILVER, shell - insert), ("connector_insert", BLACK, insert), ("jackscrews", STEEL, posts), ("label", WHITE, label))


def pc104_board(x=95.89, y=90.17, z=1.6, hole_diameter=3.2, components_height=0.0, **_):
    """PC/104-style board: PCB with mounting holes, stack standoffs at the holes, stack-through header, shielded section, ICs and an edge connector.
    Small boards (< 40 mm) get a pin header and one IC."""
    small = min(x, y) < 40
    inset = 4.57 if not small else max(1.0, 0.08 * min(x, y))
    hole = hole_diameter if not small else min(hole_diameter, 0.12 * min(x, y))
    holes = [(sx * (x / 2 - inset), sy * (y / 2 - inset)) for sx in (-1, 1) for sy in (-1, 1)]
    board = plate_with_holes(x, y, z, holes, hole, PCB)[0][2]
    result = [("pcb", PCB, board)]
    if components_height <= 0:
        return result
    top = z / 2
    if small:
        chip_height = components_height * 0.45
        chip = b.Pos(x * 0.12, 0, top + chip_height / 2) * b.Box(x * 0.32, y * 0.42, chip_height)
        header = b.Pos(-x / 2 + x * 0.12, 0, top + components_height / 2) * b.Box(x * 0.14, y * 0.55, components_height)
        passives = _union([b.Pos(x * 0.36, sy * y * 0.25, top + 0.3) * b.Box(x * 0.08, y * 0.1, 0.6) for sy in (-1, 1)])
        return result + [("ic", BLACK, chip), ("pin_header", BLACK, header), ("passives", (0.55, 0.45, 0.30), passives)]
    standoff_radius = min(2.6, inset * 0.55)
    standoffs = _union([b.Pos(hx, hy, top + components_height / 2) * (b.Cylinder(standoff_radius, components_height) - b.Cylinder(hole / 2 * 0.9, components_height + 1)) for hx, hy in holes])
    header_height = min(components_height, 11.0)
    header = b.Pos(0, -y / 2 + 2 * inset + 2.5, top + header_height / 2) * b.Box(x - 2 * (inset + 10), 5.0, header_height)
    pins = _union([b.Pos(-x / 2 + inset + 12 + index * (x - 2 * inset - 24) / 25, -y / 2 + 2 * inset + 2.5, top + header_height - 0.2) * b.Box(0.6, 3.0, 0.4) for index in range(26)])
    shield_height = max(1.5, min(components_height * 0.8, 9.0))
    shield = b.Pos(x * 0.17, y * 0.14, top + shield_height / 2) * b.Box(x * 0.42, y * 0.46, shield_height)
    chip_height = min(components_height, 1.8)
    chips = _union([b.Pos(cx, cy, top + chip_height / 2) * b.Box(min(x, y) * size, min(x, y) * size, chip_height) for cx, cy, size in ((-x * 0.24, y * 0.2, 0.16), (-x * 0.24, -y * 0.06, 0.10), (-x * 0.04, -y * 0.2, 0.08), (x * 0.24, -y * 0.24, 0.09))])
    passive_height = min(components_height, 0.8)
    passives = _union([b.Pos(-x * 0.36 + column * 4.0, y * 0.33 - row * 3.0, top + passive_height / 2) * b.Box(2.0, 1.2, passive_height) for column in range(5) for row in range(2)])
    connector_height = min(components_height, 6.0)
    connector = b.Pos(x / 2 - inset - 6, y * 0.25, top + connector_height / 2) * b.Box(9, 14, connector_height)
    return result + [("standoffs", BRASS, standoffs), ("stack_header", BLACK, header), ("header_pins", GOLD, pins), ("shield", SILVER, shield), ("ics", BLACK, chips), ("passives", (0.55, 0.45, 0.30), passives), ("connector", BLACK, connector)]


def reaction_wheel(x, y, z, flywheel_diameter=None, housing="box", **_):
    """Reaction wheel: square base or round flange with bolt holes, round sealed cover with a bolt circle, centre cap, connector with cable stub."""
    diameter = flywheel_diameter if flywheel_diameter is not None else min(x, y) * 0.9
    if housing == "round":
        flange_height = min(3.0, z * 0.15)
        base = b.Pos(0, 0, -z / 2 + flange_height / 2) * b.Box(x, y, flange_height)
        base_height = flange_height
    else:
        base_height = z * 0.4
        base = b.Pos(0, 0, -z / 2 + base_height / 2) * b.Box(x, y, base_height)
    lug = max(1.6, min(x, y) * 0.03)
    for sx in (-1, 1):
        for sy in (-1, 1):
            base = base - b.Pos(sx * (x / 2 - 2.2 * lug), sy * (y / 2 - 2.2 * lug), -z / 2 + base_height / 2) * b.Cylinder(lug, base_height + 1)
    cover_height = z - base_height - 0.8
    cover = b.Pos(0, 0, -z / 2 + base_height + cover_height / 2) * b.Cylinder(diameter / 2, cover_height)
    groove = b.Pos(0, 0, -z / 2 + base_height + cover_height * 0.55) * (b.Cylinder(diameter / 2 + 0.01, 0.6) - b.Cylinder(diameter / 2 - 0.5, 0.8))
    cover = cover - groove
    cap = b.Pos(0, 0, z / 2 - 0.4) * b.Cylinder(diameter * 0.18, 0.8)
    bolt_radius = diameter / 2 * 0.82
    bolts = _screw_heads([(bolt_radius * math.cos(angle), bolt_radius * math.sin(angle)) for angle in [index * math.pi / 4 for index in range(8)]], -z / 2 + base_height + cover_height - 0.05, max(0.6, diameter * 0.018), 0.5)
    connector_width = min(0.3 * y, 14)
    connector_height = min(base_height, 6.0) if housing != "round" else min(z * 0.35, 7.0)
    connector = b.Pos(x / 2 - 2.0, -y * 0.28, -z / 2 + base_height * 0.5 if housing != "round" else -z / 2 + flange_height + connector_height / 2) * b.Box(4.0, connector_width, connector_height)
    return bodies(("base", ANODIZED, base), ("cover", DARK, cover), ("cap", SILVER, cap), ("bolts", STEEL, bolts), ("connector", BLACK, connector))


def camera_box_lens(x, y, z, lens_diameter, lens_length, baffle_diameter=None, **_):
    """Camera / star tracker: mounting plate, housing with lid screws, lens barrel with grip rings and front glass, optional conical baffle with internal vanes, side connector."""
    plate_height = min(2.0, z * 0.12)
    plate = b.Pos(0, 0, -z / 2 + plate_height / 2) * b.Box(x, y, plate_height)
    holes = [(sx * (x / 2 - 2.5), sy * (y / 2 - 2.5)) for sx in (-1, 1) for sy in (-1, 1)]
    for hx, hy in holes:
        plate = plate - b.Pos(hx, hy, -z / 2 + plate_height / 2) * b.Cylinder(1.1, plate_height + 1)
    housing_x = x - 2 * min(4.0, 0.08 * x)
    housing_y = y - 2 * min(4.0, 0.08 * y)
    housing = b.Pos(0, 0, -z / 2 + plate_height + (z - plate_height) / 2) * b.Box(housing_x, housing_y, z - plate_height)
    screws = _screw_heads([(sx * (housing_x / 2 - 2.5), sy * (housing_y / 2 - 2.5)) for sx in (-1, 1) for sy in (-1, 1)], z / 2 - 0.55, 1.0, 0.5)
    result = [("mount_plate", SILVER, plate), ("housing", ANODIZED, housing), ("screws", STEEL, screws)]
    if baffle_diameter:
        cone = b.Pos(0, 0, z / 2) * b.Cone(lens_diameter / 2.0, baffle_diameter / 2.0, lens_length, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        bore = b.Pos(0, 0, z / 2 + 1.5) * b.Cone(lens_diameter / 2.0 - 1.5, baffle_diameter / 2.0 - 1.5, lens_length, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        baffle = cone - bore
        vanes = None
        for fraction in (0.35, 0.65, 0.9):
            radius = lens_diameter / 2 + (baffle_diameter - lens_diameter) / 2 * fraction
            vane = b.Pos(0, 0, z / 2 + lens_length * fraction) * (b.Cylinder(radius - 1.0, 0.8) - b.Cylinder(radius - 1.0 - max(1.5, radius * 0.12), 1.0))
            vanes = vane if vanes is None else vanes + vane
        glass = b.Pos(0, 0, z / 2 + 0.8) * b.Cylinder(lens_diameter * 0.4, 0.6)
        result += [("baffle", BLACK, baffle), ("baffle_vanes", BLACK, vanes), ("glass", GLASS, glass)]
    else:
        barrel = b.Pos(0, 0, z / 2 + lens_length / 2) * b.Cylinder(lens_diameter / 2.0 * 0.92, lens_length)
        rings = _union([b.Pos(0, 0, z / 2 + lens_length * fraction) * b.Cylinder(lens_diameter / 2.0, lens_length * 0.08) for fraction in (0.3, 0.55)])
        bezel = b.Pos(0, 0, z / 2 + lens_length - 0.6) * (b.Cylinder(lens_diameter / 2.0, 1.2) - b.Cylinder(lens_diameter * 0.36, 1.4))
        glass = b.Pos(0, 0, z / 2 + lens_length - 0.9) * b.Cylinder(lens_diameter * 0.36, 0.6)
        result += [("lens_barrel", BLACK, barrel), ("grip_rings", DARK, rings), ("bezel", SILVER, bezel), ("glass", GLASS, glass)]
    connector = b.Pos(housing_x / 2 + (x - housing_x) / 4, 0, -z / 2 + plate_height + min(0.3 * z, 6.0) / 2 + 1) * b.Box((x - housing_x) / 2 - 0.2, min(0.35 * housing_y, 14), min(0.3 * z, 6.0))
    result.append(("connector", BLACK, connector))
    return result


def lens_barrel(diameter, length, flange_diameter=None, flange_thickness=0.0, **_):
    """Optical tube (telescope / optical head): barrel with two stiffening rings, front bezel and glass, rear flange when given."""
    barrel = b.Cylinder(diameter / 2 * 0.94, length)
    rings = _union([b.Pos(0, 0, -length / 2 + length * fraction) * b.Cylinder(diameter / 2, length * 0.05) for fraction in (0.1, 0.5, 0.85)])
    bezel = b.Pos(0, 0, length / 2 - 0.8) * (b.Cylinder(diameter / 2, 1.6) - b.Cylinder(diameter * 0.38, 1.8))
    glass = b.Pos(0, 0, length / 2 - 1.2) * b.Cylinder(diameter * 0.38, 0.6)
    result = [("barrel", BLACK, barrel), ("rings", DARK, rings), ("bezel", SILVER, bezel), ("glass", GLASS, glass)]
    if flange_diameter:
        result.append(("flange", ALUMINIUM, b.Pos(0, 0, -length / 2 + flange_thickness / 2) * b.Cylinder(flange_diameter / 2.0, flange_thickness)))
    return result


def cubesat_frame(units_x=1, units_y=1, units_z=1, rail=8.5, wall=1.5, length_z=None, width_x=None, width_y=None, side="windows", **_):
    """CubeSat frame: hard-anodized (black) rails, aluminium end frames and mid rings, and side walls with one lightening opening per unit
    (side="windows": rounded rectangles, "circles": round holes as on the AAC ZAPHOD, "open": skeleton)."""
    width_x = width_x if width_x is not None else (226.3 if units_x == 2 else 100.0 * units_x)
    width_y = width_y if width_y is not None else (226.3 if units_y == 2 else 100.0 * units_y)
    length = length_z if length_z is not None else {1: 113.5, 2: 227.0, 3: 340.5}.get(units_z, 113.5 * units_z)
    positions_x = [-(width_x - rail) / 2, (width_x - rail) / 2]
    positions_y = [-(width_y - rail) / 2, (width_y - rail) / 2]
    rails = _union([b.Pos(px, py, 0) * b.Box(rail, rail, length) for px in positions_x for py in positions_y])
    end_height = min(rail, 6.0)
    frames = []
    for sz in (-1, 1):
        ring = b.Box(width_x - 0.4, width_y - 0.4, end_height) - b.Box(width_x - 2 * rail - 4, width_y - 2 * rail - 4, end_height + 2)
        frames.append(b.Pos(0, 0, sz * (length / 2 - rail - end_height / 2)) * ring)
    count = max(1, int(round(length / 100.0)))
    for index in range(1, count):
        z = -length / 2 + index * (length / count)
        frames.append(b.Pos(0, 0, z) * (b.Box(width_x - 0.4, width_y - 0.4, wall * 2) - b.Box(width_x - 2 * rail - 4, width_y - 2 * rail - 4, wall * 2 + 2)))
    if side != "open":
        inner = length - 2 * rail
        for axis, span, offset in (("x", width_y, width_x), ("y", width_x, width_y)):
            panel_span = span - 2 * rail + 0.4
            for sign in (-1, 1):
                position = sign * (offset / 2 - wall / 2 - 0.4)
                panel = b.Pos(position, 0, 0) * b.Box(wall, panel_span, inner) if axis == "x" else b.Pos(0, position, 0) * b.Box(panel_span, wall, inner)
                bays = [0.0] if span < 150 else [-span / 4, span / 4]
                bay_width = (panel_span / len(bays)) * 0.74
                for index in range(count):
                    cz = -inner / 2 + (index + 0.5) * inner / count
                    opening_height = (inner / count) * 0.7
                    for bay in bays:
                        if side == "circles":
                            cutter = b.Cylinder(min(bay_width, opening_height) / 2, wall + 4).rotate(b.Axis.Y if axis == "x" else b.Axis.X, 90)
                        else:
                            radius = min(bay_width, opening_height) * 0.2
                            core = b.Box(wall + 4, bay_width - 2 * radius, opening_height) + b.Box(wall + 4, bay_width, opening_height - 2 * radius) if axis == "x" else b.Box(bay_width - 2 * radius, wall + 4, opening_height) + b.Box(bay_width, wall + 4, opening_height - 2 * radius)
                            corners = []
                            for cy in (-1, 1):
                                for cz2 in (-1, 1):
                                    corner = b.Cylinder(radius, wall + 4).rotate(b.Axis.Y if axis == "x" else b.Axis.X, 90)
                                    corners.append(b.Pos(0, cy * (bay_width / 2 - radius), cz2 * (opening_height / 2 - radius)) * corner if axis == "x" else b.Pos(cy * (bay_width / 2 - radius), 0, cz2 * (opening_height / 2 - radius)) * corner)
                            cutter = core + _union(corners)
                        cutter = b.Pos(position, bay, cz) * cutter if axis == "x" else b.Pos(bay, position, cz) * cutter
                        panel = panel - cutter
                frames.append(panel)
    return bodies(("rails", BLACK, rails), ("frames", ALUMINIUM, _union(frames)))


def solar_panel(x, y, z, cells=None, cell_size=(40.0, 80.0), cell_height=0.4, **_):
    """Solar panel: black substrate with corner hold-down holes, cells with a silver busbar and interconnect tab each, harness connector on the back face."""
    substrate = b.Box(x, y, z)
    for sx in (-1, 1):
        for sy in (-1, 1):
            substrate = substrate - b.Pos(sx * (x / 2 - 3), sy * (y / 2 - 3), 0) * b.Cylinder(1.2, z + 1)
    if not cells:
        columns = max(1, int((x - 6) // (cell_size[0] + 2)))
        rows = max(1, int((y - 6) // (cell_size[1] + 2)))
        if columns * rows == 0 or x < 30 or y < 30:
            columns, rows = 0, 0
        cells = (columns, rows) if columns and rows else None
    result = [("substrate", (0.20, 0.20, 0.22), substrate)]
    if cells:
        columns, rows = cells
        pitch_x = (x - 6) / columns
        pitch_y = (y - 6) / rows
        cell_parts = []
        busbars = []
        for column in range(columns):
            for row in range(rows):
                cx = -x / 2 + 3 + pitch_x * (column + 0.5)
                cy = -y / 2 + 3 + pitch_y * (row + 0.5)
                cell_x = min(cell_size[0], pitch_x - 2)
                cell_y = min(cell_size[1], pitch_y - 2)
                cell_parts.append(b.Pos(cx, cy, z / 2 + cell_height / 2) * b.Box(cell_x, cell_y, cell_height))
                busbars.append(b.Pos(cx, cy + cell_y / 2 - 1.0, z / 2 + cell_height + 0.05) * b.Box(cell_x * 0.95, 0.8, 0.1))
                busbars.append(b.Pos(cx, cy - cell_y / 2 - 0.6, z / 2 + cell_height / 2) * b.Box(cell_x * 0.3, 1.0, cell_height))
        result += [("cells", SOLAR, _union(cell_parts)), ("busbars", SILVER, _union(busbars))]
    if z >= 1.5 and min(x, y) > 40:
        connector_height = min(z * 0.6, 3.0)
        connector = b.Pos(x * 0.3, 0, -z / 2 + connector_height / 2 - 0.01) * b.Box(12, 5, connector_height)
        result.append(("connector", BLACK, connector))
    return result


def battery_pack(x, y, z, cells=(2, 2), cell_diameter=18.4, cell_axis="x", **_):
    """Battery: housing with end plates and screws, cells visible in the top pocket, a balancing PCB strip along one side, harness connector."""
    end = min(4.0, 0.06 * x)
    housing = b.Box(x - 2 * end, y, z)
    columns, rows = cells
    cell_length = min(x - 2 * end - 4, 65.0)
    pitch_y = min(cell_diameter + 1.5, (y - 6) / max(rows, 1))
    radius = max(1.0, min(cell_diameter, pitch_y - 1) / 2.0)
    pocket_depth = min(z - 2.0, 2 * radius + 0.9)
    pocket = b.Pos(0, 0, z / 2 - pocket_depth / 2) * b.Box(cell_length + 2, pitch_y * rows + 1, pocket_depth)
    housing = housing - pocket
    cells_body = _union([b.Pos(0, -pitch_y * (rows - 1) / 2 + row * pitch_y, z / 2 - radius - 0.3) * b.Cylinder(radius, cell_length).rotate(b.Axis.Y, 90) for row in range(rows)])
    plates = _union([b.Pos(sx * (x / 2 - end / 2), 0, 0) * b.Box(end, y, z) for sx in (-1, 1)])
    screws = _union([b.Pos(sx * (x / 2 - end / 2), sy * (y / 2 - 3), z / 2 - 0.3) * b.Cylinder(1.0, 0.6) for sx in (-1, 1) for sy in (-1, 1)])
    connector = b.Pos(x / 2 - end / 2, 0, -z * 0.2) * b.Box(end + 0.01, min(12, y * 0.3), min(6, z * 0.3))
    return bodies(("housing", ANODIZED, housing), ("cells", (0.20, 0.45, 0.70), cells_body), ("end_plates", SILVER, plates - connector), ("screws", STEEL, screws), ("connector", BLACK, connector))


def thruster_box_nozzle(x, y, z, nozzle_diameter, nozzle_length, throat_diameter=None, nozzle_count=1, tank_diameter=None, **_):
    """Propulsion module: lower housing with lid screws and mounting feet, a top deck carrying the tank dome, valve blocks, feed tubes and an
    electronics box, conical nozzle(s) with throat on +z, side connector. Overall z = z + nozzle_length, all features inside."""
    throat = throat_diameter if throat_diameter is not None else nozzle_diameter * 0.3
    deck = min(2.0, z * 0.06)
    housing_height = z * 0.62
    housing = b.Pos(0, 0, -z / 2 + housing_height / 2) * b.Box(x - 4, y - 4, housing_height)
    feet = _union([b.Pos(sx * (x / 2 - 3), sy * (y / 2 - 3), -z / 2 + 1.5) * (b.Box(6, 6, 3) - b.Cylinder(1.2, 4)) for sx in (-1, 1) for sy in (-1, 1)])
    deck_plate = b.Pos(0, 0, -z / 2 + housing_height + deck / 2) * b.Box(x - 2, y - 2, deck)
    top = -z / 2 + housing_height + deck
    space = z / 2 - top
    tank = min(tank_diameter or min(x, y) * 0.5, min(x, y) - 6)
    tank_x = -min(x * 0.12, max(0.0, x / 2 - tank / 2 - 2))
    dome_height = min(space, tank * 0.45)
    dome = b.Pos(tank_x, 0, top) * (b.Sphere(tank / 2) - b.Pos(0, 0, -tank / 2) * b.Box(tank + 2, tank + 2, tank)) if tank / 2 <= space + 0.01 else b.Pos(tank_x, 0, top + dome_height / 2) * b.Cylinder(tank / 2, dome_height)
    if tank / 2 > space + 0.01:
        dome = b.Pos(tank_x, 0, top + dome_height / 2) * b.Cylinder(tank / 2, dome_height)
    valve_size = min(0.14 * min(x, y), 12.0)
    valve_height = min(space, valve_size)
    valves = _union([b.Pos(x * 0.32, sy * y * 0.25, top + valve_height / 2) * b.Box(valve_size, valve_size * 0.8, valve_height) for sy in (-1, 1)])
    tube_radius = max(0.8, min(x, y) * 0.012)
    tubes = _union([b.Pos(x * 0.1, sy * y * 0.25, top + min(space, valve_height) * 0.5) * b.Cylinder(tube_radius, x * 0.38).rotate(b.Axis.Y, 90) for sy in (-1, 1)])
    electronics = b.Pos(-x * 0.32, -y * 0.3, top + min(space, 8) / 2) * b.Box(x * 0.22, y * 0.25, min(space, 8))
    if nozzle_count == 4:
        offsets = [(sx * x * 0.3, sy * y * 0.3) for sx in (-1, 1) for sy in (-1, 1)]
    else:
        offsets = [(max(0.0, min(x * 0.22, x / 2 - nozzle_diameter / 2 - 1.0)), 0.0)]
    nozzles = []
    for ox, oy in offsets:
        cone = b.Pos(ox, oy, z / 2 + nozzle_length / 2) * (b.Cone(throat / 2.0, nozzle_diameter / 2.0, nozzle_length) - b.Pos(0, 0, 0.6) * b.Cone(throat / 2.0 * 0.6, nozzle_diameter / 2.0 - 0.6, nozzle_length))
        chamber = b.Pos(ox, oy, z / 2 - min(space, nozzle_diameter) / 2) * b.Cylinder(max(throat, nozzle_diameter * 0.35), min(space, nozzle_diameter))
        nozzles += [cone, chamber]
    lid_screws = _union([b.Pos(sx * (x / 2 - 6), sy * (y / 2 - 6), -z / 2 + housing_height + deck + 0.25) * b.Cylinder(1.0, 0.5) for sx in (-1, 1) for sy in (-1, 1)])
    connector = b.Pos(x / 2 - 2.5, -y * 0.2, -z / 2 + housing_height * 0.6) * b.Box(4.9, min(16, y * 0.25), min(8, housing_height * 0.3))
    return bodies(("housing", ANODIZED, housing), ("feet", ANODIZED, feet), ("deck", SILVER, deck_plate), ("tank_dome", TITANIUM, dome), ("valves", STEEL, valves), ("feed_tubes", STEEL, tubes), ("electronics", DARK, electronics), ("nozzles", TITANIUM, _union(nozzles)), ("screws", STEEL, lid_screws), ("connector", BLACK, connector))


def electric_thruster(x, y, z, emitter_diameter, emitter_length, **_):
    """Electric thruster (FEEP, ion, water/plasma): housing with a recessed front plate, emitter head with ring and bolt circle, corner screws, side connector."""
    body = b.Box(x, y, z)
    recess = b.Pos(0, 0, z / 2 - 0.5) * b.Box(x - 6, y - 6, 1.0)
    body = body - recess
    plate = b.Pos(0, 0, z / 2 - 0.5) * b.Box(x - 6.2, y - 6.2, 1.0)
    head = b.Pos(0, 0, z / 2 + emitter_length / 2) * b.Cylinder(emitter_diameter / 2.0, emitter_length)
    ring = b.Pos(0, 0, z / 2 + emitter_length - 0.4) * (b.Cylinder(emitter_diameter / 2.0, 0.8) - b.Cylinder(emitter_diameter * 0.3, 1.0))
    bolt_circle = emitter_diameter / 2 * 1.25
    bolts = _screw_heads([(bolt_circle * math.cos(angle), bolt_circle * math.sin(angle)) for angle in [index * math.pi / 3 for index in range(6)]], z / 2 - 0.05, 1.0, 0.5) if bolt_circle + 2 < min(x, y) / 2 - 3 else None
    corners = _screw_heads([(sx * (x / 2 - 6), sy * (y / 2 - 6)) for sx in (-1, 1) for sy in (-1, 1)], z / 2 - 0.05, 1.2, 0.5)
    connector = b.Pos(x / 2 - 1.5, 0, -z * 0.2) * b.Box(3.0, min(0.4 * y, 15.0), min(0.3 * z, 6.0))
    result = [("housing", SILVER, body - connector), ("front_plate", ANODIZED, plate), ("emitter", GOLD, head - ring), ("emitter_ring", STEEL, ring), ("corner_screws", STEEL, corners), ("connector", BLACK, connector)]
    if bolts is not None:
        result.append(("bolt_circle", STEEL, bolts))
    return result


def tank_spherical(diameter, boss_diameter=None, boss_length=0.0, **_):
    """Spherical tank (diaphragm or pressurant): shell, equatorial weld flange with four mounting lugs, two pole ports with elbow pipes; inside a diameter cube."""
    shell_diameter = diameter * 0.92
    shell = b.Sphere(shell_diameter / 2)
    flange = b.Cylinder(diameter * 0.47, max(2.0, diameter * 0.02)) - b.Cylinder(shell_diameter / 2 * 0.98, diameter * 0.03)
    lugs = _union([b.Pos(diameter * 0.46 * math.cos(angle), diameter * 0.46 * math.sin(angle), 0) * (b.Box(diameter * 0.08, diameter * 0.08, max(2.0, diameter * 0.02)) - b.Cylinder(diameter * 0.012, diameter * 0.05)) for angle in [math.pi / 4 + index * math.pi / 2 for index in range(4)]])
    port_radius = max(1.5, (boss_diameter or diameter * 0.06) / 2)
    stub_height = diameter / 2 - shell_diameter / 2 * 0.98
    ports = []
    for sz in (-1, 1):
        stub = b.Pos(0, 0, sz * (shell_diameter / 2 * 0.98 + stub_height / 2 - 0.5)) * b.Cylinder(port_radius, stub_height + 1)
        pipe_length = diameter * 0.3
        pipe = b.Pos(pipe_length / 2, 0, sz * (diameter / 2 - port_radius * 0.7)) * b.Cylinder(port_radius * 0.6, pipe_length).rotate(b.Axis.Y, 90)
        ports += [stub, pipe]
    return bodies(("shell", TITANIUM, shell), ("weld_flange", SILVER, flange + lugs), ("ports", STEEL, _union(ports)))


def tank_cylindrical(diameter, length, boss_diameter=None, **_):
    """Cylindrical tank: shell with domes, girth weld band, two mounting bands with feet, port boss and pipe at one end."""
    shell_diameter = diameter * 0.94
    straight = max(length - shell_diameter - diameter * 0.06, 0.1)
    shell = b.Cylinder(shell_diameter / 2, straight)
    for sz in (-1, 1):
        shell = shell + b.Pos(0, 0, sz * straight / 2) * b.Sphere(shell_diameter / 2)
    bands = _union([b.Pos(0, 0, sz * straight * 0.3) * (b.Cylinder(diameter / 2, diameter * 0.06) - b.Cylinder(shell_diameter / 2 * 0.99, diameter * 0.08)) for sz in (-1, 1)])
    weld = b.Cylinder(shell_diameter / 2 + 0.3, 1.0) - b.Cylinder(shell_diameter / 2 - 0.5, 1.2)
    boss = boss_diameter if boss_diameter is not None else diameter * 0.15
    port = b.Pos(0, 0, length / 2 - diameter * 0.03 - 0.5) * b.Cylinder(boss / 2.0, diameter * 0.06 + 1)
    return bodies(("shell", TITANIUM, shell), ("mount_bands", SILVER, bands), ("weld", STEEL, weld), ("port", STEEL, port))


def heater_foil(x, y, z, **_):
    """Polyimide foil heater: amber film with an etched serpentine copper element and two lead pads at one end."""
    film = b.Box(x, y, z)
    margin = min(x, y) * 0.12
    lead_zone = min(x * 0.15, 8.0)
    strips = max(3, min(9, int((y - 2 * margin) / 2.5)))
    pitch = (y - 2 * margin) / strips
    trace_height = z * 0.4
    run = x - 2 * margin - lead_zone
    trace = []
    for index in range(strips):
        cy = -y / 2 + margin + pitch * (index + 0.5)
        trace.append(b.Pos(lead_zone / 2, cy, z / 2 - trace_height / 2) * b.Box(run, pitch * 0.45, trace_height))
    for index in range(strips - 1):
        end_x = lead_zone / 2 + (run / 2 if index % 2 == 0 else -run / 2)
        trace.append(b.Pos(end_x, -y / 2 + margin + pitch * (index + 1), z / 2 - trace_height / 2) * b.Box(pitch * 0.45, pitch, trace_height))
    trace = _union(trace)
    pads = _union([b.Pos(-x / 2 + lead_zone / 2 + 0.5, sy * y * 0.2, z / 2 - trace_height / 2) * b.Box(lead_zone * 0.7, y * 0.16, trace_height) for sy in (-1, 1)])
    return bodies(("film", INSULATION, film - trace - pads), ("element", COPPER, trace), ("lead_pads", SILVER, pads))


def patch_antenna(x, y, z, patch_inset=8.0, patch_height=1.0, grid=None, **_):
    """Patch antenna or array: ground plate with corner holes, radome-coloured substrate, one patch per element with a feed via, connector under the plate."""
    base_height = z
    base = b.Box(x, y, base_height)
    for sx in (-1, 1):
        for sy in (-1, 1):
            base = base - b.Pos(sx * (x / 2 - 3), sy * (y / 2 - 3), 0) * b.Cylinder(1.3, base_height + 1)
    columns, rows = grid if grid else (1, 1)
    pitch_x = (x - 2 * patch_inset) / columns
    pitch_y = (y - 2 * patch_inset) / rows
    patches = []
    feeds = []
    for column in range(columns):
        for row in range(rows):
            cx = -x / 2 + patch_inset + pitch_x * (column + 0.5)
            cy = -y / 2 + patch_inset + pitch_y * (row + 0.5)
            size_x = pitch_x * (0.62 if columns > 1 else 1.0)
            size_y = pitch_y * (0.62 if rows > 1 else 1.0)
            patches.append(b.Pos(cx, cy, z / 2 + patch_height / 2) * b.Box(size_x, size_y, patch_height))
            feeds.append(b.Pos(cx + size_x * 0.2, cy, z / 2 + patch_height + 0.05) * b.Cylinder(min(size_x, size_y) * 0.04 + 0.3, 0.1))
    return bodies(("ground_plate", WHITE, base), ("patches", COPPER, _union(patches)), ("feeds", SILVER, _union(feeds)))


def connector_block(x, y, z, **_):
    """Micro-D / D-sub style connector: plated shell with two flange ears and mounting holes, dark insulator, contact cavities."""
    flange_height = min(1.0, z * 0.2)
    flange = b.Pos(0, 0, -z / 2 + flange_height / 2) * b.Box(x, y, flange_height)
    for sx in (-1, 1):
        flange = flange - b.Pos(sx * (x / 2 - min(2.0, x * 0.08)), 0, -z / 2 + flange_height / 2) * b.Cylinder(min(0.8, y * 0.12), flange_height + 1)
    shell = b.Pos(0, 0, -z / 2 + flange_height + (z - flange_height) / 2) * b.Box(x * 0.72, y * 0.78, z - flange_height)
    insulator = b.Pos(0, 0, z / 2 - 0.3) * b.Box(x * 0.62, y * 0.6, 0.6)
    contacts = max(2, int(x * 0.62 / 1.3))
    cavities = _union([b.Pos(-x * 0.31 + (index + 0.5) * x * 0.62 / contacts, sy * y * 0.12, z / 2 - 0.35) * b.Cylinder(0.25, 0.8) for index in range(contacts) for sy in (-1, 1)])
    return bodies(("flange", SILVER, flange), ("shell", SILVER, shell - insulator), ("insulator", BLACK, insulator - cavities), ("contacts", GOLD, cavities))


def sun_sensor(x, y, z, aperture_diameter=None, **_):
    """Sun sensor: housing with recessed aperture window and mask, corner screws, side connector."""
    aperture = aperture_diameter if aperture_diameter is not None else min(x, y) * 0.3
    body = b.Box(x, y, z)
    recess = b.Pos(0, 0, z / 2 - 0.4) * b.Box(min(x, y) * 0.6, min(x, y) * 0.6, 0.8)
    window = b.Pos(0, 0, z / 2 - 0.6) * b.Cylinder(aperture / 2.0, 0.4)
    screws = _screw_heads([(sx * (x / 2 - 2), sy * (y / 2 - 2)) for sx in (-1, 1) for sy in (-1, 1)], z / 2 - 0.45, min(0.9, min(x, y) * 0.05), 0.4)
    connector = b.Pos(x / 2 - 1.0, 0, -z * 0.15) * b.Box(2.0, min(0.4 * y, 10.0), min(0.4 * z, 4.0))
    return bodies(("housing", ANODIZED, body - recess - connector), ("mask", BLACK, recess - window), ("window", GLASS, window), ("screws", STEEL, screws), ("connector", BLACK, connector))


def torquer_rod(x, y, z, **_):
    """Magnetorquer rod along the long axis: wound coil, end caps, two mounting clamps, lead wires; fits the x by y by z envelope."""
    length = max(x, y, z)
    width = sorted((x, y, z))[0]
    coil_length = length * 0.82
    radius = width / 2 * 0.8
    coil = b.Cylinder(radius, coil_length).rotate(b.Axis.Y, 90)
    windings = _union([b.Pos(-coil_length / 2 + coil_length * (index + 0.5) / 12, 0, 0) * b.Cylinder(radius * 1.0 + 0.01, coil_length / 30).rotate(b.Axis.Y, 90) for index in range(12)])
    caps = _union([b.Pos(sx * (length / 2 - (length - coil_length) / 4), 0, 0) * b.Cylinder(radius * 0.85, (length - coil_length) / 2).rotate(b.Axis.Y, 90) for sx in (-1, 1)])
    clamps = _union([b.Pos(sx * coil_length * 0.32, 0, 0) * (b.Box(min(6.0, length * 0.05), width, width) - b.Cylinder(radius * 1.01, width).rotate(b.Axis.Y, 90)) for sx in (-1, 1)])
    result = bodies(("coil", COPPER, coil), ("windings", (0.62, 0.38, 0.16), windings), ("end_caps", BLACK, caps), ("clamps", SILVER, clamps))
    order = sorted(range(3), key=lambda axis: (x, y, z)[axis])
    if order[2] == 1:
        result = [(name, color, part.rotate(b.Axis.Z, 90)) for name, color, part in result]
    elif order[2] == 2:
        result = [(name, color, part.rotate(b.Axis.Y, 90)) for name, color, part in result]
    return result


def rod_with_driver(x, y, z, rod_diameter, board_x, board_y, board_z, **_):
    """Magnetorquer rod with clamp feet and its driver board beside it."""
    rod_y = -y / 2 + rod_diameter / 2 + 2.0
    rod = b.Pos(0, rod_y, z / 2 - rod_diameter / 2) * b.Cylinder(rod_diameter / 2, x * 0.96).rotate(b.Axis.Y, 90)
    caps = _union([b.Pos(sx * (x / 2 - x * 0.01), rod_y, z / 2 - rod_diameter / 2) * b.Cylinder(rod_diameter / 2 * 0.8, x * 0.02).rotate(b.Axis.Y, 90) for sx in (-1, 1)])
    clamps = _union([b.Pos(sx * x * 0.3, rod_y, -z / 2 + (z - rod_diameter / 2) / 2) * (b.Box(8, rod_diameter + 4, z - rod_diameter / 2) - b.Pos(0, 0, (z - rod_diameter / 2) / 2) * b.Cylinder(rod_diameter / 2, 9).rotate(b.Axis.Y, 90)) for sx in (-1, 1)])
    board = b.Pos(0, y / 2 - board_y / 2, -z / 2 + board_z / 2) * b.Box(board_x, board_y, board_z)
    return bodies(("coil", COPPER, rod), ("end_caps", BLACK, caps), ("clamps", (0.25, 0.45, 0.80), clamps), ("driver_board", (0.30, 0.55, 0.85), board))


def box_with_ears(x, y, z, ear_length, ear_thickness=3.0, ear_width=None, hole_diameter=3.4, color=None, **_):
    """Sensor housing with two bolt-down ears on -x and +x, a glass window and a rear connector."""
    body_x = x - 2 * ear_length
    ear_width = ear_width or 0.4 * y
    body = b.Box(body_x, y, z)
    ears = _union([b.Pos(sx * (body_x / 2 + ear_length / 2), 0, -z / 2 + ear_thickness / 2) * (b.Box(ear_length + 0.2, ear_width, ear_thickness) - b.Pos(sx * ear_length * 0.1, 0, 0) * b.Cylinder(hole_diameter / 2, ear_thickness + 1)) for sx in (-1, 1)])
    window = b.Pos(0, 0, z / 2 - 0.4) * b.Box(0.45 * body_x, 0.45 * y, 0.8)
    connector = b.Pos(0, -y / 2 + 2.0, -z * 0.1) * b.Box(body_x * 0.35, 4.0, z * 0.4)
    housing_color = tuple(color) if color else GOLD
    return bodies(("housing", housing_color, body - window - connector), ("ears", housing_color, ears), ("window", GLASS, window), ("connector", SILVER, connector))


def wheel_pyramid(x, y, z, base_thickness=5.0, **_):
    """Four reaction wheels on a pyramid bracket: base plate and four wheel housings leaning 20 deg inward, with round covers."""
    base = b.Pos(0, 0, -z / 2 + base_thickness / 2) * b.Box(x, y, base_thickness)
    wheel = min(x, y) * 0.42
    height = z - base_thickness
    tilt = math.radians(20)
    block_height = max(5.0, (height - wheel * math.sin(tilt)) / math.cos(tilt))
    wheels = []
    for sx, sy, axis, sign in ((-1, 0, b.Axis.Y, 1), (1, 0, b.Axis.Y, -1), (0, -1, b.Axis.X, -1), (0, 1, b.Axis.X, 1)):
        block = b.Box(wheel, wheel, block_height * 0.7) + b.Pos(0, 0, block_height * 0.35) * b.Cylinder(wheel * 0.45, block_height * 0.3 - 0.01)
        block = block.rotate(axis, sign * 20)
        bbox = block.bounding_box()
        shift_x = (x / 2 - 1.0 - bbox.max.X) if sx > 0 else (-x / 2 + 1.0 - bbox.min.X) if sx < 0 else 0.0
        shift_y = (y / 2 - 1.0 - bbox.max.Y) if sy > 0 else (-y / 2 + 1.0 - bbox.min.Y) if sy < 0 else 0.0
        block = b.Pos(shift_x, shift_y, -z / 2 + base_thickness - bbox.min.Z) * block
        wheels.append(block)
    return bodies(("bracket", SILVER, base), ("wheels", BLACK, _union(wheels)))


def wheel_pyramid_round(x, y, z, base_thickness=4.0, tilt_deg=20, **_):
    """Four round reaction wheels on a square plate, one per side, axes pointing outward and tilted upward by tilt_deg (NanoAvionics 4RW0 style)."""
    base = b.Pos(0, 0, -z / 2 + base_thickness / 2) * b.Box(x, y, base_thickness)
    height = z - base_thickness
    thickness = min(x, y) * 0.2
    diameter = min((height - thickness * math.sin(math.radians(tilt_deg))) / math.cos(math.radians(tilt_deg)), min(x, y) * 0.5)
    housings = []
    covers = []
    for sx, sy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        housing = b.Cylinder(diameter / 2, thickness)
        cover = b.Pos(0, 0, thickness / 2 + 0.5) * b.Cylinder(diameter * 0.3, 1.0)
        if sx != 0:
            housing = housing.rotate(b.Axis.Y, sx * (90 - tilt_deg))
            cover = cover.rotate(b.Axis.Y, sx * (90 - tilt_deg))
        else:
            housing = housing.rotate(b.Axis.X, -sy * (90 - tilt_deg))
            cover = cover.rotate(b.Axis.X, -sy * (90 - tilt_deg))
        both = housing + cover
        bbox = both.bounding_box()
        shift_x = (x / 2 - 0.5 - bbox.max.X) if sx > 0 else (-x / 2 + 0.5 - bbox.min.X) if sx < 0 else 0.0
        shift_y = (y / 2 - 0.5 - bbox.max.Y) if sy > 0 else (-y / 2 + 0.5 - bbox.min.Y) if sy < 0 else 0.0
        shift_z = -z / 2 + base_thickness - bbox.min.Z
        housings.append(b.Pos(shift_x, shift_y, shift_z) * housing)
        covers.append(b.Pos(shift_x, shift_y, shift_z) * cover)
    return bodies(("plate", (0.55, 0.52, 0.45), base), ("wheels", SILVER, _union(housings)), ("covers", (0.7, 0.72, 0.74), _union(covers)))

DETAIL_BUILDERS = {
    "module_box": module_box, "pc104_board": pc104_board, "reaction_wheel": reaction_wheel, "camera_box_lens": camera_box_lens, "lens_barrel": lens_barrel,
    "cubesat_frame": cubesat_frame, "solar_panel": solar_panel, "battery_pack": battery_pack, "thruster_box_nozzle": thruster_box_nozzle,
    "electric_thruster": electric_thruster, "tank_spherical": tank_spherical, "tank_cylindrical": tank_cylindrical, "heater_foil": heater_foil,
    "patch_antenna": patch_antenna, "connector_block": connector_block, "sun_sensor": sun_sensor, "torquer_rod_box": torquer_rod,
    "rod_with_driver": rod_with_driver, "box_with_ears": box_with_ears, "wheel_pyramid": wheel_pyramid, "wheel_pyramid_round": wheel_pyramid_round,
}


def detail_spec(record, spec):
    """The detail spec for a part: record["detail_shape"] when given, else the envelope spec with context from the record."""
    if record.get("detail_shape"):
        return dict(record["detail_shape"])
    spec = dict(spec)
    kind = spec.get("kind")
    subcategory = record.get("subcategory", "")
    if kind in ("box", "module_box") and subcategory in ("magnetorquer", "torquer_rod") and max(spec["x"], spec["y"], spec["z"]) > 2.5 * sorted((spec["x"], spec["y"], spec["z"]))[1]:
        return {"kind": "torquer_rod_box", "x": spec["x"], "y": spec["y"], "z": spec["z"]}
    if kind == "sphere" and record.get("category") == "propulsion":
        return {"kind": "tank_spherical", "diameter": spec["diameter"]}
    if kind == "patch_antenna" and not spec.get("grid"):
        match = re.search(r"(?<!\d)([1-8])\s*x\s*([1-8])(?![\d.])(?!\s*U)", str(record.get("model", "")) + " " + str(record.get("name", "")))
        if match:
            spec["grid"] = (int(match.group(1)), int(match.group(2)))
    if kind == "cubesat_frame" and not spec.get("side"):
        name = (str(record.get("vendor", "")) + " " + str(record.get("model", ""))).lower()
        spec["side"] = "circles" if "zaphod" in name else "windows"
    return spec


def detail_bodies(record, spec):
    spec = detail_spec(record, spec)
    builder = DETAIL_BUILDERS.get(spec.get("kind"))
    if builder is None:
        return None
    arguments = dict(spec)
    arguments.pop("kind")
    arguments.pop("tolerance", None)
    return builder(**arguments)


def baffle_cone(diameter, length, **_):
    """Star tracker sun baffle: conical shell from about 55 % of the outer diameter at the mounting flange to the full diameter, with internal vanes."""
    root = diameter * 0.55
    shell = b.Cone(root / 2, diameter / 2, length) - b.Pos(0, 0, 1.2) * b.Cone(root / 2 - 1.2, diameter / 2 - 1.2, length)
    flange = b.Pos(0, 0, -length / 2 + 1.0) * (b.Cylinder(root / 2 + 6, 2.0) - b.Cylinder(root / 2 - 1.2, 2.2))
    vanes = _union([b.Pos(0, 0, -length / 2 + length * fraction) * (b.Cylinder(root / 2 + (diameter - root) / 2 * fraction - 1.2, 0.8) - b.Cylinder(root / 2 + (diameter - root) / 2 * fraction - 1.2 - max(2.0, diameter * 0.05), 1.0)) for fraction in (0.3, 0.55, 0.8)])
    return bodies(("baffle", SILVER, shell), ("flange", SILVER, flange), ("vanes", BLACK, vanes))


DETAIL_BUILDERS["baffle_cone"] = baffle_cone
