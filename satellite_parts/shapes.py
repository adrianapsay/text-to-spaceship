"""
Geometry builders for the part library (build123d). Every builder returns a list of bodies [(name, color, Part), ...] in mm; the generator
centers the assembly on its bounding box, fuses the bodies into part.stl (the packing geometry), writes one STL per body (bodies/<name>.stl)
and a colored STEP. Shapes are deliberately simple (low face counts); features are added only where they matter for fit or recognition.
Colors are (r, g, b) in 0..1.
"""

import math
import build123d as b

# Palette
ALUMINIUM = (0.78, 0.80, 0.82)
ANODIZED = (0.36, 0.40, 0.46)
STEEL = (0.62, 0.64, 0.66)
PCB = (0.09, 0.42, 0.24)
GOLD = (0.85, 0.66, 0.22)
COPPER = (0.72, 0.45, 0.20)
BLACK = (0.16, 0.16, 0.18)
WHITE = (0.93, 0.93, 0.92)
SOLAR = (0.16, 0.26, 0.62)
GLASS = (0.45, 0.65, 0.85)
TITANIUM = (0.55, 0.55, 0.58)
RED = (0.75, 0.15, 0.12)
INSULATION = (0.85, 0.72, 0.30)
BRASS = (0.78, 0.62, 0.28)


def bodies(*items):
    """Helper: items are (name, color, part)."""
    return list(items)


def box(x, y, z, color=ANODIZED, **_):
    return bodies(("body", color, b.Box(x, y, z)))


def module_box(x, y, z, connector_face="+x", lid=1.5, **_):
    """Electronics module: anodized body, an inset aluminium lid plate on +z with four corner screws, and a connector block recessed into the +x face. Same envelope as box(x, y, z)."""
    lid_height = min(lid, z * 0.15)
    inset = min(2.0, 0.06 * min(x, y))
    body = b.Pos(0, 0, -lid_height / 2) * b.Box(x, y, z - lid_height)
    rim = b.Pos(0, 0, (z - lid_height) / 2) * (b.Box(x, y, lid_height) - b.Box(x - 2 * inset, y - 2 * inset, lid_height + 1))
    body = body + rim
    top = b.Pos(0, 0, (z - lid_height) / 2) * b.Box(x - 2 * inset, y - 2 * inset, lid_height)
    screw_radius = min(1.2, 0.02 * min(x, y))
    screws = None
    for sx in (-1, 1):
        for sy in (-1, 1):
            head = b.Pos(sx * (x / 2 - inset - 3 * screw_radius), sy * (y / 2 - inset - 3 * screw_radius), (z - lid_height) / 2 + lid_height / 2 - 0.15) * b.Cylinder(screw_radius, 0.3)
            screws = head if screws is None else screws + head
    connector_width = min(0.5 * y, 20.0)
    connector_height = min(0.4 * z, 8.0)
    connector_depth = min(3.0, 0.2 * x)
    pocket = b.Pos(x / 2 - connector_depth / 2, 0, -lid_height / 2) * b.Box(connector_depth + 0.2, connector_width + 0.2, connector_height + 0.2)
    body = body - pocket
    connector = b.Pos(x / 2 - connector_depth / 2, 0, -lid_height / 2) * b.Box(connector_depth, connector_width, connector_height)
    return bodies(("housing", ANODIZED, body), ("lid", ALUMINIUM, top), ("screws", STEEL, screws), ("connector", BLACK, connector))


def solar_cell(x, y, z, **_):
    """Single triple-junction cell: dark blue cell with a silver bus bar along one short edge."""
    cell = b.Box(x, y, z)
    bar = b.Pos(-x / 2 + 1.5, 0, z / 2 - 0.05) * b.Box(3.0, y * 0.9, 0.1)
    cell = cell - bar
    return bodies(("cell", SOLAR, cell), ("bus_bar", STEEL, bar))


def rounded_box(x, y, z, radius=2.0, color=ANODIZED, **_):
    part = b.Box(x, y, z)
    try:
        part = b.fillet(part.edges().filter_by(b.Axis.Z), radius)
    except Exception:
        pass
    return bodies(("body", color, part))


def _axis(part, axis):
    if axis == "x":
        return part.rotate(b.Axis.Y, 90)
    if axis == "y":
        return part.rotate(b.Axis.X, 90)
    return part


def cylinder(diameter, length, axis="z", color=STEEL, **_):
    return bodies(("body", color, _axis(b.Cylinder(diameter / 2.0, length), axis)))


def tube(outer_diameter, inner_diameter, length, axis="z", color=STEEL, **_):
    part = b.Cylinder(outer_diameter / 2.0, length) - b.Cylinder(inner_diameter / 2.0, length + 1)
    return bodies(("body", color, _axis(part, axis)))


def sphere(diameter, color=TITANIUM, **_):
    return bodies(("shell", color, b.Sphere(diameter / 2.0)))


def hex_prism(across_flats, length, axis="z", color=STEEL, **_):
    radius = across_flats / math.sqrt(3.0)
    part = b.extrude(b.RegularPolygon(radius, 6), length / 2.0, both=True)
    return bodies(("body", color, _axis(part, axis)))


def plate_with_holes(x, y, z, holes, hole_diameter, color=ALUMINIUM, **_):
    """Flat plate with through holes at (hx, hy) positions measured from the plate center."""
    part = b.Box(x, y, z)
    for hx, hy in holes:
        part = part - b.Pos(hx, hy, 0) * b.Cylinder(hole_diameter / 2.0, z + 2)
    return bodies(("plate", color, part))


def pc104_board(x=95.89, y=90.17, z=1.6, hole_diameter=3.2, components_height=0.0, **_):
    """PC/104 outline: green PCB with the four corner holes (centers 4.57 mm in from the edges), the 2 x 52-pin stack-through header along one long edge, and a components block (anodized shield) on top, all inside x * y * (z + components_height)."""
    inset = 4.57
    holes = [(x / 2 - inset, y / 2 - inset), (-x / 2 + inset, y / 2 - inset), (x / 2 - inset, -y / 2 + inset), (-x / 2 + inset, -y / 2 + inset)]
    board = plate_with_holes(x, y, z, holes, hole_diameter, PCB)[0][2]
    result = [("pcb", PCB, board)]
    if components_height > 0:
        header_height = min(components_height, 11.0)
        header = b.Pos(0, -y / 2 + 2 * inset + 2.5, z / 2 + header_height / 2) * b.Box(x - 2 * (inset + 4), 5.0, header_height)
        result.append(("stack_header", BLACK, header))
        block_y = y - 2 * inset - 14
        block = b.Pos(0, 6, z / 2 + components_height / 2) * b.Box(x - 2 * 12, block_y, components_height)
        result.append(("components", ANODIZED, block))
    return result


def cubesat_frame(units_x=1, units_y=1, units_z=1, rail=8.5, wall=1.5, length_z=None, width_x=None, width_y=None, **_):
    """Skeleton frame: four square rails along z (anodized), end rings and mid rings (aluminium). Outer envelope 100 x 100 mm per unit (226.3 mm for 2 units per CDS) unless width_x / width_y are given; z = CDS length."""
    width_x = width_x if width_x is not None else (226.3 if units_x == 2 else 100.0 * units_x)
    width_y = width_y if width_y is not None else (226.3 if units_y == 2 else 100.0 * units_y)
    length = length_z if length_z is not None else {1: 113.5, 2: 227.0, 3: 340.5}.get(units_z, 113.5 * units_z)
    rails = None
    positions_x = [-(width_x - rail) / 2, (width_x - rail) / 2] + ([0.0] if units_x == 2 else [])
    positions_y = [-(width_y - rail) / 2, (width_y - rail) / 2] + ([0.0] if units_y == 2 else [])
    for px in positions_x:
        for py in positions_y:
            rail_part = b.Pos(px, py, 0) * b.Box(rail, rail, length)
            rails = rail_part if rails is None else rails + rail_part
    rings = None
    for sz in (-1, 1):
        ring = b.Box(width_x, width_y, rail) - b.Box(width_x - 2 * rail, width_y - 2 * rail, rail + 2)
        ring = b.Pos(0, 0, sz * (length - rail) / 2) * ring
        rings = ring if rings is None else rings + ring
    count = int(round(length / 100.0))
    for index in range(1, count):
        z = -length / 2 + index * (length / count)
        ring = b.Box(width_x, width_y, wall * 2) - b.Box(width_x - 2 * rail, width_y - 2 * rail, wall * 2 + 2)
        rings = rings + b.Pos(0, 0, z) * ring
    return bodies(("rails", ANODIZED, rails), ("rings", ALUMINIUM, rings))


def reaction_wheel(x, y, z, flywheel_diameter=None, housing="box", **_):
    """Housing box (anodized) with a flywheel disc (steel) proud of the top face and a motor cap on the disc. housing="round": sealed cylindrical housing on a thin mounting flange with four lugs (Astrofein, NewSpace, BST style)."""
    diameter = flywheel_diameter if flywheel_diameter is not None else min(x, y) * 0.9
    if housing == "round":
        flange_thickness = min(3.0, z * 0.15)
        flange = b.Pos(0, 0, -z / 2 + flange_thickness / 2) * b.Box(x, y, flange_thickness)
        lug_bore = max(2.5, min(x, y) * 0.06)
        for sx in (-1, 1):
            for sy in (-1, 1):
                flange = flange - b.Pos(sx * (x / 2 - lug_bore), sy * (y / 2 - lug_bore), -z / 2 + flange_thickness / 2) * b.Cylinder(lug_bore / 2.0, flange_thickness + 1)
        can_height = z - flange_thickness - 1.5 + 0.4
        can = b.Pos(0, 0, -z / 2 + flange_thickness - 0.2 + can_height / 2) * b.Cylinder(diameter / 2.0, can_height)
        cap = b.Pos(0, 0, z / 2 - 0.75 - 0.1) * b.Cylinder(diameter * 0.9 / 2.0, 1.7)
        connector = b.Pos(min(diameter / 2 + 1.8, x / 2 - 2.0), 0, -z / 2 + flange_thickness + 4.8) * b.Box(4.0, min(0.35 * y, 16.0), 8.0)
        return bodies(("flange", ALUMINIUM, flange), ("housing", ANODIZED, can), ("lid", STEEL, cap), ("connector", BLACK, connector))
    height = z * 0.6
    base = b.Box(x, y, z - height)
    disc = b.Pos(0, 0, (z - height) / 2 + height * 0.8 / 2) * b.Cylinder(diameter / 2.0, height * 0.8)
    cap = b.Pos(0, 0, (z - height) / 2 + height * 0.8 + height * 0.2 / 2) * b.Cylinder(diameter * 0.35, height * 0.2)
    return bodies(("housing", ANODIZED, base), ("flywheel", STEEL, disc), ("motor_cap", BLACK, cap))


def torquer_rod(diameter, length, flange=None, **_):
    """Magnetorquer rod: copper-colored coil over a steel core, with end flanges when given."""
    core_length = length - (2 * flange[2] if flange is not None else 0.0)
    coil = b.Cylinder(diameter / 2.0, core_length * 0.8).rotate(b.Axis.Y, 90)
    core = b.Cylinder(diameter / 2.0 * 0.6, core_length).rotate(b.Axis.Y, 90)
    result = [("coil", COPPER, coil), ("core", STEEL, core)]
    if flange is not None:
        flanges = None
        for sx in (-1, 1):
            flange_part = b.Pos(sx * (length / 2 - flange[2] / 2), 0, 0) * b.Box(flange[2], flange[0], flange[1])
            flanges = flange_part if flanges is None else flanges + flange_part
        result.append(("flanges", ANODIZED, flanges))
    return result


def thruster_box_nozzle(x, y, z, nozzle_diameter, nozzle_length, throat_diameter=None, nozzle_count=1, tank_diameter=None, **_):
    """Propulsion module: anodized body, a mounting flange plate on the +z face, one or four conical nozzles (titanium) on +z, a valve block beside the nozzle(s),
    and (if tank_diameter is given, or by default for bodies deep enough) a visible propellant tank dome on the -z side within the body envelope.
    Overall z = z + nozzle_length (the body includes the flange)."""
    throat = throat_diameter if throat_diameter is not None else nozzle_diameter * 0.3
    flange_thickness = min(2.0, z * 0.08)
    body = b.Pos(0, 0, -flange_thickness / 2) * b.Box(x, y, z - flange_thickness)
    flange = b.Pos(0, 0, (z - flange_thickness) / 2) * b.Box(x, y, flange_thickness)
    nozzles = None
    if nozzle_count == 4:
        offsets = [(sx * x * 0.3, sy * y * 0.3) for sx in (-1, 1) for sy in (-1, 1)]
    else:
        offsets = [(0.0, 0.0)]
    for ox, oy in offsets:
        cone = b.Pos(ox, oy, z / 2 + nozzle_length / 2) * b.Cone(throat / 2.0, nozzle_diameter / 2.0, nozzle_length)
        ring = b.Pos(ox, oy, z / 2 + min(1.0, nozzle_length * 0.2) / 2) * b.Cylinder(nozzle_diameter * 0.75, min(1.0, nozzle_length * 0.2))
        cone = cone + ring
        nozzles = cone if nozzles is None else nozzles + cone
    valve_size = min(0.18 * min(x, y), 10.0)
    valve_height = min(nozzle_length * 0.6, 6.0)
    valve = b.Pos(x * 0.5 - valve_size, -y * 0.5 + valve_size, z / 2 + valve_height / 2) * b.Box(valve_size, valve_size, valve_height)
    result = [("body", ANODIZED, body), ("flange", ALUMINIUM, flange), ("nozzle", TITANIUM, nozzles), ("valve", STEEL, valve)]
    if tank_diameter is None and min(x, y) > 40 and z > 40:
        tank_diameter = min(x, y) * 0.6
    if tank_diameter:
        tank_depth = min(tank_diameter * 0.25, z * 0.3)
        dome = b.Pos(0, 0, -z / 2 + flange_thickness + tank_depth / 2) * b.Cylinder(tank_diameter / 2.0, tank_depth)
        result.append(("tank_dome", TITANIUM, dome))
    return result


def electric_thruster(x, y, z, emitter_diameter, emitter_length, **_):
    """Electrospray / ion thruster: anodized body, a round emitter head (gold, with a ring) proud of the +z face, and a connector. Overall z = z + emitter_length."""
    body = b.Box(x, y, z)
    head = b.Pos(0, 0, z / 2 + emitter_length / 2) * b.Cylinder(emitter_diameter / 2.0, emitter_length)
    ring = b.Pos(0, 0, z / 2 + emitter_length * 0.75) * (b.Cylinder(emitter_diameter / 2.0 + 0.01, emitter_length * 0.5) - b.Cylinder(emitter_diameter * 0.35, emitter_length))
    connector = b.Pos(x / 2 - 1.5, 0, 0) * b.Box(3.0, min(0.4 * y, 15.0), min(0.3 * z, 6.0))
    return bodies(("body", ANODIZED, body), ("emitter", GOLD, head + ring), ("connector", BLACK, connector))


def tank_cylindrical(diameter, length, boss_diameter=None, **_):
    """Cylinder with hemispherical domes (titanium) and a port boss on one end; length is the overall length."""
    straight = max(length - diameter, 0.1)
    part = b.Cylinder(diameter / 2.0, straight)
    for sz in (-1, 1):
        part = part + b.Pos(0, 0, sz * straight / 2) * b.Sphere(diameter / 2.0)
    boss = boss_diameter if boss_diameter is not None else diameter * 0.15
    port = b.Pos(0, 0, length / 2 - boss / 2) * b.Cylinder(boss / 2.0, boss)
    return bodies(("shell", TITANIUM, part), ("port", STEEL, port))


def tank_spherical(diameter, boss_diameter=None, boss_length=0.0, **_):
    shell = b.Sphere(diameter / 2.0)
    result = [("shell", TITANIUM, shell)]
    if boss_diameter and boss_length:
        result.append(("port", STEEL, b.Pos(0, 0, diameter / 2) * b.Cylinder(boss_diameter / 2.0, boss_length)))
    return result


def cell_18650(diameter=18.4, length=65.1, **_):
    """Cylindrical cell: steel can, positive cap, and a wrapper band."""
    can = b.Pos(0, 0, -1.0) * b.Cylinder(diameter / 2.0, length - 2.0)
    cap = b.Pos(0, 0, length / 2 - 1.0) * b.Cylinder(diameter * 0.28, 2.0)
    return bodies(("can", INSULATION, can), ("positive_cap", STEEL, cap))


def cell_pouch(x, y, z, tab_length=0.0, **_):
    return bodies(("pouch", (0.75, 0.75, 0.78), b.Box(x, y, z)))


def battery_pack(x, y, z, cells=(2, 2), cell_diameter=18.4, cell_axis="x", **_):
    """Battery pack: anodized housing with cylindrical cells shown recessed on the top face (cells x rows along the long side)."""
    housing = b.Box(x, y, z)
    columns, rows = cells
    cell_length = min(x - 6, 65.0)
    cell_bodies = None
    pitch_y = min(cell_diameter + 1.5, (y - 4) / max(rows, 1))
    radius = min(cell_diameter, pitch_y - 1) / 2.0
    for row in range(rows):
        cy = -pitch_y * (rows - 1) / 2 + row * pitch_y
        cell = b.Pos(0.0, cy, z / 2 - radius - 0.3) * b.Cylinder(radius, cell_length).rotate(b.Axis.Y, 90)
        cell_bodies = cell if cell_bodies is None else cell_bodies + cell
    pocket_depth = min(z - 2.0, 2 * radius + 0.9)
    pocket = b.Pos(0.0, 0.0, z / 2 - pocket_depth / 2) * b.Box(cell_length + 2.0, pitch_y * rows + 1.0, pocket_depth)
    housing = housing - pocket
    return bodies(("housing", ANODIZED, housing), ("cells", INSULATION, cell_bodies))


def screw(head_diameter, head_height, shank_diameter, length, socket_diameter=None, socket_depth=None, **_):
    """Socket head cap screw (steel): head cylinder plus shank, hex socket as a simple recess. Overall z = head_height + length, head at +z."""
    head = b.Pos(0, 0, length / 2 + head_height / 2) * b.Cylinder(head_diameter / 2.0, head_height)
    shank = b.Cylinder(shank_diameter / 2.0, length)
    if socket_diameter and socket_depth:
        radius = socket_diameter / math.sqrt(3.0)
        recess = b.Pos(0, 0, length / 2 + head_height - socket_depth / 2) * b.extrude(b.RegularPolygon(radius, 6), socket_depth / 2.0, both=True)
        head = head - recess
    return bodies(("head", ANODIZED, head), ("shank", STEEL, shank))


def countersunk_screw(head_diameter, head_height, shank_diameter, length, **_):
    """Countersunk (flat head) screw per ISO 10642: 90 degree cone head flush with the top, head at +z. Overall z = length (head included)."""
    shank = b.Pos(0, 0, -head_height / 2) * b.Cylinder(shank_diameter / 2.0, length - head_height)
    head = b.Pos(0, 0, (length - head_height) / 2) * b.Cone(shank_diameter / 2.0, head_diameter / 2.0, head_height)
    return bodies(("head", ANODIZED, head), ("shank", STEEL, shank))


def hex_nut(across_flats, thickness, bore, **_):
    radius = across_flats / math.sqrt(3.0)
    part = b.extrude(b.RegularPolygon(radius, 6), thickness / 2.0, both=True) - b.Cylinder(bore / 2.0, thickness + 2)
    return bodies(("nut", STEEL, part))


def washer(outer_diameter, inner_diameter, thickness, **_):
    return bodies(("washer", STEEL, b.Cylinder(outer_diameter / 2.0, thickness) - b.Cylinder(inner_diameter / 2.0, thickness + 2)))


def standoff(across_flats, length, bore, **_):
    radius = across_flats / math.sqrt(3.0)
    return bodies(("standoff", BRASS, b.extrude(b.RegularPolygon(radius, 6), length / 2.0, both=True) - b.Cylinder(bore / 2.0, length + 2)))


def l_bracket(x, y, z, thickness, **_):
    base = b.Pos(0, 0, -z / 2 + thickness / 2) * b.Box(x, y, thickness)
    wall = b.Pos(-x / 2 + thickness / 2, 0, 0) * b.Box(thickness, y, z)
    return bodies(("bracket", ALUMINIUM, base + wall))


def extrusion_2020(length, size=20.0, slot=6.0, **_):
    """Simplified 20x20 T-slot: square with four slots."""
    part = b.Box(size, size, length)
    depth = size * 0.3
    for angle in (0, 90, 180, 270):
        cutter = b.Pos(size / 2 - depth / 2, 0, 0) * b.Box(depth, slot, length + 2)
        part = part - cutter.rotate(b.Axis.Z, angle)
    return bodies(("extrusion", ALUMINIUM, part))


def patch_antenna(x, y, z, patch_inset=8.0, patch_height=1.0, **_):
    """Patch antenna: aluminium ground plate / housing with a copper patch on top and a connector stub on the underside face (inside the envelope)."""
    base = b.Box(x, y, z)
    patch = b.Pos(0, 0, z / 2 + patch_height / 2) * b.Box(x - 2 * patch_inset, y - 2 * patch_inset, patch_height)
    return bodies(("housing", WHITE, base), ("patch", COPPER, patch))


def cryocooler_split(compressor_diameter, compressor_length, cold_head_diameter, cold_head_length, gap=6.0, **_):
    """Split Stirling / pulse-tube cooler drawn as its two cylinders side by side along z: the pressure wave generator (compressor) and the cold head with its cold tip, joined by a short transfer line."""
    height = max(compressor_length, cold_head_length)
    total_x = compressor_diameter + gap + cold_head_diameter
    compressor_x = -total_x / 2 + compressor_diameter / 2
    cold_head_x = total_x / 2 - cold_head_diameter / 2
    compressor = b.Pos(compressor_x, 0, -height / 2 + compressor_length / 2) * b.Cylinder(compressor_diameter / 2.0, compressor_length)
    cold_body_length = cold_head_length * 0.55
    cold_body = b.Pos(cold_head_x, 0, -height / 2 + cold_body_length / 2) * b.Cylinder(cold_head_diameter / 2.0, cold_body_length)
    cold_finger = b.Pos(cold_head_x, 0, -height / 2 + cold_body_length + (cold_head_length - cold_body_length) / 2 - 0.1) * b.Cylinder(cold_head_diameter * 0.22, cold_head_length - cold_body_length + 0.2)
    line_length = cold_head_x - compressor_x
    transfer_line = b.Pos((compressor_x + cold_head_x) / 2, 0, -height / 2 + min(compressor_length, cold_body_length) * 0.5) * b.Cylinder(2.0, line_length).rotate(b.Axis.Y, 90)
    return bodies(("compressor", ANODIZED, compressor), ("cold head", STEEL, cold_body), ("cold finger", GOLD, cold_finger), ("transfer line", ALUMINIUM, transfer_line))


def radome_puck(diameter, length, flange_diameter=None, flange_thickness=2.0, **_):
    """Round antenna: white radome disc on a thin aluminium mounting flange."""
    flange_d = flange_diameter if flange_diameter is not None else diameter
    flange = b.Pos(0, 0, -length / 2 + flange_thickness / 2) * b.Cylinder(flange_d / 2.0, flange_thickness)
    radome = b.Pos(0, 0, flange_thickness / 2) * b.Cylinder(diameter / 2.0, length - flange_thickness)
    return bodies(("flange", ALUMINIUM, flange), ("radome", (0.92, 0.92, 0.9), radome))


def tape_antenna_deployed(base_x, base_y, base_z, tape_length, tape_width=6.0, tape_thickness=0.3, count=4, **_):
    """Deployed UHF/VHF tape-measure antenna: base plate with steel tapes radiating along +/-x and +/-y."""
    base = b.Box(base_x, base_y, base_z)
    tapes = None
    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)][:count]
    for dx, dy in directions:
        if dx != 0:
            tape = b.Pos(dx * (base_x / 2 + tape_length / 2 - 2.0), 0, base_z / 2 - tape_thickness / 2) * b.Box(tape_length, tape_width, tape_thickness)
        else:
            tape = b.Pos(0, dy * (base_y / 2 + tape_length / 2 - 2.0), base_z / 2 - tape_thickness / 2) * b.Box(tape_width, tape_length, tape_thickness)
        tapes = tape if tapes is None else tapes + tape
    return bodies(("base", ANODIZED, base), ("tapes", STEEL, tapes))


def tape_antenna_stowed(base_x, base_y, base_z, **_):
    """Stowed tape antenna: anodized base with a lighter lid ring and four tape guide slots."""
    base = b.Pos(0, 0, -base_z * 0.15) * b.Box(base_x, base_y, base_z * 0.7)
    lid = b.Pos(0, 0, base_z * 0.35) * (b.Box(base_x, base_y, base_z * 0.3) - b.Box(base_x * 0.7, base_y * 0.7, base_z))
    inner = b.Pos(0, 0, base_z * 0.35) * b.Box(base_x * 0.7, base_y * 0.7, base_z * 0.3)
    return bodies(("base", ANODIZED, base), ("lid", ALUMINIUM, lid), ("tape_coil", STEEL, inner))


def solar_panel(x, y, z, cells=None, cell_size=(40.0, 80.0), cell_height=0.4, **_):
    """Panel substrate (black PCB) with raised solar cells (dark blue); cells = (columns, rows)."""
    substrate = b.Box(x, y, z)
    cell_bodies = None
    if cells:
        columns, rows = cells
        pitch_x = x / columns
        pitch_y = y / rows
        for column in range(columns):
            for row in range(rows):
                cx = -x / 2 + pitch_x * (column + 0.5)
                cy = -y / 2 + pitch_y * (row + 0.5)
                cell = b.Pos(cx, cy, z / 2 + cell_height / 2) * b.Box(min(cell_size[0], pitch_x - 2), min(cell_size[1], pitch_y - 2), cell_height)
                cell_bodies = cell if cell_bodies is None else cell_bodies + cell
    result = [("substrate", (0.30, 0.30, 0.32), substrate)]
    if cell_bodies is not None:
        result.append(("cells", SOLAR, cell_bodies))
    return result


def deployable_panels(x, y, z, wings=1, angle=90.0, hinge_gap=1.0, **_):
    """Deployed configuration of a hinged array: body panel plus wings rotated out about the +x edge."""
    body = b.Box(x, y, z)
    wing_bodies = None
    for wing in range(wings):
        wing_part = b.Pos(x / 2 + hinge_gap, 0, 0) * b.Box(x, y, z)
        wing_part = wing_part.rotate(b.Axis((x / 2, 0, 0), (0, 1, 0)), -angle * (wing + 1) if angle != 90 else -90)
        wing_bodies = wing_part if wing_bodies is None else wing_bodies + wing_part
    return bodies(("body_panel", SOLAR, body), ("wings", SOLAR, wing_bodies))


def lens_barrel(diameter, length, flange_diameter=None, flange_thickness=0.0, **_):
    """Lens barrel / baffle (anodized) with a glass front and an optional mounting flange at the back."""
    barrel = b.Cylinder(diameter / 2.0, length)
    glass = b.Pos(0, 0, length / 2 - 0.5) * b.Cylinder(diameter * 0.4, 1.0)
    barrel = barrel - glass
    result = [("barrel", ANODIZED, barrel), ("glass", GLASS, glass)]
    if flange_diameter:
        result.append(("flange", ALUMINIUM, b.Pos(0, 0, -length / 2 + flange_thickness / 2) * b.Cylinder(flange_diameter / 2.0, flange_thickness)))
    return result


def camera_box_lens(x, y, z, lens_diameter, lens_length, baffle_diameter=None, **_):
    """Camera / star tracker: anodized body, lens barrel on +z with a glass front, connector on a side. Overall z = z + lens_length. baffle_diameter: the barrel becomes a conical stray-light baffle opening to that diameter."""
    body = b.Box(x, y, z)
    if baffle_diameter:
        barrel = b.Pos(0, 0, z / 2) * b.Cone(lens_diameter / 2.0, baffle_diameter / 2.0, lens_length, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        barrel = barrel - b.Pos(0, 0, z / 2 + 1.5) * b.Cone(lens_diameter / 2.0 - 1.5, baffle_diameter / 2.0 - 1.5, lens_length, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        glass = b.Pos(0, 0, z / 2 + 1.0) * b.Cylinder(lens_diameter * 0.42, 1.0)
    else:
        barrel = b.Pos(0, 0, z / 2 + lens_length / 2) * b.Cylinder(lens_diameter / 2.0, lens_length)
        glass = b.Pos(0, 0, z / 2 + lens_length - 0.5) * b.Cylinder(lens_diameter * 0.42, 1.0)
        barrel = barrel - glass
    connector = b.Pos(x / 2 - 1.5, 0, 0) * b.Box(3.0, min(0.4 * y, 15.0), min(0.3 * z, 6.0))
    return bodies(("body", ANODIZED, body), ("lens_barrel", BLACK, barrel), ("glass", GLASS, glass), ("connector", BLACK, connector))


def sun_sensor(x, y, z, aperture_diameter=None, **_):
    """Sun sensor: small anodized block with a dark aperture window on +z."""
    aperture = aperture_diameter if aperture_diameter is not None else min(x, y) * 0.3
    body = b.Box(x, y, z)
    window = b.Pos(0, 0, z / 2 - 0.3) * b.Cylinder(aperture / 2.0, 0.6)
    body = body - window
    return bodies(("body", ANODIZED, body), ("aperture", GLASS, window))


def heater_foil(x, y, z, **_):
    """Polyimide foil heater: amber film with a copper trace band."""
    film = b.Box(x, y, z)
    trace = b.Pos(0, 0, z / 2 - z * 0.25) * b.Box(x * 0.8, y * 0.6, z * 0.5)
    film = film - trace
    return bodies(("film", INSULATION, film), ("trace", COPPER, trace))


def thermal_strap(x, y, z, fitting_length=19.0, **_):
    """Copper thermal strap: copper rope section between two aluminium end fittings."""
    rope = b.Box(x - 2 * fitting_length, y * 0.8, z * 0.8)
    fittings = None
    for sx in (-1, 1):
        fitting = b.Pos(sx * (x / 2 - fitting_length / 2), 0, 0) * b.Box(fitting_length, y, z)
        fittings = fitting if fittings is None else fittings + fitting
    return bodies(("rope", COPPER, rope), ("fittings", ALUMINIUM, fittings))


def separation_switch(x, y, z, plunger_diameter=2.0, plunger_length=2.5, **_):
    """Microswitch: black body with a steel plunger on +z. Overall z = z + plunger_length."""
    body = b.Box(x, y, z)
    plunger = b.Pos(-x * 0.25, 0, z / 2 + plunger_length / 2) * b.Cylinder(plunger_diameter / 2.0, plunger_length)
    return bodies(("body", BLACK, body), ("plunger", STEEL, plunger))


def connector_block(x, y, z, **_):
    """Rectangular connector: black shell with a gold contact face strip."""
    shell = b.Box(x, y, z)
    contacts = b.Pos(0, 0, z / 2 - 0.25) * b.Box(x * 0.85, y * 0.5, 0.5)
    shell = shell - contacts
    return bodies(("shell", BLACK, shell), ("contacts", GOLD, contacts))


def center(part):
    bbox = part.bounding_box()
    cx = (bbox.min.X + bbox.max.X) / 2
    cy = (bbox.min.Y + bbox.max.Y) / 2
    cz = (bbox.min.Z + bbox.max.Z) / 2
    return b.Pos(-cx, -cy, -cz) * part


def build(spec):
    """Build a shape spec dict into (fused_part, [(name, color, part), ...]), everything centered on the fused bounding box."""
    spec = dict(spec)
    kind = spec.pop("kind")
    spec.pop("tolerance", None)
    body_list = BUILDERS[kind](**spec)
    fused = None
    for name, color, part in body_list:
        fused = part if fused is None else fused + part
    bbox = fused.bounding_box()
    shift = b.Pos(-(bbox.min.X + bbox.max.X) / 2, -(bbox.min.Y + bbox.max.Y) / 2, -(bbox.min.Z + bbox.max.Z) / 2)
    fused = shift * fused
    centered = [(name, color, shift * part) for name, color, part in body_list]
    return fused, centered




def box_with_ears(x, y, z, ear_length, ear_thickness=3.0, ear_width=None, hole_diameter=3.4, **_):
    """Sensor housing with two bolt-down ears on the -x and +x sides; overall envelope x by y by z (body x - 2 * ear_length)."""
    body_x = x - 2 * ear_length
    ear_width = ear_width or 0.4 * y
    body = b.Box(body_x, y, z)
    ears = None
    for sx in (-1, 1):
        ear = b.Pos(sx * (body_x / 2 + ear_length / 2), 0, -z / 2 + ear_thickness / 2) * b.Box(ear_length + 0.2, ear_width, ear_thickness)
        ear = ear - b.Pos(sx * (body_x / 2 + ear_length / 2), 0, -z / 2 + ear_thickness / 2) * b.Cylinder(hole_diameter / 2, ear_thickness + 1)
        ears = ear if ears is None else ears + ear
    window = b.Pos(0, 0, z / 2 - 0.25) * b.Box(0.45 * body_x, 0.45 * y, 0.5)
    return bodies(("body", ANODIZED, body + ears), ("window", GLASS, window))


def rod_with_driver(x, y, z, rod_diameter, board_x, board_y, board_z, **_):
    """Magnetorquer rod along x with clamp feet, plus its driver board beside it; overall envelope x by y by z."""
    rod_y = -y / 2 + rod_diameter / 2
    rod = b.Pos(0, rod_y, z / 2 - rod_diameter / 2) * b.Cylinder(rod_diameter / 2, x).rotate(b.Axis.Y, 90)
    clamps = None
    for sx in (-0.3, 0.3):
        clamp = b.Pos(sx * x, rod_y, -z / 2 + (z - rod_diameter / 2) / 2) * b.Box(8, rod_diameter + 4, z - rod_diameter / 2)
        clamps = clamp if clamps is None else clamps + clamp
    board = b.Pos(0, y / 2 - board_y / 2, -z / 2 + board_z / 2) * b.Box(board_x, board_y, board_z)
    return bodies(("coil", COPPER, rod), ("clamps", ANODIZED, clamps), ("driver_board", PCB, board))


def wheel_pyramid(x, y, z, base_thickness=5.0, **_):
    """Four reaction wheels on a pyramid bracket: base plate and four wheel housings at the corners, each tilted inward (drawn as blocks leaning 20 deg)."""
    base = b.Pos(0, 0, -z / 2 + base_thickness / 2) * b.Box(x, y, base_thickness)
    wheel = min(x, y) * 0.42
    height = z - base_thickness
    wheels = None
    for sx, sy, angle_axis, sign in ((-1, 0, b.Axis.Y, 1), (1, 0, b.Axis.Y, -1), (0, -1, b.Axis.X, -1), (0, 1, b.Axis.X, 1)):
        block = b.Box(wheel, wheel, min(height * 0.55, wheel * 0.6)).rotate(angle_axis, sign * 20)
        block = b.Pos(sx * (x / 2 - wheel / 2 - 2), sy * (y / 2 - wheel / 2 - 2), -z / 2 + base_thickness + height * 0.45) * block
        wheels = block if wheels is None else wheels + block
    return bodies(("bracket", ALUMINIUM, base), ("wheels", BLACK, wheels))


BUILDERS = {name: function for name, function in globals().items() if callable(function) and not name.startswith("_") and name not in ("center", "bodies", "build")}
