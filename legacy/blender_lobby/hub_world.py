"""
StickDrift hub world - built and played inside Blender.

Build + play from Blender's Text Editor (Run Script). See README.md.

Controls (PS5 controller; click the 3D viewport first):
    Left stick or D-pad  walk         Cross (X)  enter a game
    Right stick          orbit camera (left/right) and tilt top-down..45 deg (up/down)
    L1 / R1              camera lower / higher (zoom, limited)
    Triangle           toggle follow / overview camera
    Esc (keyboard)     stop playing (re-run this script to rebuild)
"""
import math
import os
import random
import shutil
import subprocess
import webbrowser

import bpy
import bmesh
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------- config
try:                                   # only used if a portal is pointed at an external pygame script
    GAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "garden")
except NameError:                      # run from Blender's Text Editor / exec(): no __file__
    GAMES_DIR = os.path.join(os.getcwd(), "legacy", "garden")
PLAYER_ID, SESSION = "P01", "1"
PORTALS = [  # name, label, script, world x, y
    ("Game1", "Game 1", None, -7.4, 0.8),      # None = built-in Blender game (apple picking)
    ("Game2", "Game 2", None, 0.0, 3.8),
    ("Game3", "Game 3", None, 6.9, -0.8),
]
GRANDMA_START = (0.0, -5.0)
HALF_X, HALF_Y = 9.6, 6.1          # walkable half-extents inside the fence
SPEED = 2.1                        # m/s
PORTAL_R = 1.9                     # prompt distance
DOOR = (0.0, -(HALF_Y + 0.35))     # exit door in the south fence, right behind where grandma starts
DOOR_R, DOOR_GAP, DOOR_OPEN = 1.2, 1.0, 1.45
DASHBOARD_URL = "http://localhost:5173/"   # where the exit door sends you (the web dashboard)
PLAYER_R = 0.38
CAM_DIST = 22.0                    # camera distance from the focus point
MAX_TILT = math.radians(45)        # right stick up/down: 0 = straight top-down .. 45 deg
ORBIT_SPEED, TILT_SPEED = math.radians(120), math.radians(60)   # per second at full stick
ZOOM_RANGE, ZOOM_SPEED = (8.0, 16.0), 3.0                       # camera height (ortho width), L1/R1

# sketch -> world (x, y, size).  Green = trees, grey = rocks.
TREES = [(-5.0, 4.9, 1.5), (-2.8, 4.4, 0.8), (-4.2, 2.1, 1.1), (5.4, 3.0, 1.0),
         (7.8, 4.7, 0.9), (6.5, 3.9, 0.7), (3.2, 2.9, 1.0), (1.8, -1.4, 1.0),
         (-6.8, -4.2, 0.9), (7.3, -4.9, 1.3), (-8.6, 4.8, 0.8), (5.2, -3.6, 0.8)]
ROCKS = [(-8.8, 3.7, 0.45), (3.9, 0.6, 0.5), (-5.0, -2.6, 0.8), (-1.6, 0.2, 0.9),
         (3.6, -4.3, 0.5), (-1.4, -1.8, 0.4), (8.2, -2.6, 0.55)]
BENCH = (-3.0, -4.9, 0.0)          # x, y, rotation (deg)

BG_COLOR = (0.09, 0.14, 0.11, 1)


# --------------------------------------------------------------------------- helpers
def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        for d in list(coll):
            coll.remove(d)


_mats = {}


def mat(name, rgb, rough=0.85, emit=None, emit_strength=0.0):
    if name in _mats:
        return _mats[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = emit_strength
    m.diffuse_color = (*rgb, 1)
    _mats[name] = m
    return m


def finish(ob, material, smooth=False, parent=None):
    ob.data.materials.append(material)
    if smooth:
        for p in ob.data.polygons:
            p.use_smooth = True
    if parent:
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_basis.inverted()   # keep the world position it was built at
    return ob


def cyl(name, r, h, loc, material, verts=12, r2=None, parent=None, smooth=True):
    verts = min(verts, 20)
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r if r2 is None else r2,
                                    depth=h, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    return finish(ob, material, smooth, parent)


def box(name, size, loc, material, parent=None, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    return finish(ob, material, False, parent)


def sphere(name, r, loc, material, parent=None, scale=(1, 1, 1), seg=10):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=seg, ring_count=seg // 2)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    return finish(ob, material, True, parent)


def label(text, loc, size=0.55, color=(1, 1, 1)):
    bpy.ops.object.text_add(location=loc)
    t = bpy.context.active_object
    t.name = "Label_" + text
    t.data.body = text
    t.data.size = size
    t.data.align_x = "CENTER"
    t.data.extrude = 0.03
    t.visible_shadow = False                           # text should not cast a ghost shadow
    t.data.materials.append(mat("LabelMat", color, 0.5, emit=color, emit_strength=1.5))
    return t


# --------------------------------------------------------------------------- scenery
def build_ground():
    grass = mat("Grass", (0.20, 0.46, 0.18))
    grass2 = mat("GrassDark", (0.16, 0.38, 0.15))
    path = mat("Path", (0.62, 0.50, 0.33), 0.95)
    stone = mat("FenceStone", (0.45, 0.45, 0.47))
    wood = mat("FenceWood", (0.40, 0.26, 0.14))

    box("Ground", (2 * (HALF_X + 0.6), 2 * (HALF_Y + 0.6), 0.4), (0, 0, -0.2), grass)

    rnd = random.Random(4)  # grass tufts / lighter patches
    for i in range(18):
        x, y = rnd.uniform(-HALF_X, HALF_X), rnd.uniform(-HALF_Y, HALF_Y)
        cyl(f"Patch{i}", rnd.uniform(0.5, 1.3), 0.02, (x, y, 0.01), grass2, verts=8, smooth=False)
    for i in range(30):
        x, y = rnd.uniform(-HALF_X, HALF_X), rnd.uniform(-HALF_Y, HALF_Y)
        cyl(f"Tuft{i}", 0.06, 0.22, (x, y, 0.11), grass2, verts=4, r2=0.0, smooth=False)

    # dirt paths grandma -> every portal (flat strips)
    start = Vector((*GRANDMA_START, 0))
    for name, _, _, px, py in PORTALS:
        a, b = start + Vector((0, 0.9, 0)), Vector((px, py, 0))
        mid, d = (a + b) / 2, b - a
        box("Path_" + name, (d.length, 0.9, 0.04), (mid.x, mid.y, 0.02), path,
            rot=(0, 0, math.atan2(d.y, d.x)))
    cyl("PathPlaza", 1.6, 0.04, (start.x, start.y + 0.3, 0.02), path, verts=24, smooth=False)

    # fence: stone corner posts + wooden rails
    fx, fy = HALF_X + 0.35, HALF_Y + 0.35
    ln = fx - DOOR_GAP
    for z_, name in ((0.55, "RailX"), (0.95, "RailX2")):
        box(name, (2 * fx, 0.12, 0.12), (0, fy, z_), wood)                           # north side: full length
        box(name, (ln, 0.12, 0.12), (-(DOOR_GAP + ln / 2), -fy, z_), wood)           # south side: two pieces
        box(name, (ln, 0.12, 0.12), (DOOR_GAP + ln / 2, -fy, z_), wood)              # with the doorway between
    for sx in (-fx, fx):
        box("RailY", (0.12, 2 * fy, 0.12), (sx, 0, 0.55), wood)
        box("RailY2", (0.12, 2 * fy, 0.12), (sx, 0, 0.95), wood)
    for i in range(-10, 11):
        x = i * fx / 10
        for y in (fy, -fy):
            if y < 0 and abs(x) < DOOR_GAP + 0.05:
                continue                                                              # no post in the doorway
            box("Post", (0.16, 0.16, 1.2), (x, y, 0.6), stone)
    for j in range(-6, 7):
        y = j * fy / 6
        for x in (fx, -fx):
            box("Post", (0.16, 0.16, 1.2), (x, y, 0.6), stone)


def build_door():
    """Exit door in the south fence: a low frame, warm light outside, a doormat and a leaf that swings open when near."""
    dx, dy = DOOR
    frame, wood_m, dark = mat("DoorFrame", (0.30, 0.19, 0.09), 0.9), mat("DoorWood", (0.50, 0.33, 0.17), 0.85), mat("DoorDark", (0.28, 0.17, 0.08), 0.9)
    light = mat("DoorLight", (1, 0.9, 0.6), 0.4, emit=(1, 0.85, 0.5), emit_strength=2.2)
    green = mat("DoorMat", (0.2, 0.75, 0.35), 0.6, emit=(0.2, 0.8, 0.35), emit_strength=1.2)
    knob = mat("DoorKnob", (0.9, 0.75, 0.3), 0.3)
    for sx in (-DOOR_GAP - 0.08, DOOR_GAP + 0.08):
        box("DoorPost", (0.2, 0.28, 1.7), (dx + sx, dy, 0.85), frame)
    box("DoorLintel", (2 * DOOR_GAP + 0.55, 0.28, 0.2), (dx, dy, 1.72), frame)
    box("DoorLight", (2 * DOOR_GAP, 0.05, 1.6), (dx, dy - 0.32, 0.8), light)
    box("DoorMat", (1.9, 0.8, 0.03), (dx, dy + 0.55, 0.03), green)
    label("EXIT", (dx, dy + 0.55, 0.06), 0.42, (1, 1, 1))
    hinge = bpy.data.objects.new("DoorHinge", None)              # the leaf is hinged on the left post
    bpy.context.collection.objects.link(hinge)
    hinge.location = (dx - DOOR_GAP, dy, 0)
    box("DoorLeaf", (2 * DOOR_GAP, 0.1, 1.6), (dx, dy, 0.8), wood_m, parent=hinge)
    box("DoorBar", (2 * DOOR_GAP - 0.2, 0.12, 0.08), (dx, dy, 1.2), dark, parent=hinge)
    box("DoorBar", (2 * DOOR_GAP - 0.2, 0.12, 0.08), (dx, dy, 0.45), dark, parent=hinge)
    sphere("DoorKnob", 0.07, (dx + DOOR_GAP - 0.2, dy + 0.1, 0.85), knob, parent=hinge, seg=8)


def blob(name, r, loc, material, parent, squash=1.0, seed=0):
    """Lumpy low-poly canopy blob (icosphere with jittered verts)."""
    rnd = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
    for v in bm.verts:
        v.co *= rnd.uniform(0.88, 1.12)
        v.co.z *= squash
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    return finish(ob, material, False, parent)


TREE_KINDS = ["oak", "pine", "oak", "autumn", "pine", "oak", "birch", "pine", "oak", "autumn", "oak", "pine"]


def build_tree(i, x, y, s):
    kind = TREE_KINDS[i % len(TREE_KINDS)]
    bark = mat("Bark", (0.30, 0.19, 0.10), 0.95)
    birch = mat("BirchBark", (0.88, 0.86, 0.80), 0.9)
    greens = [mat("Oak1", (0.12, 0.45, 0.14)), mat("Oak2", (0.17, 0.56, 0.18)), mat("Oak3", (0.27, 0.66, 0.22))]
    pines = [mat("Pine1", (0.06, 0.31, 0.17)), mat("Pine2", (0.08, 0.40, 0.21))]
    autumn = [mat("Aut1", (0.80, 0.36, 0.08)), mat("Aut2", (0.90, 0.55, 0.10)), mat("Aut3", (0.72, 0.20, 0.07))]
    root = bpy.data.objects.new(f"Tree{i}", None)
    bpy.context.collection.objects.link(root)
    root.location = (x, y, 0)
    root.rotation_euler.z = i * 0.9
    P = (x, y)
    cyl("Shadow", 1.0 * s, 0.01, (x, y, 0.015), mat("TreeShadow", (0.08, 0.2, 0.08)), 20, parent=root, smooth=False)
    cyl("Flare", 0.3 * s, 0.25 * s, (x, y, 0.12 * s), bark, 8, r2=0.2 * s, parent=root)
    if kind == "pine":
        cyl("Trunk", 0.17 * s, 1.0 * s, (*P, 0.5 * s), bark, 8, parent=root)
        for k in range(5):
            r = (1.15 - k * 0.2) * s
            cyl("Tier", r, 0.95 * s, (*P, (0.9 + k * 0.62) * s), pines[k % 2], 9, r2=0.05 * s, parent=root, smooth=False)
    else:
        tr = birch if kind == "birch" else bark
        cyl("Trunk", 0.2 * s, 1.5 * s, (*P, 0.75 * s), tr, 8, r2=0.14 * s, parent=root)
        pal = autumn if kind == "autumn" else greens
        spots = [(0, 0, 2.15, 0.95), (0.55, 0.15, 1.8, 0.7), (-0.5, -0.2, 1.85, 0.72),
                 (0.1, 0.55, 2.0, 0.65), (-0.1, -0.5, 2.3, 0.6), (0.35, -0.3, 2.55, 0.55)]
        if kind == "birch":
            spots = [(0, 0, 2.3, 0.7), (0.3, 0.2, 1.9, 0.5), (-0.3, -0.1, 2.0, 0.5), (0, 0.2, 2.7, 0.45)]
        for k, (dx, dy, z, r) in enumerate(spots):
            blob("Canopy", r * s, (x + dx * s, y + dy * s, z * s), pal[k % 3], root, 0.85, i * 10 + k)
    return root


def build_rock(i, x, y, s):
    rock = mat("Rock", (0.50, 0.50, 0.52), 0.95)
    rnd = random.Random(i + 11)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=s)
    for v in bm.verts:
        v.co *= rnd.uniform(0.8, 1.2)
        v.co.z *= 0.65
    me = bpy.data.meshes.new(f"Rock{i}")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(f"Rock{i}", me)
    bpy.context.collection.objects.link(ob)
    ob.location = (x, y, s * 0.4)
    ob.rotation_euler.z = rnd.uniform(0, 6.28)
    finish(ob, rock)
    return ob


def build_bench(x, y, rot):
    wood, iron = mat("BenchWood", (0.55, 0.35, 0.17)), mat("BenchIron", (0.12, 0.12, 0.13), 0.5)
    root = bpy.data.objects.new("Bench", None)
    bpy.context.collection.objects.link(root)
    root.location = (x, y, 0)
    root.rotation_euler.z = math.radians(rot)
    for k in range(3):
        box("Slat", (1.7, 0.16, 0.06), (x, y - 0.18 + k * 0.18, 0.5), wood, parent=root)
    for k in range(3):
        box("BackSlat", (1.7, 0.05, 0.14), (x, y + 0.36, 0.72 + k * 0.16), wood, parent=root)
    for sx in (-0.75, 0.75):
        box("Leg", (0.07, 0.6, 0.5), (x + sx, y, 0.25), iron, parent=root)
        box("BackLeg", (0.07, 0.06, 0.75), (x + sx, y + 0.36, 0.55), iron, parent=root)
    return root


def build_lamp(x, y):
    iron = mat("LampPole", (0.15, 0.15, 0.16), 0.5)
    glow = mat("LampGlow", (1, 0.9, 0.6), 0.3, emit=(1, 0.85, 0.5), emit_strength=6)
    cyl("LampPole", 0.05, 1.8, (x, y, 0.9), iron, 8)
    sphere("LampBulb", 0.17, (x, y, 1.9), glow)


PORTAL_COLORS = {"Game1": (0.25, 0.6, 1.0), "Game2": (0.3, 1.0, 0.55), "Game3": (0.8, 0.35, 1.0)}


def child(ob, root):
    ob.parent = root
    ob.matrix_parent_inverse = root.matrix_basis.inverted()
    return ob


def build_portal(name, text, x, y):
    col = PORTAL_COLORS[name]
    stone = mat("PortalStone", (0.50, 0.50, 0.55), 0.7)
    dark = mat("PortalDark", (0.22, 0.22, 0.27), 0.6)
    glow = mat("PortalGlow_" + name, col, 0.2, emit=col, emit_strength=1.2)
    bright = mat("PortalBright_" + name, col, 0.1, emit=col, emit_strength=6)
    root = bpy.data.objects.new("Portal_" + name, None)
    bpy.context.collection.objects.link(root)
    root.location = (x, y, 0)
    cyl("Step", 1.65, 0.1, (x, y, 0.05), dark, 40, parent=root)
    cyl("Base", 1.45, 0.2, (x, y, 0.15), stone, 40, parent=root)
    cyl("Inner", 1.12, 0.22, (x, y, 0.16), dark, 40, parent=root)
    cyl("Glow", 1.05, 0.22, (x, y, 0.17), glow, 40, parent=root)
    for k in range(12):                       # glowing rune ticks around the rim
        a = k * math.tau / 12
        box("Rune", (0.25, 0.06, 0.04), (x + 1.28 * math.cos(a), y + 1.28 * math.sin(a), 0.26), bright,
            parent=root, rot=(0, 0, a + math.pi / 2))
    for k in range(6):                        # stone pillars with glowing caps
        a = k * math.tau / 6 + 0.26
        px, py = x + 1.5 * math.cos(a), y + 1.5 * math.sin(a)
        cyl("Pillar", 0.14, 0.95, (px, py, 0.55), stone, 8, parent=root)
        cyl("PillarCap", 0.18, 0.1, (px, py, 1.05), dark, 8, parent=root)
        sphere("PillarOrb", 0.1, (px, py, 1.17), bright, root)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.85, minor_radius=0.035, major_segments=20, minor_segments=4, location=(x, y, 0.9))
    ring = bpy.context.active_object
    ring.name = "Ring_" + name
    child(finish(ring, bright, True), root)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.38, location=(x, y, 0.9))
    cr = bpy.context.active_object
    cr.name, cr.scale = "Crystal_" + name, (0.7, 0.7, 1.5)
    child(finish(cr, bright), root)
    bpy.ops.object.light_add(type="POINT", location=(x, y, 1.3))
    L = bpy.context.active_object
    L.name, L.data.energy, L.data.color = "PortalLight_" + name, 90, col
    L.data.use_shadow = False
    child(L, root)
    child(label(text, (x, y + 2.2, 0.02), 0.5), root)  # flat on the ground, readable from above
    return root


def build_grandma(x, y):
    from mathutils import Matrix
    skin, dress = mat("Skin", (0.95, 0.76, 0.62)), mat("Dress", (0.72, 0.22, 0.45))
    hair, shoe = mat("Hair", (0.85, 0.85, 0.88)), mat("Shoe", (0.2, 0.12, 0.08))
    shawl, glasses = mat("Shawl", (0.95, 0.80, 0.35)), mat("Glasses", (0.1, 0.1, 0.1), 0.4)

    root = bpy.data.objects.new("Grandma", None)
    bpy.context.collection.objects.link(root)
    root.rotation_euler.z = math.pi / 2  # model faces +X; start facing +Y (up screen)

    body = bpy.data.objects.new("GrandmaBody", None)
    bpy.context.collection.objects.link(body)
    body.parent = root

    cyl("Dress", 0.34, 0.75, (0, 0, 0.5), dress, 20, r2=0.2, parent=body)
    sphere("Shawl", 0.27, (0, 0, 0.9), shawl, body, (1.0, 1.35, 0.55))
    sphere("Head", 0.2, (0.03, 0, 1.15), skin, body)
    sphere("Hair", 0.215, (-0.03, 0, 1.2), hair, body, (1, 1.02, 0.9))
    sphere("Bun", 0.11, (-0.2, 0, 1.38), hair, body)
    sphere("Nose", 0.04, (0.22, 0, 1.13), skin, body)
    for sy in (-0.09, 0.09):
        sphere("Glass", 0.045, (0.2, sy, 1.19), glasses, body, (0.4, 1, 1), 8)
    arms, legs = [], []
    for sy in (-1, 1):
        pivot = bpy.data.objects.new("ArmPivot", None)
        bpy.context.collection.objects.link(pivot)
        pivot.parent, pivot.location = body, (0, sy * 0.33, 0.88)
        a = sphere("Arm", 0.075, (0, sy * 0.33, 0.7), skin, None, (1, 1, 2.6), 8)
        a.parent, a.matrix_parent_inverse = pivot, Matrix.Translation(-pivot.location)
        arms.append(pivot)
        leg = bpy.data.objects.new("LegPivot", None)
        bpy.context.collection.objects.link(leg)
        leg.parent, leg.location = root, (0, sy * 0.13, 0.2)
        sh = sphere("Shoe", 0.1, (0.05, sy * 0.13, 0.06), shoe, None, (1.5, 1, 0.8), 8)
        sh.parent, sh.matrix_parent_inverse = leg, Matrix.Translation(-leg.location)
        legs.append(leg)
    root.location = (x, y, 0)
    return root, body, arms, legs


def build_world():
    clear_scene()
    scn = bpy.context.scene
    build_ground()
    for i, (x, y, s) in enumerate(TREES):
        build_tree(i, x, y, s)
    for i, (x, y, s) in enumerate(ROCKS):
        build_rock(i, x, y, s)
    build_bench(*BENCH)
    for x, y in ((-3.6, -1.0), (3.6, -1.0), (-3.4, 2.7), (3.6, 2.8)):
        build_lamp(x, y)
    for name, text, _, x, y in PORTALS:
        build_portal(name, text, x, y)
    label("Grandma", (GRANDMA_START[0] + 2.3, GRANDMA_START[1], 0.02), 0.4, (1, 1, 1))   # beside her, off the doormat
    build_door()
    build_grandma(*GRANDMA_START)
    build_apple_game()
    build_fish_game()
    build_rat_game()
    optimize_scene()

    # sun + sky
    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(35), math.radians(10), math.radians(25)))
    sun = bpy.context.active_object
    sun.name, sun.data.energy, sun.data.angle = "Sun", 3.5, math.radians(4)

    # top-down camera framing the whole arena
    cam = bpy.data.cameras.new("HubCam")
    cam.type, cam.ortho_scale = "ORTHO", 2 * HALF_X + 2.4
    co = bpy.data.objects.new("HubCamera", cam)
    bpy.context.collection.objects.link(co)
    co.location = (0, -22 * math.sin(math.radians(14)), 22 * math.cos(math.radians(14)))
    co.rotation_euler = (math.radians(14), 0, 0)
    scn.camera = co

    scn.render.resolution_x, scn.render.resolution_y = 1600, 1000
    world = scn.world or bpy.data.worlds.new("World")
    scn.world = world
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = BG_COLOR
    bg.inputs["Strength"].default_value = 1.0
    scn.render.film_transparent = False
    for light in bpy.data.lights:
        if light.type != "SUN":
            light.use_shadow = False                       # soft sun shadow only: point-light shadows are costly
    for attr, val in (("taa_samples", 8), ("use_raytracing", False), ("use_fast_gi", True)):
        try:
            setattr(scn.eevee, attr, val)
        except (AttributeError, TypeError):
            pass
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scn.render.engine = eng
            break
        except TypeError:
            continue


# --------------------------------------------------------------------------- play
COLLIDERS = [(x, y, 0.35 * s + 0.15) for x, y, s in TREES] + \
            [(x, y, s * 0.9) for x, y, s in ROCKS] + [(BENCH[0], BENCH[1], 0.9)]
COLLIDERS += [(x, y, 0.25) for x, y in ((-3.6, -1.0), (3.6, -1.0), (-3.4, 2.7), (3.6, 2.8))]

DEADZONE = 0.2


class Gamepad:
    """Left stick / D-pad + Cross + Triangle from a PS5 (DualSense) or any Windows pad.

    Tries XInput first (Xbox-style pads, Steam Input), then the DirectInput joystick API
    (winmm), which is how a plain USB/Bluetooth DualSense shows up.
    """
    _XI_A, _XI_Y, _XI_LB, _XI_RB, _XI_B = 0x1000, 0x8000, 0x0100, 0x0200, 0x2000
    _DI_CROSS, _DI_TRIANGLE, _DI_L1, _DI_R1, _DI_CIRCLE = 1 << 1, 1 << 3, 1 << 4, 1 << 5, 1 << 2

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.xinput = self.winmm = None
        try:
            self.xinput = ctypes.windll.xinput1_4
        except (OSError, AttributeError):
            pass
        try:
            self.winmm = ctypes.windll.winmm
        except (OSError, AttributeError):
            pass

        class XState(ctypes.Structure):
            _fields_ = [("packet", wintypes.DWORD), ("buttons", wintypes.WORD), ("lt", ctypes.c_ubyte),
                        ("rt", ctypes.c_ubyte), ("lx", ctypes.c_short), ("ly", ctypes.c_short),
                        ("rx", ctypes.c_short), ("ry", ctypes.c_short)]

        class JoyInfoEx(ctypes.Structure):
            _fields_ = [(n, wintypes.DWORD) for n in (
                "size", "flags", "x", "y", "z", "r", "u", "v", "buttons", "button_n", "pov", "r1", "r2")]

        self.XState, self.JoyInfoEx = XState, JoyInfoEx
        self.prev, self.name, self.joy_id = 0, "none", None

    def _xinput(self):
        st = self.XState()
        if not self.xinput or self.xinput.XInputGetState(0, self.ct.byref(st)) != 0:
            return None
        dx, dy = st.lx / 32767, st.ly / 32767
        return (dx, dy, st.rx / 32767, st.ry / 32767, st.buttons & self._XI_A, st.buttons & self._XI_Y,
                bool(st.buttons & self._XI_LB), bool(st.buttons & self._XI_RB), bool(st.buttons & self._XI_B))

    def _dinput(self):
        if not self.winmm:
            return None
        ids = [self.joy_id] if self.joy_id is not None else range(16)
        for jid in ids:
            info = self.JoyInfoEx()
            info.size, info.flags = self.ct.sizeof(info), 0xFF       # JOY_RETURNALL
            if self.winmm.joyGetPosEx(jid, self.ct.byref(info)) == 0:
                self.joy_id = jid
                dx, dy = (info.x - 32767.5) / 32767.5, -(info.y - 32767.5) / 32767.5
                if info.pov != 0xFFFF and not (dx or dy):            # D-pad as a fallback
                    a = math.radians(info.pov / 100)
                    dx, dy = math.sin(a), math.cos(a)
                rx, ry = (info.z - 32767.5) / 32767.5, -(info.r - 32767.5) / 32767.5   # DualSense right stick
                return (dx, dy, rx, ry, info.buttons & self._DI_CROSS, info.buttons & self._DI_TRIANGLE,
                        bool(info.buttons & self._DI_L1), bool(info.buttons & self._DI_R1),
                        bool(info.buttons & self._DI_CIRCLE))
        self.joy_id = None
        return None

    @staticmethod
    def _stick(x, y):
        m = math.hypot(x, y)
        if m < DEADZONE:
            return 0.0, 0.0, 0.0
        return x / m, y / m, (min(m, 1.0) - DEADZONE) / (1 - DEADZONE)   # ramps from 0 past the deadzone

    def read(self):
        """-> dict(move=(dx, dy, mag), look=(x, y), enter, cam, zoom) or None when no pad is connected.
        enter / cam are one-shot presses; zoom is +1 (R1), -1 (L1) or 0 while held."""
        r = self._xinput()
        self.name = "XInput pad"
        if r is None:
            r, self.name = self._dinput(), "DualSense / DirectInput pad"
        if r is None:
            self.prev = 0
            return None
        lx, ly, rx, ry, enter, cam, l1, r1, back = r
        now = bool(enter) | (bool(cam) << 1) | (bool(back) << 2)
        edge = (bool(enter) and not self.prev & 1, bool(cam) and not self.prev & 2, bool(back) and not self.prev & 4)
        self.prev = now
        lk = self._stick(rx, ry)
        return {"move": self._stick(lx, ly), "look": (lk[0] * lk[2], lk[1] * lk[2]),
                "enter": edge[0], "cam": edge[1], "back": edge[2], "zoom": int(r1) - int(l1)}


# --------------------------------------------------------------------------- Game 1: apple picking
# First-person: red glove = left stick, blue glove = right stick. Hover a matching apple to grab it,
# drag it over the basket and it drops in. Built far from the hub (along +Y) and filmed by "AppleCam".
GY = 200.0                              # depth of the apple/tree/basket plane
APPLE_TIME, COUNTDOWN = 15.0, 3.0
RETURN_DELAY = 3.0                      # seconds the results show before going back to the lobby (any game)
HAND_SPEED, PICK_R, HAND_Y = 5.5, 0.85, GY - 0.6
HAND_BOUNDS = (-5.2, 5.2, 0.45, 5.6)    # x min/max, z min/max for the palm centre
BASKET = (0.0, GY - 0.5, 1.0)           # x, y, rim height
APPLE_AREA = (-4.5, 4.5, 3.4, 5.5)      # where apples may hang (x min/max, z min/max)
APPLE_LIFE, APPLE_POOL = 6.5, 14
SKY = (0.45, 0.68, 0.95, 1)
COLORS = {"red": (0.80, 0.02, 0.02), "blue": (0.03, 0.12, 0.90)}
HAND_START = {"red": (-3.9, 0.9), "blue": (3.9, 0.9)}


def build_apple_game():
    grass, bark = mat("GameGrass", (0.25, 0.55, 0.20)), mat("GameBark", (0.33, 0.20, 0.10), 0.95)
    leaf = [mat("GameLeaf1", (0.10, 0.42, 0.13)), mat("GameLeaf2", (0.15, 0.52, 0.17)),
            mat("GameLeaf3", (0.22, 0.62, 0.20))]
    wicker, dark = mat("Wicker", (0.66, 0.45, 0.22), 0.9), mat("WickerDark", (0.36, 0.21, 0.09), 0.9)
    box("GameGround", (34, 34, 0.4), (0, GY, -0.2), grass)
    cyl("GameTrunk", 0.6, 4.4, (0, GY + 1.2, 2.2), bark, 10, r2=0.4)
    rnd = random.Random(7)
    for k in range(26):                                   # big lumpy canopy behind the apples
        x = rnd.uniform(-6.5, 6.5)
        z = 5.0 + rnd.uniform(-0.9, 1.3) - abs(x) * 0.08
        blob("GameCanopy", rnd.uniform(1.1, 1.7), (x, GY + 1.2 + rnd.uniform(-0.2, 0.6), z), leaf[k % 3], None, 0.85, k)
    for k in range(7):                                    # far bushes for depth
        blob("GameBush", rnd.uniform(1.0, 1.6), (-9 + k * 3, GY + 8, 0.5), leaf[k % 3], None, 0.7, 50 + k)

    # basket: open wicker bowl with woven bands, rim and a dark floor
    bpy.ops.mesh.primitive_cone_add(vertices=20, radius1=1.0, radius2=1.55, depth=0.85, end_fill_type="NOTHING",
                                    location=(BASKET[0], BASKET[1], 0.575))
    bowl = bpy.context.active_object
    bowl.name = "Basket"
    mod = bowl.modifiers.new("Thick", "SOLIDIFY")
    mod.thickness = 0.1
    finish(bowl, wicker, True)
    cyl("BasketFloor", 0.95, 0.06, (BASKET[0], BASKET[1], 0.2), dark, 20)
    for z, r, col in ((1.0, 1.55, wicker), (0.82, 1.45, dark), (0.58, 1.27, dark), (0.34, 1.1, dark)):
        bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=0.06, major_segments=20, minor_segments=4, location=(BASKET[0], BASKET[1], z))
        finish(bpy.context.active_object, col, True)

    cam = bpy.data.cameras.new("AppleCam")
    cam.lens, cam.clip_end = 28, 60
    co = bpy.data.objects.new("AppleCam", cam)
    bpy.context.collection.objects.link(co)
    co.location, co.rotation_euler = (0, GY - 10, 5.0), (math.radians(80), 0, 0)

    for color in COLORS:
        build_hand(color)
        for i in range(APPLE_POOL):
            build_apple(color, i)
    for name, size, z in (("AppleHUD", 0.38, 6.5), ("AppleBig", 0.8, 3.3)):
        t = label("", (0, GY - 0.2, z), size)
        t.name, t.rotation_euler = name, (math.pi / 2, 0, 0)       # stand upright, facing the camera


def build_hand(color, tag=None, flip=False):
    tag = tag or color
    rgb = COLORS[color]
    glove = mat("Glove_" + color, rgb, 0.55, emit=rgb, emit_strength=0.5)
    cuff, sleeve = mat("GloveCuff", (0.95, 0.95, 0.95), 0.7), mat("GameSleeve", (0.55, 0.30, 0.45), 0.9)
    root = bpy.data.objects.new("Hand_" + tag, None)
    bpy.context.collection.objects.link(root)          # built at the origin, moved into place when played
    box("Palm", (0.62, 0.3, 0.62), (0, 0, 0), glove, root)
    cyl("Cuff", 0.33, 0.2, (0, 0, -0.42), cuff, 16, parent=root)
    cyl("Sleeve", 0.27, 3.2, (0, 0, -2.0), sleeve, 12, parent=root)
    side = (1 if color == "red" else -1) * (-1 if flip else 1)   # thumbs point toward the middle
    for i, (fx, h) in enumerate(((-0.21, 0.5), (-0.07, 0.6), (0.07, 0.56), (0.21, 0.46))):
        piv = bpy.data.objects.new(f"FingerPivot_{tag}_{i}", None)
        bpy.context.collection.objects.link(piv)
        piv.parent, piv.location = root, (fx, 0, 0.28)
        f = cyl("Finger", 0.085, h, (fx, 0, 0.28 + h / 2), glove, 10)
        f.parent, f.matrix_parent_inverse = piv, Matrix.Translation(-piv.location)
    piv = bpy.data.objects.new(f"FingerPivot_{tag}_t", None)
    bpy.context.collection.objects.link(piv)
    piv.parent, piv.location = root, (side * 0.3, 0, -0.05)
    th = cyl("Thumb", 0.09, 0.42, (side * 0.3, 0, 0.16), glove, 10)
    th.parent, th.matrix_parent_inverse = piv, Matrix.Translation(-piv.location)
    piv.rotation_euler.y = side * 0.9                     # swing the thumb in toward the middle


def join_objects(objs):
    """Join into objs[0] (keeps its origin and every material slot); returns the merged object."""
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    return objs[0]


def build_apple(color, i):
    body_m = mat("Apple_" + color, COLORS[color], 0.3)
    stem, leaf = mat("AppleStem", (0.25, 0.15, 0.05)), mat("AppleLeaf", (0.15, 0.55, 0.15))
    body = sphere("Apple_%s_%d" % (color, i), 0.42, (0, 0, 0), body_m, None, (1, 1, 0.92), 10)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    st = cyl("AppleStem", 0.03, 0.24, (0, 0, 0.42), stem, 5)
    lf = sphere("AppleLeaf", 0.12, (0.12, 0, 0.5), leaf, None, (1, 0.35, 0.15), 6)
    lf.rotation_euler.y = -0.5
    apple = join_objects([body, st, lf])
    apple.scale = (0, 0, 0)
    apple.hide_viewport = apple.hide_render = True        # shown only while in play


# --------------------------------------------------------------------------- merge static meshes
def optimize_scene():
    """Merge every static mesh into one object per material (and per hub / game area): ~600 objects
    become ~40, which is what makes the viewport run smoothly."""
    animated = set()

    def keep(ob):
        animated.add(ob)
        animated.update(ob.children_recursive)

    for ob in bpy.data.objects:
        if ob.name.startswith(("Grandma", "Crystal_", "Ring_", "Hand_", "Apple_", "AppleHUD", "AppleBig", "Label_Game", "Label_Grandma", "Fish", "Rod", "Lure", "Ripple", "Marker", "Trace", "Rat", "Door")):
            keep(ob)
    bpy.context.view_layer.update()
    statics = [o for o in bpy.context.scene.objects
               if o.type in {"MESH", "FONT"} and o not in animated and not o.name.startswith("Label_Grandma")]
    for o in statics:                                      # detach (keeping world position)
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    bpy.ops.object.select_all(action="DESELECT")
    for o in statics:                                      # text and modifiers -> plain meshes
        if o.type == "FONT" or o.modifiers:
            o.select_set(True)
    bpy.context.view_layer.objects.active = next((o for o in statics if o.select_get()), None)
    if bpy.context.view_layer.objects.active:
        bpy.ops.object.convert(target="MESH")
    groups = {}
    for o in statics:
        if o.type == "MESH" and o.material_slots and o.material_slots[0].material:
            groups.setdefault((o.material_slots[0].material.name, int(o.location.y // 100)), []).append(o)
    for (mname, area), objs in groups.items():
        if len(objs) > 1:
            merged = join_objects(objs)
            merged.name = ("Hub_" if area == 0 else f"Area{area}_") + mname
    for o in [o for o in bpy.data.objects if o.type == "EMPTY" and not o.children and o not in animated]:
        bpy.data.objects.remove(o)


class AppleGame:
    def __init__(self):
        self.cam = bpy.data.objects["AppleCam"]
        self.hud, self.big = bpy.data.objects["AppleHUD"], bpy.data.objects["AppleBig"]
        self.hands = {c: bpy.data.objects["Hand_" + c] for c in COLORS}
        self.fingers = {c: [o for o in bpy.data.objects if o.name.startswith(f"FingerPivot_{c}_") and
                            not o.name.endswith("_t")] for c in COLORS}
        self.pool = {c: [bpy.data.objects[f"Apple_{c}_{i}"] for i in range(APPLE_POOL)] for c in COLORS}

    def start(self):
        self.t, self.phase = -COUNTDOWN, "countdown"
        self.score, self.wrong = {c: 0 for c in COLORS}, 0
        self.pos = {c: list(HAND_START[c]) for c in COLORS}
        self.carry = {c: None for c in COLORS}
        self.apples, self.in_basket = [], 0
        self.free = {c: list(self.pool[c]) for c in COLORS}
        self.next_spawn, self.last_colors = 0.4, []
        self.rnd = random.Random()
        for c in COLORS:
            for ob in self.pool[c]:
                ob.scale = (0, 0, 0)
                ob.hide_viewport = ob.hide_render = True
        self.set_text(self.big, "")
        self.apply_hands(0)

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def set_text(ob, body):
        if ob.data.body != body:
            ob.data.body = body

    def apply_hands(self, dt):
        for c, ob in self.hands.items():
            x, z = self.pos[c]
            ob.location = (x, HAND_Y, z)
            curl = -1.15 if self.carry[c] else -0.15
            for piv in self.fingers[c]:
                piv.rotation_euler.x += (curl - piv.rotation_euler.x) * min(1, 14 * dt)

    def spawn(self):
        taken = [a for a in self.apples if a["state"] == "hang"]
        if len(taken) >= 4:
            return
        color = self.rnd.choice(list(COLORS))
        if len(self.last_colors) >= 2 and self.last_colors[-1] == self.last_colors[-2] == color:
            color = "blue" if color == "red" else "red"          # never three of one colour in a row
        if not self.free[color]:
            return
        for _ in range(30):
            x, z = self.rnd.uniform(APPLE_AREA[0], APPLE_AREA[1]), self.rnd.uniform(APPLE_AREA[2], APPLE_AREA[3])
            if all(math.hypot(x - a["x"], z - a["z"]) > 1.2 for a in taken):
                break
        ob = self.free[color].pop()
        ob.hide_viewport = ob.hide_render = False
        self.apples.append({"ob": ob, "color": color, "state": "hang", "born": self.t, "x": x, "y": GY, "z": z,
                            "vz": 0.0, "wob": -9.0, "s": 0.0, "tx": 0, "rest": 0})
        self.last_colors.append(color)

    def release(self, a):
        a["state"], a["vz"] = "fall", 0.0
        n = self.in_basket
        self.in_basket += 1
        a["tx"] = BASKET[0] + self.rnd.uniform(-0.6, 0.6)
        a["ty"] = BASKET[1] + self.rnd.uniform(-0.3, 0.3)
        a["rest"] = 0.5 + min(n, 7) * 0.08

    def header(self):
        s = self.score
        if self.phase == "countdown":
            return "Apple Picking - get ready!   Left stick = RED hand   Right stick = BLUE hand"
        left = max(0.0, APPLE_TIME - self.t)
        return f"Apple Picking   Time {left:4.1f}s   Red {s['red']}   Blue {s['blue']}   |   O: back" if self.phase == "play" \
            else f"Time's up!  Red {s['red']}  Blue {s['blue']}  Total {s['red'] + s['blue']}   |   returning to the lobby in {max(0.0, RETURN_DELAY - (self.t - APPLE_TIME)):.0f}s   |   O: back now"

    # -- per frame -----------------------------------------------------------------------
    def update(self, dt, pad):
        """Advance the game; returns True when the player asks to go back to the hub."""
        mv, lk = (pad["move"], pad["look"]) if pad else ((0, 0, 0), (0, 0))
        stick = {"red": (mv[0] * mv[2], mv[1] * mv[2]), "blue": lk}
        for c in COLORS:
            p = self.pos[c]
            p[0] = min(max(p[0] + stick[c][0] * HAND_SPEED * dt, HAND_BOUNDS[0]), HAND_BOUNDS[1])
            p[1] = min(max(p[1] + stick[c][1] * HAND_SPEED * dt, HAND_BOUNDS[2]), HAND_BOUNDS[3])

        self.t += dt
        if self.phase == "countdown" and self.t >= 0:
            self.phase = "play"
            self.set_text(self.big, "GO!")
        if self.phase == "play" and self.t >= APPLE_TIME:
            self.phase = "done"
            for c in COLORS:
                self.carry[c] = None
            for a in self.apples:
                if a["state"] in ("hang", "carried"):
                    a["state"] = "gone"
        if self.phase == "countdown":
            self.set_text(self.big, str(int(math.ceil(-self.t))))
        elif self.phase == "play" and self.t > 0.8:
            self.set_text(self.big, "")
        elif self.phase == "done":
            s = self.score
            self.set_text(self.big, f"Time's up!\nRed {s['red']}   Blue {s['blue']}\nTotal {s['red'] + s['blue']}")

        if self.phase == "play":
            if self.t >= self.next_spawn:
                self.spawn()
                self.next_spawn = self.t + self.rnd.uniform(0.7, 1.5)
            for c in COLORS:                                     # grab by hovering a matching apple
                if self.carry[c]:
                    continue
                px, pz = self.pos[c][0], self.pos[c][1] + 0.5
                for a in self.apples:
                    if a["state"] != "hang" or math.hypot(a["x"] - px, a["z"] - pz) > PICK_R:
                        continue
                    if a["color"] == c:
                        a["state"] = "carried"
                        self.carry[c] = a
                        break
                    if self.t - a["wob"] > 0.7:                  # wrong glove: apple just shakes
                        a["wob"] = self.t
                        self.wrong += 1

        for a in self.apples:
            ob, st = a["ob"], a["state"]
            if st == "hang":
                a["s"] += (1 - a["s"]) * min(1, 10 * dt)
                if self.t - a["born"] > APPLE_LIFE:
                    a["state"] = "gone"
            elif st == "carried":
                c = a["color"]
                hx, hz = self.pos[c]
                a["x"], a["z"], a["y"] = hx, hz + 0.58, HAND_Y - 0.15
                if abs(hx - BASKET[0]) < 1.35 and hz < 2.0:      # over the basket: let go
                    self.carry[c] = None
                    self.release(a)
            elif st == "fall":
                a["vz"] -= 20 * dt
                a["z"] += a["vz"] * dt
                a["x"] += (a["tx"] - a["x"]) * min(1, 8 * dt)
                a["y"] += (a["ty"] - a["y"]) * min(1, 8 * dt)
                if a["z"] <= a["rest"]:
                    a["z"], a["state"] = a["rest"], "in"
                    self.score[a["color"]] += 1
            if st in ("carried", "fall", "in"):
                a["s"] += (1 - a["s"]) * min(1, 12 * dt)
            elif st == "gone":
                a["s"] -= min(a["s"], 8 * dt)
                if a["s"] < 0.02:
                    a["s"] = 0.0
                    ob.hide_viewport = ob.hide_render = True
                    self.free[a["color"]].append(ob)
                    a["state"] = "dead"
            ob.location = (a["x"], a["y"], a["z"])
            ob.scale = (a["s"],) * 3
            ob.rotation_euler = (0.0, 0.0, 0.0)
            if self.t - a["wob"] < 0.45:                         # shake on wrong-colour touch
                ob.rotation_euler.y = math.sin((self.t - a["wob"]) * 45) * 0.35
        self.apples = [a for a in self.apples if a["state"] != "dead"]

        self.apply_hands(dt)
        score = self.score
        self.set_text(self.hud, f"{max(0, math.ceil(APPLE_TIME - self.t)) if self.phase != 'countdown' else int(APPLE_TIME)}s"
                                f"    Red {score['red']}   Blue {score['blue']}")
        if pad and pad["back"]:                                  # O (Circle): leave at any time
            return True
        return self.phase == "done" and self.t - APPLE_TIME >= RETURN_DELAY


# --------------------------------------------------------------------------- Game 2: harbour fishing
# First-person on a dock. Left stick moves the rod tip and traces a random shape along the water that a fish
# is swimming; when it is complete the rod goes to the right hand, which traces a second random shape. Then both
# fish are reeled into the bucket. Velocity-controlled cursor, lane tolerance, % on path.
WY0 = 402.0                                   # world y of the water-plane origin
FISH_CAM_POS, FISH_CAM_PITCH = (0.0, 394.5, 5.2), math.radians(60)
LANE_HALF, LANE_VIS, LANE_STEP = 0.5, 0.42, 0.15    # tolerance / drawn half-width / point spacing (m)
CURSOR_SPEED, LEAD = 3.2, 8                   # rod-tip speed (m/s); points the fish swims ahead of the tip
FISH_ROUNDS = 2                               # rounds: each = one left-hand fish + one right-hand fish
WATER_X, WATER_Y = 4.8, 2.9                   # cursor bounds on the water
BUCKET = (0.0, 397.5, 1.85)
FISH_COL = {"A": (0.95, 0.42, 0.08), "B": (0.10, 0.55, 0.85)}


def catmull(p0, p1, p2, p3, t):
    """Uniform Catmull-Rom spline point between p1 and p2 (the old pygame trace game used the same one)."""
    return tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                        + (-a + 3 * b - 3 * c + d) * t ** 3) for a, b, c, d in zip(p0, p1, p2, p3))


def make_path(rng, left_to_right=True):
    """A random traceable shape across the water -> (points ~LANE_STEP apart, kind)."""
    kind = rng.choice(["wave", "zigzag", "loop", "scurve"])
    x0, x1 = -4.2, 4.2
    flip = rng.choice((-1, 1))
    ctrl = []
    if kind == "wave":
        n, amp, ph, cyc = rng.randint(8, 10), rng.uniform(0.8, 1.6), rng.uniform(0, math.tau), rng.uniform(1.0, 1.8)
        for i in range(n):
            t = i / (n - 1)
            ctrl.append((x0 + (x1 - x0) * t, amp * math.sin(math.tau * cyc * t + ph)))
    elif kind == "zigzag":
        n, amp = rng.randint(5, 7), rng.uniform(1.3, 2.0)
        for i in range(n):
            t = i / (n - 1)
            y = 0.0 if i in (0, n - 1) else amp * (1 if i % 2 else -1) * rng.uniform(0.8, 1.0)
            ctrl.append((x0 + (x1 - x0) * t + rng.uniform(-0.15, 0.15), y))
    elif kind == "loop":
        r, cx = rng.uniform(0.85, 1.1), rng.uniform(-1.3, 1.3)
        y0 = rng.uniform(-2.3, 2.3 - 2 * r)
        ctrl += [(x0, y0 + rng.uniform(-0.3, 0.3)), ((x0 + cx) / 2, y0 + rng.uniform(-0.3, 0.3))]
        for k in range(11):                           # one full counter-clockwise loop
            a = math.radians(-90 + k * 30)
            ctrl.append((cx + r * math.cos(a), y0 + r + r * math.sin(a)))
        ctrl += [((cx + x1) / 2, y0 + rng.uniform(-0.3, 0.3)), (x1, y0 + rng.uniform(-0.3, 0.3))]
    else:                                             # scurve
        ys, s = [], rng.choice((-1, 1))
        for i in range(5):
            ys.append(s * (-1) ** i * rng.uniform(0.9, 2.0))
        ctrl = [(x0 + (x1 - x0) * i / 4, ys[i]) for i in range(5)]
    ctrl = [(min(max(x, -WATER_X + 0.3), WATER_X - 0.3), min(max(flip * y, -WATER_Y + 0.4), WATER_Y - 0.4))
            for x, y in ctrl]
    if not left_to_right:
        ctrl = [(-x, y) for x, y in ctrl]
    n = len(ctrl)
    dense = []
    for i in range(n - 1):
        p0, p1, p2, p3 = ctrl[max(i - 1, 0)], ctrl[i], ctrl[i + 1], ctrl[min(i + 2, n - 1)]
        dense += [catmull(p0, p1, p2, p3, k / 30) for k in range(30)]
    dense.append(ctrl[-1])
    pts, acc = [dense[0]], 0.0
    for a, b in zip(dense, dense[1:]):
        acc += math.dist(a, b)
        if acc >= LANE_STEP:
            pts.append(b)
            acc = 0.0
    return pts, kind


def apply_xform(ob):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def unit_cyl(name, r1, r2, material, verts=6):
    """Cylinder of length 1 whose origin is at its base, so it can be stretched between two points."""
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=1.0, location=(0, 0, 0.5))
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    ob.rotation_mode = "QUATERNION"
    return finish(ob, material, False)


def build_fish(tag, rgb):
    body_m, fin_m = mat("Fish_" + tag, rgb, 0.4), mat("FishFin_" + tag, tuple(c * 0.65 for c in rgb), 0.5)
    eye = mat("FishEye", (0.02, 0.02, 0.02), 0.3)
    body = sphere("Fish" + tag, 0.5, (0, 0, 0), body_m, None, (1.0, 0.42, 0.5), 10)
    parts = [body]
    tail = cyl("FishTail", 0.34, 0.6, (-0.68, 0, 0), fin_m, 3, r2=0.0)
    tail.rotation_euler, tail.scale = (0, math.pi / 2, 0), (1, 0.2, 1)
    fin = cyl("FishFin", 0.14, 0.3, (0.0, 0, 0.26), fin_m, 3, r2=0.0)
    parts += [tail, fin]
    for sy in (-0.17, 0.17):
        parts.append(sphere("FishEye", 0.07, (0.34, sy, 0.08), eye, None, (1, 1, 1), 6))
    for o in parts:
        apply_xform(o)
    fish = join_objects(parts)
    fish.hide_viewport = fish.hide_render = True
    return fish


def build_fish_game():
    water = mat("HarbourWater", (0.08, 0.42, 0.62), 0.12)
    deck, deck2 = mat("HarbourDeck", (0.50, 0.34, 0.18), 0.9), mat("HarbourDeckDark", (0.30, 0.19, 0.09), 0.9)
    hill = [mat("HarbourHill1", (0.20, 0.45, 0.22)), mat("HarbourHill2", (0.27, 0.52, 0.25))]
    white, red = mat("HarbourWhite", (0.93, 0.93, 0.95), 0.6), mat("HarbourRed", (0.80, 0.12, 0.10), 0.6)
    hull, cabin = mat("HarbourHull", (0.20, 0.25, 0.55), 0.6), mat("HarbourCabin", (0.90, 0.85, 0.70), 0.7)
    lamp = mat("HarbourLamp", (1, 0.9, 0.5), 0.3, emit=(1, 0.85, 0.4), emit_strength=3)
    wood = mat("HarbourPost", (0.28, 0.18, 0.09), 0.95)

    box("HarbourWater", (70, 70, 0.4), (0, WY0 + 10, -0.2), water)
    box("HarbourDeck", (22, 10, 0.3), (0, 392.8, 1.35), deck)             # top at z = 1.5, edge at y = 397.8
    for i in range(-10, 11, 2):
        box("HarbourPlank", (0.05, 10, 0.02), (i * 1.0, 392.8, 1.51), deck2)
    for sx in (-5.8, 5.8):
        cyl("HarbourPile", 0.2, 3.0, (sx, 397.5, 1.0), wood, 6)
        sphere("HarbourPileCap", 0.22, (sx, 397.5, 2.5), wood, None, (1, 1, 0.6), 6)
    rnd = random.Random(3)
    for k in range(7):                                                      # far shore
        blob("HarbourHill", rnd.uniform(7, 10), (-36 + k * 12, 428 + rnd.uniform(-2, 3), 0.0), hill[k % 2], None, 0.4, 90 + k)
    cyl("HarbourLighthouse", 1.2, 8.0, (-13, 417, 4.0), white, 10, r2=0.8)
    cyl("HarbourStripe", 1.0, 1.3, (-13, 417, 3.0), red, 10, r2=0.95)
    cyl("HarbourStripe", 0.92, 1.3, (-13, 417, 5.6), red, 10, r2=0.85)
    cyl("HarbourLantern", 0.9, 1.0, (-13, 417, 8.5), lamp, 8)
    cyl("HarbourRoof", 1.1, 0.9, (-13, 417, 9.4), red, 8, r2=0.0)
    for bx, by, ry, col in ((6.5, 411, 0.3, hull), (-7.5, 408, -0.5, red)):
        box("HarbourBoatHull", (3.2, 1.2, 0.7), (bx, by, 0.15), col, rot=(0, 0, ry))
        box("HarbourBoatCabin", (1.1, 0.8, 0.7), (bx + math.cos(ry) * 0.3, by + math.sin(ry) * 0.3, 0.85), cabin, rot=(0, 0, ry))
        cyl("HarbourMast", 0.05, 2.6, (bx - math.cos(ry) * 0.6, by - math.sin(ry) * 0.6, 1.6), wood, 5)
    for bx, by in ((-5.4, WY0 - 0.5), (5.5, WY0 + 1.0), (-5.6, WY0 + 3.8), (5.4, WY0 + 4.2)):
        sphere("HarbourBuoy", 0.28, (bx, by, 0.1), red, None, (1, 1, 1), 6)
        cyl("HarbourBuoyTop", 0.12, 0.35, (bx, by, 0.45), white, 6, r2=0.04)

    # bucket on the deck (open top: fish land in it)
    wood2 = mat("HarbourBucket", (0.45, 0.30, 0.16), 0.9)
    bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.55, radius2=0.72, depth=0.75, end_fill_type="NOTHING",
                                    location=BUCKET)
    bk = bpy.context.active_object
    bk.name = "HarbourBucketBody"
    bk.modifiers.new("Thick", "SOLIDIFY").thickness = 0.06
    finish(bk, wood2, True)
    cyl("HarbourBucketFloor", 0.5, 0.05, (BUCKET[0], BUCKET[1], BUCKET[2] - 0.3), mat("HarbourDark", (0.1, 0.07, 0.04)), 16)

    cam = bpy.data.cameras.new("FishCam")
    cam.lens, cam.clip_end = 28, 100
    co = bpy.data.objects.new("FishCam", cam)
    bpy.context.collection.objects.link(co)
    co.location, co.rotation_euler = FISH_CAM_POS, (FISH_CAM_PITCH, 0, 0)

    build_hand("red", "fish_red", flip=True)
    build_hand("blue", "fish_blue", flip=True)
    build_fish("A", FISH_COL["A"])
    build_fish("B", FISH_COL["B"])
    rod, line = mat("RodMat", (0.30, 0.20, 0.10), 0.5), mat("LineMat", (0.95, 0.95, 0.95), 0.4, emit=(1, 1, 1), emit_strength=1.5)
    unit_cyl("RodPole", 0.06, 0.02, rod, 6)
    unit_cyl("RodLine", 0.012, 0.012, line, 4)
    on = mat("LureOn", (0.15, 0.95, 0.35), 0.3, emit=(0.15, 0.95, 0.35), emit_strength=3)
    mat("LureOff", (0.95, 0.15, 0.15), 0.3, emit=(0.95, 0.15, 0.15), emit_strength=3)
    sphere("LureBall", 0.14, (0, 0, 0), on, None, (1, 1, 1), 8)
    gold = mat("MarkerGold", (1.0, 0.8, 0.2), 0.3, emit=(1.0, 0.75, 0.1), emit_strength=2)
    glow = mat("RippleMat", (0.9, 0.97, 1.0), 0.3, emit=(0.9, 0.97, 1.0), emit_strength=2)
    for name, r, m in (("RippleRing", 0.32, glow), ("MarkerStart", 0.6, gold), ("MarkerEnd", 0.6, gold)):
        bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=0.04, major_segments=16, minor_segments=4)
        o = bpy.context.active_object
        o.name = name
        finish(o, m, True)
    for name, base, m in (("TraceLane", mat("LaneMat", (0.55, 0.9, 1.0), 0.4, emit=(0.4, 0.85, 1.0), emit_strength=1.4), None),
                          ("TraceDone", mat("LaneDone", (0.2, 1.0, 0.4), 0.4, emit=(0.15, 0.95, 0.3), emit_strength=2.5), None)):
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(ob)
        ob.data.materials.append(base)
    for name in ("FishHUD", "FishBig"):
        t = label("", (0, 0, 0), 0.24 if name == "FishHUD" else 0.45)
        t.name = name


class FishGame:
    def __init__(self):
        o = bpy.data.objects
        self.cam = o["FishCam"]
        bpy.context.view_layer.update()
        self.hud, self.big = o["FishHUD"], o["FishBig"]
        self.fish = {"left": o["FishA"], "right": o["FishB"]}
        self.rod, self.line, self.lure = o["RodPole"], o["RodLine"], o["LureBall"]
        self.ripple, self.mstart, self.mend = o["RippleRing"], o["MarkerStart"], o["MarkerEnd"]
        self.lane, self.done = o["TraceLane"], o["TraceDone"]
        self.hands = {"left": o["Hand_fish_red"], "right": o["Hand_fish_blue"]}
        self.fingers = {s: [p for p in o if p.name.startswith(f"FingerPivot_fish_{c}_") and not p.name.endswith("_t")]
                        for s, c in (("left", "red"), ("right", "blue"))}
        self.mat_on, self.mat_off = bpy.data.materials["LureOn"], bpy.data.materials["LureOff"]
        mw = self.cam.matrix_world
        fwd, up = (mw.to_3x3() @ Vector((0, 0, -1))), (mw.to_3x3() @ Vector((0, 1, 0)))
        self.dirf = (fwd * math.cos(0.35) + up * math.sin(0.35)).normalized()
        self.grip = {}
        for side, lx in (("left", -1.45), ("right", 1.45)):                 # gloves rest at the bottom corners
            h = self.hands[side]
            h.location = mw @ Vector((lx, -1.1, -3.2))
            h.rotation_euler = self.dirf.to_track_quat("Z", "Y").to_euler()
            h.scale = (0.8, 0.8, 0.8)
            self.grip[side] = h.location + self.dirf * 0.35
        for ob, pos in ((self.hud, (0, 1.75, -5.0)), (self.big, (0, 0.3, -5.0))):
            ob.location, ob.rotation_euler = mw @ Vector(pos), self.cam.rotation_euler
        self.fish_mats = {}

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def set_text(ob, body):
        if ob.data.body != body:
            ob.data.body = body

    @staticmethod
    def w(p, z=0.04):
        return Vector((p[0], WY0 + p[1], z))

    def ribbon(self, ob, pts, upto, z):
        n = len(pts) if upto is None else upto + 1
        verts, faces = [], []
        for i in range(max(n, 0)):
            x, y = pts[i]
            a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            l = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / l * LANE_VIS, dx / l * LANE_VIS
            verts += [(x + nx, WY0 + y + ny, z), (x - nx, WY0 + y - ny, z)]
        for i in range(max(n - 1, 0)):
            faces.append((2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2))
        ob.data.clear_geometry()
        ob.data.from_pydata(verts, [], faces)
        ob.data.update()

    def start(self):
        self.rnd = random.Random()
        self.round, self.caught, self.stats = 0, 0, []
        self.clock, self.timer = 0.0, 2.8
        self.state, self.side = "intro", "left"
        self.fish_pos = {s: Vector((0, 0, 0)) for s in self.fish}
        self.fish_head = {"left": 0.0, "right": 0.0}
        self.cur, self.pts, self.prog, self.kind = [0.0, 0.0], [(0, 0), (1, 0)], 0, ""
        for f in self.fish.values():
            f.hide_viewport = f.hide_render = True
        for ob in (self.lane, self.done):
            ob.data.clear_geometry()
        self.set_text(self.big, "Harbour Fishing\nTrace the fish!\nLeft stick first, then right")
        self.place_cursor(hide=True)

    def begin_trace(self, side):
        self.side = side
        self.pts, self.kind = make_path(self.rnd, left_to_right=(side == "left"))
        self.prog, self.cur = 0, list(self.pts[0])
        self.frames = self.on_frames = self.off_count = 0
        self.off, self.t_trace, self.state, self.banner = False, 0.0, "trace", 1.6
        self.ribbon(self.lane, self.pts, None, 0.04)
        self.ribbon(self.done, self.pts, 0, 0.06)
        self.mstart.location, self.mend.location = self.w(self.pts[0], 0.07), self.w(self.pts[-1], 0.07)
        f = self.fish[side]
        f.hide_viewport = f.hide_render = False
        self.fish_pos[side] = self.w(self.pts[0], 0.12)
        self.fish_head[side] = math.atan2(self.pts[1][1] - self.pts[0][1], self.pts[1][0] - self.pts[0][0])
        hand = "LEFT" if side == "left" else "RIGHT"
        self.set_text(self.big, f"Round {self.round + 1}/{FISH_ROUNDS}   {hand} hand: trace the fish!")

    def place_cursor(self, hide=False):
        c = self.w(self.cur, 0.1)
        self.lure.location = c
        self.ripple.location = c
        grip = self.grip[self.side]
        tip = grip.lerp(c, 0.55)
        tip.z = 3.7
        for ob, a, b in ((self.rod, grip, tip), (self.line, tip, c)):
            d = b - a
            ob.location = a
            ob.rotation_quaternion = d.to_track_quat("Z", "Y")
            ob.scale = (1, 1, d.length)

    def header(self):
        if self.state == "done":
            return f"Harbour Fishing done - {self.caught} fish caught   |   back to the lobby in {max(0.0, RETURN_DELAY - self.timer):.0f}s   |   O: back now"
        hand = "LEFT stick" if self.side == "left" else "RIGHT stick"
        return f"Harbour Fishing   Round {min(self.round + 1, FISH_ROUNDS)}/{FISH_ROUNDS}   Caught {self.caught}   " \
               f"{hand}: trace the fish along the glowing lane   |   O: back"

    # -- per frame -----------------------------------------------------------------------
    def update(self, dt, pad):
        """Advance the game; returns True when the player asks to go back to the hub."""
        self.clock += dt
        if pad and pad["back"]:                                      # O (Circle): leave at any time
            return True
        mv, lk = (pad["move"], pad["look"]) if pad else ((0, 0, 0), (0, 0))
        stick = (mv[0] * mv[2], mv[1] * mv[2]) if self.side == "left" else lk

        if self.state == "intro":
            self.timer -= dt
            if self.timer <= 0:
                self.begin_trace("left")
        elif self.state == "trace":
            self.t_trace += dt
            self.banner -= dt
            if self.banner < 0:
                self.set_text(self.big, "")
            cur = self.cur
            cur[0] = min(max(cur[0] + stick[0] * CURSOR_SPEED * dt, -WATER_X), WATER_X)
            cur[1] = min(max(cur[1] + stick[1] * CURSOR_SPEED * dt, -WATER_Y), WATER_Y)
            n = len(self.pts)
            best = self.prog
            for k in range(self.prog + 1, min(self.prog + 14, n)):           # advance along the shape in order
                if math.hypot(self.pts[k][0] - cur[0], self.pts[k][1] - cur[1]) < LANE_HALF:
                    best = k
            if best > self.prog:
                self.prog = best
                self.ribbon(self.done, self.pts, self.prog, 0.06)
            lo, hi = max(0, self.prog - 5), min(n, self.prog + 14)
            near = min(math.hypot(self.pts[k][0] - cur[0], self.pts[k][1] - cur[1]) for k in range(lo, hi))
            off = near > LANE_HALF
            if off and not self.off:
                self.off_count += 1
            self.off = off
            self.frames += 1
            self.on_frames += 0 if off else 1
            self.lure.data.materials[0] = self.mat_off if off else self.mat_on
            if self.prog >= n - 3:
                pct = 100.0 * self.on_frames / max(self.frames, 1)
                self.stats.append({"round": self.round + 1, "side": self.side, "shape": self.kind,
                                   "time": round(self.t_trace, 2), "pct": round(pct), "off": self.off_count})
                if self.side == "left":
                    self.state, self.timer = "switch", 1.4
                    self.set_text(self.big, "Hooked one!\nNow the RIGHT hand")
                else:
                    self.state, self.timer = "capture", 1.8
                    self.cap_from = {s: Vector(self.fish_pos[s]) for s in self.fish}
                    self.set_text(self.big, "Caught!")
        elif self.state == "switch":
            self.timer -= dt
            if self.timer <= 0:
                self.begin_trace("right")
        elif self.state == "capture":
            self.timer -= dt
            q = 1.0 - max(self.timer, 0.0) / 1.8
            for i, s in enumerate(("left", "right")):
                qs = min(max((q - 0.25 * i) / 0.75, 0.0), 1.0)
                end = Vector((BUCKET[0] + (-0.15 if i == 0 else 0.15), BUCKET[1], BUCKET[2] + 0.35))
                pos = self.cap_from[s].lerp(end, qs)
                pos.z += 3.0 * math.sin(math.pi * qs)
                self.fish_pos[s] = pos
                self.fish_head[s] += 12 * dt
                if qs >= 1.0 and not self.fish[s].hide_viewport:
                    self.fish[s].hide_viewport = self.fish[s].hide_render = True
                    self.caught += 1
            if self.timer <= 0:
                self.round += 1
                if self.round >= FISH_ROUNDS:
                    self.finish_game()
                else:
                    self.begin_trace("left")
        elif self.state == "done":
            self.timer += dt
            return self.timer >= RETURN_DELAY

        self.animate_fish(dt)
        self.place_cursor()
        for side, h in self.hands.items():                        # active glove grips the rod
            curl = -0.9 if (side == self.side and self.state in ("trace", "switch", "capture")) else -0.1
            for piv in self.fingers[side]:
                piv.rotation_euler.x += (curl - piv.rotation_euler.x) * min(1, 12 * dt)
        pulse = 1.0 + 0.25 * math.sin(self.clock * 6)
        self.ripple.scale = (pulse, pulse, 1.0)
        self.mend.scale = (pulse, pulse, 1.0)
        self.set_text(self.hud, f"Round {min(self.round + 1, FISH_ROUNDS)}/{FISH_ROUNDS}    Fish caught {self.caught}")
        return False

    def animate_fish(self, dt):
        k = min(1, 10 * dt)
        for side, f in self.fish.items():
            if f.hide_viewport:
                continue
            if self.state == "trace" and side == self.side:           # the fish swims ahead of the rod tip
                i = min(self.prog + LEAD, len(self.pts) - 1)
                tgt = self.w(self.pts[i], 0.12)
                a, b = self.pts[max(i - 1, 0)], self.pts[min(i + 1, len(self.pts) - 1)]
                head = math.atan2(b[1] - a[1], b[0] - a[0])
                self.fish_pos[side] += (tgt - self.fish_pos[side]) * k
                d = (head - self.fish_head[side] + math.pi) % math.tau - math.pi
                self.fish_head[side] += d * k
            sway = 0.25 * math.sin(self.clock * 12 + (0 if side == "left" else 2))
            hooked = self.state in ("switch", "trace") and side == "left" and self.side == "right" or self.state == "switch"
            f.location = self.fish_pos[side] + Vector((0, 0, 0.12 * math.sin(self.clock * 9) if hooked else 0))
            if self.state == "capture":
                f.rotation_euler = (self.fish_head[side], 0, 0.6)
            else:
                f.rotation_euler = (0, 0.15 * math.sin(self.clock * 10) if hooked else 0, self.fish_head[side] + sway)
            f.scale = (1.5, 1.5, 1.5)

    def finish_game(self):
        self.state, self.timer = "done", 0.0
        lines = ["Harbour Fishing complete!", f"Fish caught: {self.caught}"]
        for r in range(1, FISH_ROUNDS + 1):
            sl = [s for s in self.stats if s["round"] == r]
            lines.append("Round %d   " % r + "   ".join(f"{'L' if s['side'] == 'left' else 'R'} {s['time']:.1f}s {s['pct']}%"
                                                         for s in sl))
        self.set_text(self.big, "\n".join(lines))
        self.lure.data.materials[0] = self.mat_on


# --------------------------------------------------------------------------- Game 3: rat catching
# One big hand hovers over a lane. Rats run right -> left, one at a time. A card (top-left) shows the rat to
# catch. Press Cross to slam: if the target rat is under the hand it turns green and the rat is caught;
# a wrong rat (or an empty slam) just makes the hand shake. 3 rounds, a different target rat each round.
RAT_TYPES = [("grey", "Grey Rat", (0.42, 0.42, 0.46)), ("white", "White Rat", (0.96, 0.96, 0.98)),
             ("ginger", "Ginger Rat", (0.80, 0.40, 0.12))]
RAT_ROUNDS, RAT_LANE_Y = 3, 600.0
HAND_HOVER, HAND_SLAM_Z, HIT_HALF, SLAM_TIME = 3.6, 0.9, 0.7, 0.09
RAT_X0, RAT_X1 = 9.0, -9.0                     # run from the right hole to the left hole
RAT_SPEED = (7.3008, 10.70784)               # m/s (original 3.0-4.4; +20%, +30%, +20%, +30% more)
RAT_CAM_POS, RAT_CAM_TARGET = (0.0, 592.0, 9.0), (0.0, 600.0, 0.6)


def build_rat(tag, rgb, stripe=False, red_eyes=False):
    """Low-poly rat as ONE mesh, long axis +X (nose at +X)."""
    body_m, pink = mat("Rat_" + tag, rgb, 0.8), mat("RatPink", (0.95, 0.62, 0.66), 0.8)
    eye_m = mat("RatEyeRed" if red_eyes else "RatEye", (0.85, 0.05, 0.05) if red_eyes else (0.02, 0.02, 0.02), 0.3)
    name = "Rat" + tag.capitalize()
    parts = [sphere(name, 0.5, (0, 0, 0.3), body_m, None, (1.0, 0.5, 0.45), 10),
             sphere("RatHead", 0.28, (0.52, 0, 0.3), body_m, None, (1.1, 0.85, 0.85), 8)]
    nose = cyl("RatNose", 0.12, 0.3, (0.82, 0, 0.28), pink, 6, r2=0.03)
    nose.rotation_euler = (0, math.pi / 2, 0)
    tail = cyl("RatTail", 0.05, 0.9, (-0.95, 0, 0.22), pink, 5, r2=0.012)
    tail.rotation_euler = (0, -math.pi / 2, 0)
    parts += [nose, tail]
    for sy in (-1, 1):
        parts.append(sphere("RatEar", 0.12, (0.42, sy * 0.2, 0.55), pink, None, (0.5, 1, 1), 6))
        parts.append(sphere("RatEye", 0.045, (0.66, sy * 0.13, 0.38), eye_m, None, (1, 1, 1), 5))
        for sx in (-0.3, 0.3):
            parts.append(sphere("RatFoot", 0.09, (sx, sy * 0.2, 0.08), pink, None, (1.3, 1, 0.7), 5))
    if stripe:
        parts.append(sphere("RatStripe", 0.35, (0, 0, 0.5), mat("RatStripe", (0.20, 0.10, 0.04), 0.9), None, (1.0, 0.18, 0.25), 6))
    for o in parts:
        apply_xform(o)
    rat = join_objects(parts)
    rat.hide_viewport = rat.hide_render = True
    return rat


def build_rat_game():
    fa, fb = mat("BarnFloorA", (0.30, 0.19, 0.09), 0.95), mat("BarnFloorB", (0.24, 0.15, 0.07), 0.95)
    lane, gold = mat("BarnLane", (0.16, 0.14, 0.13), 0.9), mat("BarnZone", (1.0, 0.8, 0.2), 0.4, emit=(1.0, 0.75, 0.1), emit_strength=2.5)
    dark, wood = mat("BarnHole", (0.04, 0.03, 0.02), 0.9), mat("BarnWood", (0.45, 0.30, 0.15), 0.9)
    sack, cheese = mat("BarnSack", (0.72, 0.62, 0.42), 0.95), mat("BarnCheese", (0.95, 0.78, 0.15), 0.6)
    box("BarnFloor", (44, 30, 0.4), (0, 602, -0.2), fb)
    for k in range(-7, 14):
        box("BarnBoard", (44, 0.94, 0.03), (0, RAT_LANE_Y + k, 0.0), fa if k % 2 else fb)
    box("BarnLane", (30, 1.9, 0.04), (0, RAT_LANE_Y, 0.02), lane)
    h = HIT_HALF
    for sx, sy, w, d in ((0, 0.95, 2 * h + 0.08, 0.08), (0, -0.95, 2 * h + 0.08, 0.08), (h, 0, 0.08, 1.9), (-h, 0, 0.08, 1.9)):
        box("BarnZone", (w, d, 0.05), (sx, RAT_LANE_Y + sy, 0.06), gold)          # where the hand will land
    for sx in (-7.2, 7.2):
        cyl("BarnHole", 0.7, 0.05, (sx, RAT_LANE_Y, 0.05), dark, 12)
    for x, y in ((-6.8, 605.0), (7.0, 605.5), (-8.0, 602.8)):
        cyl("BarnBarrel", 0.75, 1.2, (x, y, 0.6), wood, 10, r2=0.65)
    for x, y, s in ((5.6, 607.5, 1.3), (6.9, 608.2, 1.0), (-5.2, 608.0, 1.2)):
        box("BarnCrate", (s, s, s), (x, y, s / 2), wood, rot=(0, 0, x * 0.3))
    for x, y in ((-3.0, 608.5), (2.5, 609.0), (-7.5, 597.5)):
        sphere("BarnSack", 0.8, (x, y, 0.5), sack, None, (1, 1, 0.8), 8)
    cyl("BarnCheese", 0.55, 0.35, (-4.2, 597.6, 0.18), cheese, 12)

    cam = bpy.data.cameras.new("RatCam")
    cam.lens, cam.clip_end = 28, 100
    co = bpy.data.objects.new("RatCam", cam)
    bpy.context.collection.objects.link(co)
    co.location = RAT_CAM_POS
    co.rotation_euler = (Vector(RAT_CAM_TARGET) - Vector(RAT_CAM_POS)).to_track_quat("-Z", "Y").to_euler()

    hand = build_hand("red", "rat_hand", flip=True)                  # right hand, seen from above
    skin = mat("RatHand", (0.85, 0.58, 0.42), 0.6)
    root = bpy.data.objects["Hand_rat_hand"]
    for ch in list(root.children_recursive):
        if ch.name.startswith(("Cuff", "Sleeve")):
            bpy.data.objects.remove(ch)
        elif ch.type == "MESH":
            ch.material_slots[0].material = skin
            ch.visible_shadow = False                           # the gold box shows where it lands

    for k, (key, _, rgb) in enumerate(RAT_TYPES):
        rat = build_rat(key, rgb, stripe=(key == "ginger"), red_eyes=(key == "white"))
        card = rat.copy()                                            # same mesh, shown on the card
        card.name = "RatCard" + key.capitalize()
        bpy.context.collection.objects.link(card)
        card.hide_viewport = card.hide_render = True
    paper, border = mat("RatPaper", (0.97, 0.93, 0.80), 0.9), mat("RatBorder", (0.10, 0.07, 0.04), 0.9)
    box("RatCardBorder", (3.5, 2.7, 0.04), (0, 0, 0), border)
    box("RatCardPaper", (3.3, 2.5, 0.05), (0, 0, 0.03), paper)
    for name, size in (("RatHUD", 0.4), ("RatBig", 0.75), ("RatCardName", 0.3)):
        label("", (0, 0, 0), size).name = name


class RatGame:
    def __init__(self):
        o = bpy.data.objects
        self.cam = o["RatCam"]
        bpy.context.view_layer.update()
        self.hud, self.big, self.cardname = o["RatHUD"], o["RatBig"], o["RatCardName"]
        self.rats = {k: o["Rat" + k.capitalize()] for k, _, _ in RAT_TYPES}
        self.cards = {k: o["RatCard" + k.capitalize()] for k, _, _ in RAT_TYPES}
        self.names = {k: n for k, n, _ in RAT_TYPES}
        self.hand = o["Hand_rat_hand"]
        self.hand.rotation_euler = (-math.pi / 2, 0, 0)                  # palm down, fingers away from camera
        self.hand.scale = (1.8, 1.8, 1.8)
        self.skin = bpy.data.materials["RatHand"]
        self.hand_color = None
        mw = self.cam.matrix_world
        r3 = mw.to_3x3()
        for ob, pos in ((self.hud, (0, 4.3, -12)), (self.big, (0, 0.6, -12)), (self.cardname, (-5.6, 1.85, -12))):
            ob.location, ob.rotation_euler = mw @ Vector(pos), self.cam.rotation_euler
        for name, z in (("RatCardBorder", 0.0), ("RatCardPaper", 0.05)):
            ob = o[name]
            ob.location, ob.rotation_euler = mw @ Vector((-5.6, 3.4, -12 + z)), self.cam.rotation_euler
        face = (r3 @ Matrix.Rotation(math.pi / 2, 3, "X") @ Matrix.Rotation(math.pi, 3, "Z")).to_euler()   # side view, facing left
        for card in self.cards.values():
            card.location, card.rotation_euler = mw @ Vector((-5.6, 3.4, -11.7)), face
            card.scale = (1.5, 1.5, 1.5)

    @staticmethod
    def set_text(ob, body):
        if ob.data.body != body:
            ob.data.body = body

    def set_hand_color(self, state):
        if state == self.hand_color:
            return
        self.hand_color = state
        rgb = (0.15, 0.85, 0.25) if state == "ok" else (0.85, 0.58, 0.42)
        b = next(n for n in self.skin.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = 0.6 if state == "ok" else 0.0

    def start(self):
        self.rnd = random.Random()
        order = [k for k, _, _ in RAT_TYPES]
        self.rnd.shuffle(order)
        self.targets = order
        self.round, self.clock, self.state, self.timer = 0, 0.0, "intro", 2.6
        self.stats = {"caught": 0, "missed": 0, "wrong": 0, "empty": 0}
        self.armed, self.hist = True, []
        self.hs, self.ht, self.shake, self.ok = "idle", 0.0, False, False
        self.rat, self.rat_x, self.rat_v, self.hop = None, RAT_X0, 0.0, 0.0
        for ob in list(self.rats.values()) + list(self.cards.values()):
            ob.hide_viewport = ob.hide_render = True
        self.set_hand_color("normal")
        self.hand.location = (0, RAT_LANE_Y, HAND_HOVER)
        self.set_text(self.big, "Rat Catching\nSlam the rat on the card!\nFlick either stick UP to slam")
        self.set_text(self.cardname, "")

    def begin_round(self):
        t = self.targets[self.round]
        others = [k for k, _, _ in RAT_TYPES if k != t]
        runs = [t, t] + [self.rnd.choice(others) for _ in range(2)]
        self.rnd.shuffle(runs)
        self.runs, self.run_i, self.caught_this = runs, 0, False
        for k, c in self.cards.items():
            c.hide_viewport = c.hide_render = (k != t)
        self.set_text(self.cardname, self.names[t])
        self.set_text(self.big, f"Round {self.round + 1}/{RAT_ROUNDS}\nCatch the {self.names[t]}!")
        self.state, self.timer = "round_intro", 2.2

    def spawn(self):
        self.rat = self.runs[self.run_i]
        self.rat_x, self.rat_v, self.caught_this, self.hop = RAT_X0, self.rnd.uniform(*RAT_SPEED), False, 0.0
        ob = self.rats[self.rat]
        ob.hide_viewport = ob.hide_render = False
        ob.scale = (1.8, 1.8, 1.8)
        ob.rotation_euler = (0, 0, math.pi)
        self.state = "run"

    def end_run(self):
        ob = self.rats[self.rat]
        if self.rat == self.targets[self.round] and not self.caught_this:
            self.stats["missed"] += 1                              # the target ran past
        ob.hide_viewport = ob.hide_render = True
        self.rat = None
        self.run_i += 1
        if self.run_i >= len(self.runs):
            self.round += 1
            if self.round >= RAT_ROUNDS:
                self.finish_game()
                return
            self.begin_round()
        else:
            self.state, self.timer = "gap", self.rnd.uniform(0.4, 0.9)

    def finish_game(self):
        s = self.stats
        self.state, self.timer = "done", 0.0
        for c in self.cards.values():
            c.hide_viewport = c.hide_render = True
        self.set_text(self.cardname, "")
        self.set_text(self.big, f"Rat Catching complete!\nCaught {s['caught']}/{2 * RAT_ROUNDS} target rats\n"
                                f"Wrong rat slammed: {s['wrong']}   Empty slams: {s['empty']}")

    def header(self):
        s = self.stats
        if self.state == "done":
            return f"Rat Catching done - caught {s['caught']}/{2 * RAT_ROUNDS}   |   back to the lobby in " \
                   f"{max(0.0, RETURN_DELAY - self.timer):.0f}s   |   O: back now"
        return f"Rat Catching   Round {min(self.round + 1, RAT_ROUNDS)}/{RAT_ROUNDS}   Caught {s['caught']}   |   " \
               f"flick a stick UP: slam the {self.names[self.targets[min(self.round, RAT_ROUNDS - 1)]]}   |   O: back"

    def flick(self, pad):
        """True once per flick: either stick snaps up past 0.75; it must come back down (below 0.4) to re-arm."""
        up = 0.0
        if pad:
            mv, lk = pad["move"], pad["look"]
            up = max(mv[1] * mv[2], lk[1])
        self.hist = (self.hist + [up])[-9:]                      # last ~0.15 s of stick height
        if up < 0.4:
            self.armed = True
        elif up > 0.75 and self.armed and min(self.hist) < 0.35:   # a quick snap up, not a slow push
            self.armed = False
            return True
        return False

    def impact(self):
        """The hand lands: decide what it hit."""
        hit = self.rat if (self.state == "run" and abs(self.rat_x) < HIT_HALF) else None
        if hit and hit == self.targets[self.round]:
            self.ok, self.caught_this = True, True
            self.stats["caught"] += 1
            ob = self.rats[hit]
            ob.scale, ob.location = (2.2, 2.2, 0.2), (self.rat_x, RAT_LANE_Y, 0.03)
            self.state, self.timer = "squash", 0.9
            self.set_hand_color("ok")
        else:
            self.shake = True
            if hit:
                self.stats["wrong"] += 1
                self.hop = 0.35                                    # the wrong rat hops out of the way
            else:
                self.stats["empty"] += 1

    def update(self, dt, pad):
        """Advance the game; returns True when the player asks to go back to the lobby."""
        self.clock += dt
        if pad and pad["back"]:                                      # O (Circle): leave at any time
            return True
        s = self.state
        if s == "done":
            self.timer += dt
            return self.timer >= RETURN_DELAY
        if s in ("intro", "round_intro", "gap", "squash"):
            self.timer -= dt
            if self.timer <= 0:
                if s == "intro":
                    self.begin_round()
                elif s == "round_intro":
                    self.set_text(self.big, "")
                    self.state, self.timer = "gap", 0.6
                elif s == "gap":
                    self.spawn()
                else:
                    self.end_run()
        elif s == "run":
            self.rat_x -= self.rat_v * dt
            ob = self.rats[self.rat]
            run = self.clock * self.rat_v * 4.0
            self.hop = max(0.0, self.hop - dt)
            ob.location = (self.rat_x, RAT_LANE_Y, 0.04 * abs(math.sin(run)) + 0.9 * math.sin(math.pi * self.hop / 0.35) ** 2 * (self.hop > 0))
            ob.rotation_euler = (0.06 * math.sin(run), 0, math.pi)
            if self.rat_x < RAT_X1:
                self.end_run()

        # the hand: idle hover -> fast slam -> hold (green / shake) -> lift back up
        hand, h = self.hand, self.hs
        if h == "idle":
            self.set_hand_color("normal")
            hand.location = (0, RAT_LANE_Y, HAND_HOVER + 0.08 * math.sin(self.clock * 2))
            if self.flick(pad) and self.state in ("gap", "run", "squash"):
                self.hs, self.ht, self.shake, self.ok = "down", 0.0, False, False
        elif h == "down":
            self.ht += dt
            q = min(self.ht / SLAM_TIME, 1.0)
            hand.location = (0, RAT_LANE_Y, HAND_HOVER + (HAND_SLAM_Z - HAND_HOVER) * q * q)
            if q >= 1.0:
                self.impact()
                self.hs, self.ht = "hold", 0.0
        elif h == "hold":
            self.ht += dt
            amp = 0.25 * max(0.0, 1.0 - self.ht / 0.45) if self.shake else 0.0
            hand.location = (amp * math.sin(self.ht * 70), RAT_LANE_Y + amp * 0.4 * math.sin(self.ht * 53), HAND_SLAM_Z)
            if self.ht >= 0.45:
                self.hs, self.ht = "up", 0.0
        elif h == "up":
            self.ht += dt
            q = min(self.ht / 0.3, 1.0)
            hand.location = (0, RAT_LANE_Y, HAND_SLAM_Z + (HAND_HOVER - HAND_SLAM_Z) * q)
            if q >= 1.0:
                self.hs = "idle"
        self.set_text(self.hud, f"Round {min(self.round + 1, RAT_ROUNDS)}/{RAT_ROUNDS}    Caught {self.stats['caught']}")
        return False


def launch_game(script):
    """Open the pygame game in its own window; returns an error string or None."""
    path = os.path.join(GAMES_DIR, script)
    exe = shutil.which("python") or shutil.which("py")
    if not (exe and os.path.exists(path)):
        return f"cannot launch {script}: python or script not found"
    try:
        subprocess.Popen([exe, script, "--player", PLAYER_ID, "--session", SESSION], cwd=GAMES_DIR)
    except OSError as e:
        return f"cannot launch {script}: {e}"
    return None


class HUB_OT_play(bpy.types.Operator):
    bl_idname = "hub.play"
    bl_label = "Play StickDrift Hub"

    def invoke(self, context, event):
        self.root = bpy.data.objects["Grandma"]
        self.body = bpy.data.objects["GrandmaBody"]
        self.arms = [o for o in bpy.data.objects if o.name.startswith("ArmPivot")]
        self.legs = [o for o in bpy.data.objects if o.name.startswith("LegPivot")]
        self.cam = bpy.data.objects["HubCamera"]
        self.follow, self.clock = True, 0.0
        self.crystals = {n: (bpy.data.objects["Crystal_" + n], bpy.data.objects["Ring_" + n],
                             bpy.data.materials["PortalGlow_" + n]) for n, *_ in PORTALS}
        self.pad = Gamepad()
        self.games, self.game, self.mode = {"Game1": AppleGame(), "Game2": FishGame(), "Game3": RatGame()}, None, "hub"
        self.near_state, self.last_header = {}, None
        self.hinge, self.door_angle = bpy.data.objects["DoorHinge"], 0.0
        self.focus = (0.0, 0.0)
        self.yaw, self.tilt, self.zoom = 0.0, math.radians(14), 12.0     # orbit angle, tilt from top-down, zoom
        self.t, self.msg, self.heading = 0.0, "", self.root.rotation_euler.z
        self.area = context.area
        if context.space_data.type == "VIEW_3D":
            context.space_data.region_3d.view_perspective = "CAMERA"
        self.timer = context.window_manager.event_timer_add(1 / 60, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def set_header(self, txt):
        if txt != self.last_header:                           # redrawing the header every frame is wasteful
            self.last_header = txt
            self.area.header_text_set(txt)

    def set_world(self, color):
        bg = next(n for n in bpy.context.scene.world.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs["Color"].default_value = color

    def start_game(self, context, name):
        self.mode = "game"
        self.game = self.games[name]
        self.game.start()
        context.scene.camera = self.game.cam
        self.set_world(SKY)

    def stop_game(self, context):
        self.mode = "hub"
        context.scene.camera = self.cam
        self.set_world(BG_COLOR)

    def finish(self, context):
        if self.mode == "game":
            self.stop_game(context)
        context.window_manager.event_timer_remove(self.timer)
        self.area.header_text_set(None)
        return {"CANCELLED"}

    def animate(self, dt):
        self.clock += dt
        c, p = self.clock, self.root.location
        for name, label_, script, x, y in PORTALS:
            crystal, ring, glow = self.crystals[name]
            near = math.hypot(p.x - x, p.y - y) < PORTAL_R
            crystal.rotation_euler.z = c * (2.2 if near else 0.9)
            crystal.location.z = 0.9 + 0.12 * math.sin(c * 2 + x)
            ring.rotation_euler = (c * 0.6, c * 0.4, 0)
            if self.near_state.get(name) != near:               # touch the material only when it changes
                self.near_state[name] = near
                bsdf = next(n for n in glow.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
                bsdf.inputs["Emission Strength"].default_value = 3.0 if near else 1.2
        self.door_angle += ((DOOR_OPEN if self.near_door() else 0.0) - self.door_angle) * min(1, 6 * dt)
        self.hinge.rotation_euler.z = self.door_angle
        cam, k = self.cam, min(1, 5 * dt)
        scale = self.zoom if self.follow else 2 * HALF_X + 2.4
        cam.data.ortho_scale += (scale - cam.data.ortho_scale) * k
        half = cam.data.ortho_scale / 2
        fx = 0.0 if not self.follow else min(max(p.x, -(HALF_X + 1.2 - half)), HALF_X + 1.2 - half)
        fy = 0.0 if not self.follow else min(max(p.y, -(HALF_Y + 0.8 - half / 1.6)), HALF_Y + 0.8 - half / 1.6)
        sp, cp = math.sin(self.tilt), math.cos(self.tilt)
        sy, cy = math.sin(self.yaw), math.cos(self.yaw)
        tx, ty = self.focus
        self.focus = (tx + (fx - tx) * k, ty + (fy - ty) * k)
        tx, ty = self.focus
        cam.location = (tx + CAM_DIST * sp * sy, ty - CAM_DIST * sp * cy, CAM_DIST * cp)   # orbit around focus
        cam.rotation_euler = (self.tilt, 0, self.yaw)

    def near_door(self):
        p = self.root.location
        return math.hypot(p.x - DOOR[0], p.y - DOOR[1]) < DOOR_R

    def portal_near(self):
        p = self.root.location
        for name, label_, script, x, y in PORTALS:
            if math.hypot(p.x - x, p.y - y) < PORTAL_R:
                return label_, script, name
        return None

    def modal(self, context, event):
        if event.type in {"ESC", "Q"} and event.value == "PRESS":
            return self.finish(context)
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        dt = 1 / 60
        pad = self.pad.read()
        if self.mode == "game":
            if self.game.update(dt, pad):
                self.stop_game(context)
            self.set_header(self.game.header() if pad else "No controller found - connect the PS5 pad")
            return {"RUNNING_MODAL"}
        dx = dy = mag = 0.0
        if pad:
            mx, my, mag = pad["move"]
            c, s_ = math.cos(self.yaw), math.sin(self.yaw)
            dx, dy = mx * c - my * s_, mx * s_ + my * c          # stick direction relative to the camera
            lx, ly = pad["look"]
            self.yaw -= lx * ORBIT_SPEED * dt                    # right stick X: orbit all the way round
            self.tilt = min(max(self.tilt - ly * TILT_SPEED * dt, 0.0), MAX_TILT)   # Y: top-down .. 45 deg
            self.zoom = min(max(self.zoom + pad["zoom"] * ZOOM_SPEED * dt, ZOOM_RANGE[0]), ZOOM_RANGE[1])
            if pad["cam"]:
                self.follow = not self.follow
            near = self.portal_near()
            if pad["enter"] and self.near_door():                # the exit door: stop playing and open the dashboard
                self.finish(context)
                webbrowser.open(DASHBOARD_URL)
                return {"CANCELLED"}
            if pad["enter"] and near:
                if near[1] is None:
                    self.start_game(context, near[2])
                    return {"RUNNING_MODAL"}
                err = launch_game(near[1])
                self.msg = err or f"Entering {near[0]}..."
        p = self.root.location
        moving = mag > 0
        if moving:
            step = SPEED * mag * dt
            for ax, ay in ((dx * step, 0), (0, dy * step)):  # axis-separated => slides on walls
                nx = min(max(p.x + ax, -HALF_X), HALF_X)
                ny = min(max(p.y + ay, -HALF_Y), HALF_Y)
                if all(math.hypot(nx - cx, ny - cy) > cr + PLAYER_R for cx, cy, cr in COLLIDERS):
                    p.x, p.y = nx, ny
            target = math.atan2(dy, dx)
            diff = (target - self.heading + math.pi) % math.tau - math.pi
            self.heading += diff * min(1, 14 * dt)
            self.root.rotation_euler.z = self.heading
            self.t += dt * 11 * max(mag, 0.4)
        else:
            self.t *= 0.8
        swing = math.sin(self.t) * 0.7 * (1 if moving else 0)
        for i, arm in enumerate(self.arms):
            arm.rotation_euler.y = swing * (1 if i else -1)
        for i, leg in enumerate(self.legs):
            leg.rotation_euler.y = -swing * (1 if i else -1)
        self.body.location.z = abs(math.sin(self.t)) * 0.06 * (1 if moving else 0)

        self.animate(dt)
        near = self.portal_near()
        if self.near_door():
            txt = "Press X (Cross) to leave and go back to the dashboard"
        elif near:
            txt = self.msg if self.msg.startswith(("Entering", "cannot")) else f"Press X (Cross) to enter {near[0]}"
        else:
            self.msg, txt = "", "Left stick: walk   |   Right stick: orbit/tilt   |   L1/R1: zoom   |   Triangle: camera   |   walk onto a glowing pad and press X   |   Esc: quit"
        if not pad:
            txt = "No controller found - connect the PS5 pad (Esc: quit)"
        self.set_header(txt)
        return {"RUNNING_MODAL"}


def start_play():
    """Start the modal loop on the first 3D viewport (works from a script / MCP call)."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with bpy.context.temp_override(window=win, area=area, region=region):
                    return bpy.ops.hub.play("INVOKE_DEFAULT")


try:
    bpy.utils.unregister_class(HUB_OT_play)
except RuntimeError:
    pass
bpy.utils.register_class(HUB_OT_play)

build_world()
if True:
    start_play()
