"""Small orthographic mesh renderer for baked garden diorama artwork.

Vertices, face normals, a directional sun and ambient fill produce original
3D models. Back faces are culled, triangles depth sorted and rasterized at 2x.
The resulting transparent sprites are cached; gameplay never rebuilds meshes.
This is fixed-view 2.5D presentation, not a freely navigable 3D world.
"""
import math
from functools import lru_cache

import pygame


def unit(v):
    length = math.sqrt(sum(x * x for x in v)) or 1
    return tuple(x / length for x in v)


class Mesh:
    def __init__(self):
        self.faces = []

    def tri(self, points, color, normal):
        self.faces.append((points, color, unit(normal)))

    def sphere(self, center, scale, color, rings=10, segments=16):
        def point(i, j):
            a, b = math.pi * i / rings, math.tau * j / segments
            return tuple(c + r * v for c, r, v in zip(center, scale,
                         (math.sin(a) * math.cos(b), math.sin(a) * math.sin(b), math.cos(a))))
        for i in range(rings):
            for j in range(segments):
                a, b, c, d = point(i, j), point(i + 1, j), point(i + 1, j + 1), point(i, j + 1)
                for tri in ((a, b, c), (a, c, d)):
                    middle = tuple(sum(p[k] for p in tri) / 3 for k in range(3))
                    normal = tuple((v - c0) / (r * r) for v, c0, r in zip(middle, center, scale))
                    self.tri(tri, color, normal)

    def box(self, center, size, color):
        x, y, z = center
        a, b, c = (v / 2 for v in size)
        for axis in range(3):
            other = [k for k in range(3) if k != axis]
            for sign in (-1, 1):
                points = []
                for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    p = [x, y, z]
                    p[axis] += (a, b, c)[axis] * sign
                    p[other[0]] += (a, b, c)[other[0]] * u
                    p[other[1]] += (a, b, c)[other[1]] * v
                    points.append(tuple(p))
                n = [0, 0, 0]
                n[axis] = sign
                self.tri(points[:3], color, n)
                self.tri((points[0], points[2], points[3]), color, n)

    def cylinder(self, center, bottom, top, height, color, segments=20):
        x, y, z = center
        for i in range(segments):
            a, b = math.tau * i / segments, math.tau * (i + 1) / segments
            p = [(x + r * math.cos(t), y + r * math.sin(t), z + h)
                 for r, t, h in ((bottom, a, 0), (bottom, b, 0), (top, b, height), (top, a, height))]
            n = (math.cos((a + b) / 2), math.sin((a + b) / 2), (bottom - top) / height)
            self.tri(p[:3], color, n)
            self.tri((p[0], p[2], p[3]), color, n)
            self.tri(((x, y, z + height), p[3], p[2]), color, (0, 0, 1))


def bake(mesh, size, yaw=0.18, elevation=0.28):
    width, height = size
    cy, sy, ce, se = math.cos(yaw), math.sin(yaw), math.cos(elevation), math.sin(elevation)

    def project(p):
        x, y, z = p
        xx, yy = cy * x - sy * y, sy * x + cy * y
        return xx, -se * yy - ce * z, ce * yy - se * z

    vertices = [project(v) for f, _, _ in mesh.faces for v in f]
    lo = [min(v[k] for v in vertices) for k in range(2)]
    hi = [max(v[k] for v in vertices) for k in range(2)]
    zoom = min((width - 8) / (hi[0] - lo[0]), (height - 8) / (hi[1] - lo[1]))
    ox = (width - (hi[0] - lo[0]) * zoom) / 2
    oy = (height - (hi[1] - lo[1]) * zoom) / 2
    light = unit((-0.65, -0.8, 1.3))
    view = (-sy * ce, -cy * ce, se)
    surface = pygame.Surface((width * 2, height * 2), pygame.SRCALPHA)
    faces = []
    for points, color, normal in mesh.faces:
        if sum(a * b for a, b in zip(normal, view)) <= 0:
            continue
        pts = [project(p) for p in points]
        diffuse = max(0, sum(a * b for a, b in zip(normal, light)))
        strength = 0.57 + 0.43 * diffuse
        shade = tuple(min(255, int(channel * strength + 7)) for channel in color)
        faces.append((sum(p[2] for p in pts) / 3, pts, shade))
    for _, points, color in sorted(faces, key=lambda f: f[0], reverse=True):
        coords = [(round(2 * (ox + (p[0] - lo[0]) * zoom)), round(2 * (oy + (p[1] - lo[1]) * zoom))) for p in points]
        pygame.draw.polygon(surface, color, coords)
    return pygame.transform.smoothscale(surface, size)


def mabel_model():
    m = Mesh()
    teal, skin, hair, straw = (78, 143, 139), (247, 196, 153), (234, 231, 212), (242, 205, 131)
    for x in (-0.28, 0.28):
        m.sphere((x, -0.12, 0.12), (0.24, 0.4, 0.14), (80, 75, 64))
    m.cylinder((0, 0, 0.2), 0.67, 0.43, 1.35, teal)
    m.sphere((0, 0, 1.55), (0.49, 0.35, 0.35), teal)
    m.box((0, -0.65, 0.95), (0.66, 0.09, 0.91), (238, 217, 173))
    m.box((0, -0.72, 0.86), (0.35, 0.06, 0.23), (204, 177, 131))
    for x in (-0.57, 0.57):
        m.sphere((x, 0, 1.32), (0.22, 0.23, 0.44), teal)
        m.sphere((x * 1.08, -0.09, 1.02), (0.19, 0.2, 0.21), skin)
    m.sphere((0, 0.07, 2.06), (0.51, 0.43, 0.52), hair)
    m.sphere((0, -0.12, 2.03), (0.43, 0.38, 0.47), skin, 16, 24)
    m.sphere((0, -0.49, 1.99), (0.085, 0.1, 0.09), skin)
    for x in (-0.17, 0.17):
        m.sphere((x, -0.47, 2.13), (0.033, 0.035, 0.046), (38, 52, 45))
        m.sphere((x * 1.35, -0.43, 1.97), (0.08, 0.025, 0.05), (228, 151, 129))
        for i in range(18):
            a = math.tau * i / 18
            m.sphere((x + 0.135 * math.cos(a), -0.49, 2.12 + 0.12 * math.sin(a)),
                     (0.016, 0.018, 0.016), (107, 100, 77), 4, 6)
    m.box((0, -0.5, 2.13), (0.075, 0.02, 0.02), (107, 100, 77))
    for i in range(7):
        x = (i - 3) * 0.033
        m.sphere((x, -0.47, 1.82 + x * x * 4), (0.018, 0.018, 0.014), (150, 88, 76), 4, 6)
    m.cylinder((0, 0, 2.42), 0.82, 0.83, 0.08, straw)
    m.cylinder((0, 0, 2.5), 0.48, 0.42, 0.35, straw)
    m.cylinder((0, 0, 2.5), 0.488, 0.475, 0.12, (174, 111, 91))
    m.sphere((0.35, -0.36, 2.62), (0.11, 0.045, 0.11), (255, 243, 208))
    m.sphere((0.35, -0.4, 2.62), (0.045, 0.025, 0.045), (238, 180, 78))
    return m


def bird_model(hand, flap=0):
    m = Mesh()
    col = (99, 164, 197) if hand == "left" else (213, 123, 87)
    wing = (56, 105, 143) if hand == "left" else (157, 79, 64)
    m.sphere((0, 0, 0.5), (0.63, 0.39, 0.52), col)
    m.sphere((0.34, -0.05, 0.93), (0.39, 0.34, 0.38), col)
    m.sphere((0.3, -0.26, 0.46), (0.36, 0.21, 0.37), (255, 238, 200))
    m.sphere((-0.23, -0.35, 0.55 + flap), (0.4, 0.095, 0.26), wing)
    m.sphere((-0.67, 0.04, 0.49), (0.38, 0.11, 0.13), wing)
    m.sphere((0.7, -0.09, 0.85), (0.25, 0.12, 0.11), (247, 192, 87))
    m.sphere((0.45, -0.35, 0.99), (0.065, 0.035, 0.072), (31, 44, 45))
    m.sphere((0.46, -0.382, 1.015), (0.02, 0.012, 0.023), (255, 252, 234), 6, 8)
    for x in (-0.15, 0.16):
        m.sphere((x, -0.08, 0.06), (0.12, 0.17, 0.045), (150, 104, 61))
    if hand == "left":
        m.sphere((0.2, 0, 1.29), (0.1, 0.08, 0.18), wing)
    else:
        for i in range(5):
            a = i * math.tau / 5
            m.sphere((0.2 + 0.09 * math.cos(a), -0.3, 1.18 + 0.09 * math.sin(a)), (0.065, 0.04, 0.065), (255, 231, 177), 6, 8)
        m.sphere((0.2, -0.35, 1.18), (0.04, 0.025, 0.04), (239, 174, 73), 6, 8)
    return m


def tree_model():
    m = Mesh()
    m.cylinder((0, 0, 0), 0.25, 0.13, 2.1, (158, 115, 76))
    for i, (x, y, z, r) in enumerate(((-0.83, 0, 2.1, 0.92), (0.83, 0, 2.1, 0.92),
                                      (0, 0.25, 2.9, 1.0), (-0.3, -0.35, 2.0, 1.05),
                                      (0.64, -0.3, 2.5, 0.78))):
        m.sphere((x, y, z), (r, r * 0.8, r), (119 + i * 5, 170 + i * 3, 95 + i * 3), 10, 16)
    return m


def apple_model():
    m = Mesh()
    m.sphere((-0.14, 0, 0), (0.49, 0.48, 0.5), (223, 93, 64), 12, 20)
    m.sphere((0.14, 0, 0), (0.49, 0.48, 0.5), (234, 105, 69), 12, 20)
    m.cylinder((0, 0, 0.4), 0.04, 0.03, 0.3, (119, 87, 49), 8)
    m.sphere((0.19, 0, 0.61), (0.26, 0.09, 0.07), (94, 151, 76))
    return m


def flower_model():
    m = Mesh()
    m.cylinder((0, 0, 0), 0.035, 0.035, 0.6, (87, 140, 78), 8)
    m.sphere((-0.16, 0, 0.24), (0.2, 0.08, 0.08), (108, 161, 86))
    for i in range(6):
        a = math.tau * i / 6
        m.sphere((0.23 * math.cos(a), 0, 0.65 + 0.23 * math.sin(a)), (0.16, 0.08, 0.16), (255, 238, 204), 8, 12)
    m.sphere((0, -0.1, 0.65), (0.13, 0.07, 0.13), (250, 194, 79))
    return m


def cottage_model():
    m = Mesh()
    m.box((0, 0, 0.85), (2.5, 1.8, 1.7), (245, 222, 177))
    # Roof is a genuine triangular prism, with front/back gables.
    a, b, c = (-1.45, -1.05, 1.7), (1.45, -1.05, 1.7), (0, -1.05, 2.65)
    d, e, f = (-1.45, 1.05, 1.7), (1.45, 1.05, 1.7), (0, 1.05, 2.65)
    m.tri((a, b, c), (236, 204, 154), (0, -1, 0))
    for tri in ((a, c, f), (a, f, d)):
        m.tri(tri, (183, 105, 81), (-0.65, 0, 1))
    for tri in ((b, e, f), (b, f, c)):
        m.tri(tri, (167, 88, 70), (0.65, 0, 1))
    m.box((0.75, 0.3, 2.45), (0.3, 0.35, 0.85), (156, 105, 80))
    m.box((0, -0.92, 0.52), (0.55, 0.05, 1.05), (79, 135, 132))
    for x in (-0.82, 0.82):
        m.box((x, -0.94, 1.05), (0.48, 0.07, 0.55), (255, 227, 149))
        m.box((x, -0.99, 1.05), (0.035, 0.03, 0.55), (135, 125, 94))
        m.box((x, -0.99, 1.05), (0.48, 0.03, 0.035), (135, 125, 94))
        m.box((x, -1.02, 0.69), (0.6, 0.18, 0.18), (151, 111, 76))
        for i in range(3):
            m.sphere((x - 0.2 + i * 0.2, -1.05, 0.85), (0.14, 0.12, 0.11), (124, 166, 91), 6, 8)
    return m


@lru_cache(maxsize=1)
def assets():
    """One shared atlas per process; no graphics driver or new dependency required."""
    atlas = {
        "mabel": bake(mabel_model(), (320, 510), elevation=0.1),
        "tree": bake(tree_model(), (530, 520), yaw=0.1, elevation=0.15),
        "apple": bake(apple_model(), (76, 82), elevation=0.25),
        "flower": bake(flower_model(), (52, 65), elevation=0.1),
        "cottage": bake(cottage_model(), (335, 305), yaw=-0.35, elevation=0.25),
    }
    for hand in ("left", "right"):
        for frame, flap in enumerate((-0.05, 0.04, 0.14)):
            sprite = bake(bird_model(hand, flap), (110, 90), yaw=0, elevation=0.1)
            atlas[f"{hand}{frame}"] = pygame.transform.flip(sprite, hand == "right", False)
    return atlas
