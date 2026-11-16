"""
NEXUS PRIME -- procedural ultra-futuristic technocity for Blender (4.2+ / 5.x).

Everything (geometry, PBR + emissive shaders, lighting, atmosphere, cameras,
compositing) is generated from code; there are no external assets.

Run inside Blender:
    blender -b -P technocity.py -- --render hero --samples 192
or with the `bpy` Python module:
    python technocity.py --render hero street aerial --res 1920 1080

Options (after `--` when launched through the blender binary):
    --seed N            layout seed (default 7)
    --render CAM [...]  cameras to render: hero, street, aerial (default: none)
    --res W H           resolution (default 1920 1080)
    --samples N         Cycles samples (default 160)
    --out DIR           output directory (default: ./renders next to this file)
    --save PATH         save the generated scene as a .blend
"""
import argparse
import math
import os
import random
import sys

import bpy
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------
# City layout constants (metres)
# --------------------------------------------------------------------------
PITCH = 90.0          # block-to-block distance
ROAD = 26.0           # road width
BLOCK = PITCH - ROAD  # buildable block size
NB = 11               # blocks from centre to edge (city is ~2 km across)
EXTENT = (NB + 0.5) * PITCH
SPIRE_H = 1000.0
SUN_DIR = Vector((0.45, 1.0, 0.075)).normalized()   # low dusk sun behind the skyline

NEONS = ["neon_cyan", "neon_magenta", "neon_amber", "neon_violet", "neon_white"]
FACADES = ["facade_a", "facade_b", "facade_c", "facade_d", "facade_e"]
HOLOS = ["holo_cyan", "holo_magenta", "holo_amber"]

MATS = {}


# --------------------------------------------------------------------------
# Mesh builder
# --------------------------------------------------------------------------
class MeshBuilder:
    """Accumulates polygons (with per-face material and UVs) into one mesh."""

    def __init__(self):
        self.verts, self.faces, self.fmats, self.uvs, self.mats = [], [], [], [], []

    def mat(self, name):
        if name not in self.mats:
            self.mats.append(name)
        return self.mats.index(name)

    def poly(self, pts, mat, uvs=None):
        base = len(self.verts)
        self.verts.extend((p[0], p[1], p[2]) for p in pts)
        self.faces.append(tuple(range(base, base + len(pts))))
        self.fmats.append(self.mat(mat))
        if uvs is None:
            uvs = [(0.0, 0.0)] * len(pts)
        for uv in uvs:
            self.uvs.extend(uv)

    def prism(self, r0, r1, side, top="roof", bottom=None):
        """Connect two rings (CCW seen from above). Side UVs are in metres."""
        n = len(r0)
        u = 0.0
        for i in range(n):
            j = (i + 1) % n
            seg = (Vector(r0[j]) - Vector(r0[i])).length
            self.poly(
                [r0[i], r0[j], r1[j], r1[i]], side,
                [(u, r0[i][2]), (u + seg, r0[j][2]), (u + seg, r1[j][2]), (u, r1[i][2])],
            )
            u += seg
        if top:
            self.poly(list(r1), top)
        if bottom:
            self.poly(list(reversed(r0)), bottom)

    def box(self, cx, cy, z0, w, d, h, mat, top=None, rot=0.0):
        self.prism(rect(cx, cy, z0, w, d, rot), rect(cx, cy, z0 + h, w, d, rot),
                   mat, top or mat, mat)

    def torus(self, R, r, mat, matrix=None, seg=72, tube=8):
        matrix = matrix or Matrix.Identity(4)
        rings = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ring = []
            for k in range(tube):
                b = 2 * math.pi * k / tube
                rr = R + r * math.cos(b)
                ring.append(matrix @ Vector((rr * math.cos(a), rr * math.sin(a), r * math.sin(b))))
            rings.append(ring)
        for i in range(seg):
            a, b = rings[i], rings[(i + 1) % seg]
            for k in range(tube):
                k2 = (k + 1) % tube
                self.poly([a[k], b[k], b[k2], a[k2]], mat,
                          [(i / seg, 0), ((i + 1) / seg, 0), ((i + 1) / seg, 1), (i / seg, 1)])

    def build(self, name, collection, smooth=False):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.polygons.foreach_set("material_index", self.fmats)
        if smooth:
            mesh.polygons.foreach_set("use_smooth", [True] * len(self.faces))
        mesh.uv_layers.new(name="UVMap").data.foreach_set("uv", self.uvs)
        for m in self.mats:
            mesh.materials.append(MATS[m])
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj


def rect(cx, cy, z, w, d, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = sx * w / 2, sy * d / 2
        out.append((cx + x * c - y * s, cy + x * s + y * c, z))
    return out


def ngon(cx, cy, z, r, n, rot=0.0):
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n),
             cy + r * math.sin(rot + 2 * math.pi * i / n), z) for i in range(n)]


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    MATS[name] = m
    return m, m.node_tree, m.node_tree.nodes["Principled BSDF"]


def node(nt, kind, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def math_node(nt, op, a, b=None):
    n = node(nt, "ShaderNodeMath", operation=op)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def ramp(nt, fac, stops, interp="LINEAR"):
    n = node(nt, "ShaderNodeValToRGB")
    cr = n.color_ramp
    cr.interpolation = interp
    while len(cr.elements) < len(stops):
        cr.elements.new(0.5)
    for el, (pos, col) in zip(cr.elements, stops):
        el.position = pos
        el.color = (*col, 1.0)
    nt.links.new(fac, n.inputs[0])
    return n.outputs[0]


def mix_color(nt, fac, a, b):
    n = node(nt, "ShaderNodeMix", data_type="RGBA")
    nt.links.new(fac, n.inputs[0])
    for sock, v in ((n.inputs[6], a), (n.inputs[7], b)):
        if isinstance(v, tuple):
            sock.default_value = (*v, 1.0)
        else:
            nt.links.new(v, sock)
    return n.outputs[2]


def make_facade(name, cell_w, cell_h, win, lit, palette, glass, frame, strength, panes=2):
    """Curtain-wall shader: procedural window grid with per-window random
    lighting, clustered occupancy and mirror-like glazing."""
    m, nt, bsdf = new_mat(name)
    uv = node(nt, "ShaderNodeTexCoord").outputs["UV"]
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(uv, sep.inputs[0])
    cu = math_node(nt, "DIVIDE", sep.outputs[0], cell_w)
    cv = math_node(nt, "DIVIDE", sep.outputs[1], cell_h)
    fu, fv = math_node(nt, "FRACT", cu), math_node(nt, "FRACT", cv)
    iu, iv = math_node(nt, "FLOOR", cu), math_node(nt, "FLOOR", cv)
    mask = math_node(nt, "GREATER_THAN", fu, win[0])
    for op, src, lim in (("LESS_THAN", fu, win[1]), ("GREATER_THAN", fv, win[2]),
                         ("LESS_THAN", fv, win[3])):
        mask = math_node(nt, "MULTIPLY", mask, math_node(nt, op, src, lim))

    seed = math_node(nt, "MULTIPLY", node(nt, "ShaderNodeObjectInfo").outputs["Random"], 913.0)
    cell = node(nt, "ShaderNodeCombineXYZ")
    for i, s in enumerate((iu, iv, seed)):
        nt.links.new(s, cell.inputs[i])
    wn = node(nt, "ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    nt.links.new(cell.outputs[0], wn.inputs["Vector"])
    rgb = node(nt, "ShaderNodeSeparateColor")
    nt.links.new(wn.outputs["Color"], rgb.inputs[0])

    # occupancy clusters: whole floors / zones go dark together
    cl_vec = node(nt, "ShaderNodeCombineXYZ")
    nt.links.new(math_node(nt, "MULTIPLY", iu, 0.09), cl_vec.inputs[0])
    nt.links.new(math_node(nt, "MULTIPLY", iv, 0.22), cl_vec.inputs[1])
    nt.links.new(seed, cl_vec.inputs[2])
    cl = node(nt, "ShaderNodeTexNoise")
    cl.inputs["Scale"].default_value = 1.0
    nt.links.new(cl_vec.outputs[0], cl.inputs["Vector"])
    thr = math_node(nt, "ADD", math_node(nt, "MULTIPLY", math_node(nt, "SUBTRACT", cl.outputs[0], 0.5), -1.3), 1.0 - lit)
    on = math_node(nt, "MULTIPLY", math_node(nt, "GREATER_THAN", wn.outputs["Value"], thr), mask)

    n = len(palette)
    col = ramp(nt, rgb.outputs[0], [(i / n, c) for i, c in enumerate(palette)], "CONSTANT")
    bright = math_node(nt, "ADD", math_node(nt, "MULTIPLY", math_node(nt, "POWER", rgb.outputs[1], 2.0), 1.6), 0.25)
    nt.links.new(col, bsdf.inputs["Emission Color"])
    # mullions split each bay into panes; interiors are unevenly lit (ceiling
    # lights at the top of the pane, furniture / blinds breaking up the glow)
    pane = math_node(nt, "GREATER_THAN", math_node(nt, "FRACT", math_node(nt, "MULTIPLY", fu, panes)), 0.08)
    grad = math_node(nt, "ADD", math_node(nt, "MULTIPLY", fv, 0.8), 0.45)
    room_vec = node(nt, "ShaderNodeCombineXYZ")
    nt.links.new(math_node(nt, "MULTIPLY", sep.outputs[0], 0.9), room_vec.inputs[0])
    nt.links.new(math_node(nt, "MULTIPLY", sep.outputs[1], 0.9), room_vec.inputs[1])
    nt.links.new(seed, room_vec.inputs[2])
    room = node(nt, "ShaderNodeTexNoise")
    room.inputs["Scale"].default_value = 1.0
    room.inputs["Detail"].default_value = 3.0
    nt.links.new(room_vec.outputs[0], room.inputs["Vector"])
    interior = math_node(nt, "ADD", math_node(nt, "MULTIPLY", room.outputs[0], 1.5), 0.2)
    level = math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", on, bright), math_node(nt, "MULTIPLY", grad, interior))
    nt.links.new(math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", level, pane), strength),
                 bsdf.inputs["Emission Strength"])
    nt.links.new(mix_color(nt, mask, frame, glass), bsdf.inputs["Base Color"])
    nt.links.new(math_node(nt, "ADD", math_node(nt, "MULTIPLY", mask, -0.3), 0.38), bsdf.inputs["Roughness"])
    bsdf.inputs["Metallic"].default_value = 0.92
    return m


def make_pbr(name, color, rough, metal=0.0):
    m, nt, bsdf = new_mat(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return m


def make_neon(name, color, strength):
    m, nt, bsdf = new_mat(name)
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Emission Color"].default_value = (*color, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    return m


def make_holo(name, color, strength=3.0):
    """Semi-transparent holographic signage: glyph blocks, bars and scanlines."""
    m, nt, bsdf = new_mat(name)
    nt.nodes.remove(bsdf)
    out = nt.nodes["Material Output"]
    uv = node(nt, "ShaderNodeTexCoord").outputs["UV"]
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(uv, sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    seed = math_node(nt, "MULTIPLY", node(nt, "ShaderNodeObjectInfo").outputs["Random"], 71.0)
    cell = node(nt, "ShaderNodeCombineXYZ")
    nt.links.new(math_node(nt, "FLOOR", math_node(nt, "MULTIPLY", u, 9.0)), cell.inputs[0])
    nt.links.new(math_node(nt, "FLOOR", math_node(nt, "MULTIPLY", v, 14.0)), cell.inputs[1])
    nt.links.new(seed, cell.inputs[2])
    wn = node(nt, "ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    nt.links.new(cell.outputs[0], wn.inputs["Vector"])
    glyph = math_node(nt, "GREATER_THAN", wn.outputs["Value"], 0.52)
    # inner gap between glyph cells
    gu = math_node(nt, "GREATER_THAN", math_node(nt, "FRACT", math_node(nt, "MULTIPLY", u, 9.0)), 0.18)
    gv = math_node(nt, "GREATER_THAN", math_node(nt, "FRACT", math_node(nt, "MULTIPLY", v, 14.0)), 0.25)
    glyph = math_node(nt, "MULTIPLY", glyph, math_node(nt, "MULTIPLY", gu, gv))
    scan = math_node(nt, "ADD", math_node(nt, "MULTIPLY", math_node(
        nt, "SINE", math_node(nt, "MULTIPLY", v, 420.0)), 0.2), 0.8)
    # frame border
    edge = math_node(nt, "MINIMUM",
                     math_node(nt, "MINIMUM", u, math_node(nt, "SUBTRACT", 1.0, u)),
                     math_node(nt, "MINIMUM", v, math_node(nt, "SUBTRACT", 1.0, v)))
    border = math_node(nt, "LESS_THAN", edge, 0.025)
    pattern = math_node(nt, "MAXIMUM", glyph, border)
    alpha = math_node(nt, "MULTIPLY", math_node(nt, "ADD", math_node(nt, "MULTIPLY", pattern, 0.82), 0.1), scan)
    em = node(nt, "ShaderNodeEmission")
    em.inputs[0].default_value = (*color, 1)
    nt.links.new(math_node(nt, "MULTIPLY", math_node(nt, "ADD", math_node(nt, "MULTIPLY", pattern, 1.0), 0.12), strength),
                 em.inputs[1])
    tr = node(nt, "ShaderNodeBsdfTransparent")
    mix = node(nt, "ShaderNodeMixShader")
    nt.links.new(alpha, mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def make_beam(name, color, strength):
    """Volumetric-looking light shaft that fades along its length (UV v)."""
    m, nt, bsdf = new_mat(name)
    nt.nodes.remove(bsdf)
    out = nt.nodes["Material Output"]
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(node(nt, "ShaderNodeTexCoord").outputs["UV"], sep.inputs[0])
    fade = math_node(nt, "POWER", math_node(nt, "SUBTRACT", 1.0, sep.outputs[1]), 2.2)
    em = node(nt, "ShaderNodeEmission")
    em.inputs[0].default_value = (*color, 1)
    em.inputs[1].default_value = strength
    tr = node(nt, "ShaderNodeBsdfTransparent")
    mix = node(nt, "ShaderNodeMixShader")
    nt.links.new(math_node(nt, "MULTIPLY", fade, 0.07), mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def make_ground(name):
    """Rain-slick asphalt: dark, with noise-driven puddles that mirror the neon."""
    m, nt, bsdf = new_mat(name)
    tc = node(nt, "ShaderNodeTexCoord")
    noise = node(nt, "ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.035
    noise.inputs["Detail"].default_value = 6.0
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    r = ramp(nt, noise.outputs[0], [(0.38, (0.04,) * 3), (0.62, (0.42,) * 3)])
    nt.links.new(r, bsdf.inputs["Roughness"])
    bsdf.inputs["Base Color"].default_value = (0.012, 0.013, 0.016, 1)
    return m


def make_volume(name, density, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    vol = node(nt, "ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (*color, 1)
    vol.inputs["Density"].default_value = density
    vol.inputs["Anisotropy"].default_value = 0.1
    nt.links.new(vol.outputs[0], nt.nodes["Material Output"].inputs["Volume"])
    MATS[name] = m
    return m


def build_materials():
    warm = [(1.0, 0.62, 0.28), (1.0, 0.78, 0.5), (1.0, 0.9, 0.75), (0.6, 0.85, 1.0), (1.0, 0.45, 0.15)]
    cool = [(0.35, 0.8, 1.0), (0.7, 0.9, 1.0), (0.1, 0.9, 0.95), (0.9, 0.95, 1.0), (0.3, 0.45, 1.0)]
    mixed = [(1.0, 0.75, 0.45), (0.5, 0.85, 1.0), (1.0, 0.25, 0.6), (0.9, 0.95, 1.0), (0.15, 0.95, 0.85)]
    vice = [(1.0, 0.2, 0.55), (0.55, 0.3, 1.0), (0.2, 0.8, 1.0), (1.0, 0.5, 0.8), (0.85, 0.9, 1.0)]
    #            name       cw   ch   window mask (u0,u1,v0,v1)   lit   palette glass               frame               str
    make_facade("facade_a", 3.2, 4.0, (0.08, 0.92, 0.22, 0.86), 0.24, warm, (0.02, 0.03, 0.05), (0.03, 0.03, 0.035), 3.0)
    make_facade("facade_b", 2.4, 4.5, (0.12, 0.88, 0.10, 0.92), 0.2, cool, (0.01, 0.03, 0.06), (0.015, 0.02, 0.03), 3.4)
    make_facade("facade_c", 9.0, 3.6, (0.02, 0.98, 0.30, 0.78), 0.27, mixed, (0.03, 0.03, 0.04), (0.05, 0.05, 0.055), 2.6, 5)
    make_facade("facade_d", 1.6, 12.0, (0.2, 0.8, 0.04, 0.96), 0.2, vice, (0.02, 0.015, 0.04), (0.02, 0.02, 0.025), 3.0, 1)
    make_facade("facade_e", 4.5, 3.2, (0.05, 0.95, 0.35, 0.9), 0.28, warm[:3] + cool[:2], (0.04, 0.035, 0.03), (0.07, 0.065, 0.06), 2.6, 3)
    make_facade("facade_mega", 5.0, 6.0, (0.06, 0.94, 0.15, 0.85), 0.4, cool, (0.01, 0.025, 0.05), (0.02, 0.025, 0.03), 4.5)

    make_pbr("metal", (0.035, 0.038, 0.045), 0.32, 1.0)
    make_pbr("metal_light", (0.35, 0.37, 0.4), 0.28, 1.0)
    make_pbr("roof", (0.02, 0.02, 0.024), 0.75)
    make_pbr("podium", (0.045, 0.047, 0.055), 0.45)
    make_pbr("hull", (0.55, 0.57, 0.6), 0.22, 1.0)
    make_ground("asphalt")

    make_neon("neon_cyan", (0.0, 0.85, 1.0), 7.0)
    make_neon("neon_magenta", (1.0, 0.05, 0.55), 7.0)
    make_neon("neon_amber", (1.0, 0.42, 0.04), 7.0)
    make_neon("neon_violet", (0.45, 0.15, 1.0), 8.0)
    make_neon("neon_white", (0.8, 0.9, 1.0), 5.0)
    make_neon("beacon", (1.0, 0.03, 0.02), 25.0)
    make_neon("light_white", (1.0, 0.95, 0.85), 22.0)
    make_neon("light_red", (1.0, 0.04, 0.02), 18.0)
    make_neon("light_cyan", (0.1, 0.9, 1.0), 22.0)
    make_neon("light_amber", (1.0, 0.5, 0.08), 22.0)
    make_neon("road_line", (0.0, 0.6, 0.9), 1.5)
    make_neon("core_glow", (0.55, 0.95, 1.0), 14.0)

    make_holo("holo_cyan", (0.05, 0.85, 1.0))
    make_holo("holo_magenta", (1.0, 0.08, 0.6))
    make_holo("holo_amber", (1.0, 0.5, 0.06))
    make_beam("beam_cyan", (0.3, 0.8, 1.0), 2.2)
    make_beam("beam_white", (0.8, 0.85, 1.0), 1.6)
    make_beam("beam_core", (0.5, 0.9, 1.0), 9.0)
    make_volume("haze", 0.00004, (0.45, 0.55, 0.95))
    make_volume("smog", 0.00028, (0.6, 0.5, 0.85))


# --------------------------------------------------------------------------
# Building archetypes.  Each fills a MeshBuilder inside footprint (x, y, w, d)
# with total height h, and returns the height of its bridge-able base level.
# --------------------------------------------------------------------------
def greebles(mb, rng, x, y, z, w, d, count=None):
    """Rooftop plant: HVAC blocks, tanks, masts."""
    for _ in range(count if count is not None else rng.randint(2, 6)):
        gw, gd = rng.uniform(0.12, 0.35) * w, rng.uniform(0.12, 0.35) * d
        gx = x + rng.uniform(-0.5, 0.5) * (w - gw) * 0.9
        gy = y + rng.uniform(-0.5, 0.5) * (d - gd) * 0.9
        gh = rng.uniform(1.5, 6.0)
        if rng.random() < 0.3:
            mb.prism(ngon(gx, gy, z, min(gw, gd) / 2, 10), ngon(gx, gy, z + gh, min(gw, gd) / 2, 10), "metal", "metal")
        else:
            mb.box(gx, gy, z, gw, gd, gh, "metal")
        if rng.random() < 0.25:
            mb.box(gx, gy, z + gh, gw * 0.8, 0.5, 0.35, rng.choice(NEONS))


def antenna(mb, rng, x, y, z, h):
    mb.prism(ngon(x, y, z, 1.4, 6), ngon(x, y, z + h * 0.6, 0.6, 6), "metal", "metal")
    mb.prism(ngon(x, y, z + h * 0.6, 0.45, 6), ngon(x, y, z + h, 0.12, 6), "metal_light", "metal_light")
    mb.box(x, y, z + h, 1.3, 1.3, 1.3, "beacon")
    mb.box(x, y, z + h * 0.6, 1.1, 1.1, 0.9, "beacon")


def ribs(mb, x, y, z, w, d, h, n, mat="metal", depth=0.9):
    """Vertical fins standing proud of the curtain wall."""
    for i in range(n):
        t = (i + 0.5) / n - 0.5
        for sy in (-1, 1):
            mb.box(x + t * w, y + sy * (d / 2 + depth / 2), z, 0.6, depth, h, mat)
        for sx in (-1, 1):
            mb.box(x + sx * (w / 2 + depth / 2), y + t * d, z, depth, 0.6, h, mat)


def b_stepped(mb, rng, x, y, w, d, h, fac, neon):
    levels = rng.randint(2, 4)
    cuts = [rng.uniform(0.45, 0.6)] + [rng.uniform(0.5, 1.0) for _ in range(levels - 1)]
    rest = sum(cuts[1:]) or 1.0
    heights = [cuts[0] * h] + [c / rest * (1 - cuts[0]) * h for c in cuts[1:]]
    z, cw, cd, ox, oy = 0.0, w, d, x, y
    for li, lh in enumerate(heights):
        mb.prism(rect(ox, oy, z, cw, cd), rect(ox, oy, z + lh, cw, cd), fac)
        if rng.random() < 0.55:
            ribs(mb, ox, oy, z, cw, cd, lh, rng.randint(2, 5))
        # mechanical floors
        mz = z + rng.uniform(40, 70)
        while mz < z + lh - 10:
            mb.box(ox, oy, mz, cw + 0.7, cd + 0.7, 3.0, "metal")
            mz += rng.uniform(45, 80)
        if rng.random() < 0.5:
            mb.box(ox, oy, z + lh - 0.3, cw + 0.8, cd + 0.8, 0.6, neon)
        if rng.random() < 0.12:
            for sx in (-1, 1):
                for sy in (-1, 1):
                    mb.box(ox + sx * cw / 2, oy + sy * cd / 2, z, 0.6, 0.6, lh, neon)
        z += lh
        if li < levels - 1:
            s = rng.uniform(0.62, 0.86)
            ox += rng.uniform(-1, 1) * (cw - cw * s) * 0.4
            oy += rng.uniform(-1, 1) * (cd - cd * s) * 0.4
            greebles(mb, rng, x, y, z, cw, cd, 2)
            cw, cd = cw * s, cd * s
    greebles(mb, rng, ox, oy, z, cw, cd)
    if h > 90:
        antenna(mb, rng, ox, oy, z, rng.uniform(0.08, 0.22) * h)
    return heights[0]


def b_cylinder(mb, rng, x, y, w, d, h, fac, neon):
    r, n, z = min(w, d) / 2, 28, 0.0
    sections = rng.randint(2, 3)
    for si in range(sections):
        sh = h * (0.55 if si == 0 else 0.45 / (sections - 1)) * 0.92
        mb.prism(ngon(x, y, z, r, n), ngon(x, y, z + sh, r, n), fac)
        z += sh
        mb.prism(ngon(x, y, z - 1.5, r + 2.5, n), ngon(x, y, z, r + 2.5, n), "metal", "metal", "metal")
        mb.prism(ngon(x, y, z - 1.0, r + 2.8, n), ngon(x, y, z - 0.4, r + 2.8, n), neon, None)
        r *= rng.uniform(0.68, 0.85)
    # crown
    mb.prism(ngon(x, y, z, r, n), ngon(x, y, z + h * 0.05, r * 0.55, n), "metal_light", "roof")
    mb.torus(r * 0.9, 0.6, neon, Matrix.Translation((x, y, z + h * 0.03)), 40, 6)
    antenna(mb, rng, x, y, z + h * 0.05, h * rng.uniform(0.06, 0.15))
    return 0.0


def b_twisted(mb, rng, x, y, w, d, h, fac, neon):
    n = rng.choice([3, 4, 4, 4, 5, 6])
    r0 = min(w, d) / 2 * (1.0 if n > 4 else 1.15 if n == 4 else 1.05)
    steps = max(6, int(h / 9))
    twist = rng.choice([-1, 1]) * rng.uniform(0.5, 1.7)
    taper = rng.uniform(0.5, 0.8)
    rot0 = rng.uniform(0, math.pi)
    prev = ngon(x, y, 0, r0, n, rot0)
    for k in range(1, steps + 1):
        t = k / steps
        cur = ngon(x, y, h * t, r0 * (1 - (1 - taper) * t ** 1.5), n, rot0 + twist * t)
        mb.prism(prev, cur, fac, "roof" if k == steps else None)
        # neon seam following each twisted corner
        if k % 2 == 0:
            for p, q in zip(prev, cur):
                c = Vector((x, y, 0))
                a = Vector(p) + (Vector(p) - Vector((x, y, p[2]))).normalized() * 0.5
                b = Vector(q) + (Vector(q) - Vector((x, y, q[2]))).normalized() * 0.5
                mb.poly([a + Vector((0.5, 0, 0)), a - Vector((0.5, 0, 0)), b - Vector((0.5, 0, 0)), b + Vector((0.5, 0, 0))], neon)
                mb.poly([a + Vector((0, 0.5, 0)), a - Vector((0, 0.5, 0)), b - Vector((0, 0.5, 0)), b + Vector((0, 0.5, 0))], neon)
        prev = cur
    antenna(mb, rng, x, y, h, h * rng.uniform(0.08, 0.18))
    return 0.0


def b_spire(mb, rng, x, y, w, d, h, fac, neon):
    n = rng.choice([6, 8, 12])
    r0, segs = min(w, d) / 2, 14
    body = h * 0.86
    prev = ngon(x, y, 0, r0, n)
    for k in range(1, segs + 1):
        t = k / segs
        r = r0 * (1 - 0.82 * t ** 1.4)
        cur = ngon(x, y, body * t, r, n)
        mb.prism(prev, cur, fac, "roof" if k == segs else None)
        if k % 3 == 0 and k < segs:
            mb.prism(ngon(x, y, body * t - 0.5, r + 0.6, n), ngon(x, y, body * t + 0.5, r + 0.6, n), neon, neon, neon)
        prev = cur
    # buttress fins
    for i in range(n // 2):
        a = math.pi * 2 * i / (n // 2)
        dx, dy = math.cos(a), math.sin(a)
        base = rect(x + dx * r0 * 0.95, y + dy * r0 * 0.95, 0, r0 * 0.5, 1.6, a)
        top = rect(x + dx * r0 * 0.3, y + dy * r0 * 0.3, body * 0.7, 1.0, 0.8, a)
        mb.prism(base, top, "metal", "metal")
    antenna(mb, rng, x, y, body, h * 0.14)
    return 0.0


def b_gate(mb, rng, x, y, w, d, h, fac, neon):
    """Twin towers joined by a crown and sky-lobbies."""
    swap = rng.random() < 0.5
    def r(cx, cy, z, ww, dd):
        return rect(x + (cy if swap else cx), y + (cx if swap else cy), z, dd if swap else ww, ww if swap else dd)
    dd = (w if swap else d) * rng.uniform(0.55, 0.9)
    ww = d if swap else w
    leg, hh = ww * 0.34, h * rng.uniform(0.78, 0.88)
    for s in (-1, 1):
        cx = s * (ww / 2 - leg / 2)
        mb.prism(r(cx, 0, 0, leg, dd), r(cx, 0, hh, leg, dd), fac)
        # inner neon edge
        mb.prism(r(s * (ww / 2 - leg) - s * 0.3, 0, 0, 0.6, dd + 0.6), r(s * (ww / 2 - leg) - s * 0.3, 0, hh, 0.6, dd + 0.6), neon, None)
    mb.prism(r(0, 0, hh, ww, dd), r(0, 0, h, ww, dd), fac, "roof", "metal")
    mb.prism(r(0, 0, hh - 0.8, ww - 2 * leg, dd + 0.6), r(0, 0, hh, ww - 2 * leg, dd + 0.6), neon, None, neon)
    for _ in range(rng.randint(1, 3)):
        bz = rng.uniform(0.2, 0.7) * hh
        mb.prism(r(0, 0, bz, ww - 2 * leg + 2, dd * 0.4), r(0, 0, bz + 6, ww - 2 * leg + 2, dd * 0.4), "facade_b", "metal", "metal")
    greebles(mb, rng, x, y, h, (dd if swap else ww) * 0.8, (ww if swap else dd) * 0.8)
    return 0.0


def b_blade(mb, rng, x, y, w, d, h, fac, neon):
    """Thin slab with a raked, knife-edge roofline."""
    swap = rng.random() < 0.5
    ww, dd = (w, d * rng.uniform(0.32, 0.5)) if not swap else (w * rng.uniform(0.32, 0.5), d)
    low = h * rng.uniform(0.6, 0.8)
    top = rect(x, y, h, ww, dd)
    hi = {0, 3} if swap else {0, 1}
    if rng.random() < 0.5:
        hi = {0, 1, 2, 3} - hi
    top = [(p[0], p[1], h if i in hi else low) for i, p in enumerate(top)]
    mb.prism(rect(x, y, 0, ww, dd), top, fac, "metal_light")
    # glowing roof edge
    for i in range(4):
        a, b = Vector(top[i]), Vector(top[(i + 1) % 4])
        up = Vector((0, 0, 1.0))
        mb.poly([a, b, b + up, a + up], neon)
        mb.poly([b, a, a + up, b + up], neon)
    ribs(mb, x, y, 0, ww, dd, low, rng.randint(3, 6))
    antenna(mb, rng, *top[min(hi)][:2], h, h * 0.1)
    return low * 0.8


def b_cluster(mb, rng, x, y, w, d, h, fac, neon):
    """Low-rise industrial / data-centre massing."""
    for _ in range(rng.randint(3, 6)):
        bw, bd = rng.uniform(0.3, 0.6) * w, rng.uniform(0.3, 0.6) * d
        bx = x + rng.uniform(-0.5, 0.5) * (w - bw)
        by = y + rng.uniform(-0.5, 0.5) * (d - bd)
        bh = h * rng.uniform(0.35, 1.0)
        mb.prism(rect(bx, by, 0, bw, bd), rect(bx, by, bh, bw, bd), fac)
        if rng.random() < 0.5:
            mb.box(bx, by, bh - 0.3, bw + 0.6, bd + 0.6, 0.6, neon)
        greebles(mb, rng, bx, by, bh, bw, bd, rng.randint(1, 3))
    return 0.0


def signage(mb, rng, x, y, w, d, h, base_h):
    """Holographic billboards on the base level + blade signs on corners."""
    if base_h > 40 and rng.random() < 0.32:
        bh = min(rng.uniform(0.2, 0.4) * base_h, 70)
        z0 = rng.uniform(0.2, 0.9) * (base_h - bh)
        side = rng.randrange(4)
        off = 1.6
        if side < 2:
            sy = y + (d / 2 + off) * (1 if side else -1)
            hw = w * rng.uniform(0.2, 0.36)
            pts = [(x - hw, sy, z0), (x + hw, sy, z0), (x + hw, sy, z0 + bh), (x - hw, sy, z0 + bh)]
        else:
            sx = x + (w / 2 + off) * (1 if side == 3 else -1)
            hw = d * rng.uniform(0.2, 0.36)
            pts = [(sx, y - hw, z0), (sx, y + hw, z0), (sx, y + hw, z0 + bh), (sx, y - hw, z0 + bh)]
        mb.poly(pts, rng.choice(HOLOS), [(0, 0), (1, 0), (1, 1), (0, 1)])
    if h > 60 and rng.random() < 0.3:
        sx, sy = rng.choice([-1, 1]), rng.choice([-1, 1])
        sh = rng.uniform(18, 40)
        z0 = rng.uniform(12, max(13, min(h * 0.4, 120)))
        px, py = x + sx * w / 2, y + sy * d / 2
        if rng.random() < 0.5:
            pts = [(px, py, z0), (px + sx * 5, py, z0), (px + sx * 5, py, z0 + sh), (px, py, z0 + sh)]
        else:
            pts = [(px, py, z0), (px, py + sy * 5, z0), (px, py + sy * 5, z0 + sh), (px, py, z0 + sh)]
        mb.poly(pts, rng.choice(HOLOS), [(0, 0), (0.33, 0), (0.33, 1), (0, 1)])


ARCHETYPES = {
    "stepped": b_stepped, "cylinder": b_cylinder, "twisted": b_twisted, "spire": b_spire,
    "gate": b_gate, "blade": b_blade, "cluster": b_cluster,
}


def pick_archetype(rng, h, w):
    if h < 60:
        return rng.choices(["cluster", "stepped", "blade"], [5, 4, 1])[0]
    if w < 30:
        return rng.choices(["stepped", "cylinder", "twisted", "spire", "blade"], [5, 2, 2, 2, 2])[0]
    return rng.choices(["stepped", "cylinder", "twisted", "spire", "gate", "blade"], [6, 2, 3, 2, 2, 2])[0]


# --------------------------------------------------------------------------
# City assembly
# --------------------------------------------------------------------------
def new_collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def height_at(rng, x, y):
    dist = math.hypot(x, y)
    hmax = 55 + 470 * math.exp(-(dist / 560) ** 2)
    # secondary financial cluster to break radial symmetry
    hmax += 230 * math.exp(-((x + 520) ** 2 + (y - 380) ** 2) / 200 ** 2)
    h = hmax * (0.3 + rng.random() ** 1.7 * 0.95)
    if rng.random() < 0.05:
        h *= 1.45
    return h


def build_buildings(rng, coll):
    lots = []
    for i in range(-NB, NB + 1):
        for j in range(-NB, NB + 1):
            if max(abs(i), abs(j)) <= 1:
                continue  # central plaza for the megaspire
            cx, cy = i * PITCH, j * PITCH
            if math.hypot(cx, cy) > EXTENT * (0.9 + 0.22 * rng.random()):
                continue
            if rng.random() < 0.05:
                lots.append(("plaza", cx, cy, BLOCK, BLOCK, 0))
                continue
            h = height_at(rng, cx, cy)
            if h < 90 or rng.random() < 0.22:
                q = BLOCK / 2
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        if rng.random() < 0.1:
                            continue
                        lots.append(("b", cx + sx * q / 2, cy + sy * q / 2, q - 5, q - 5,
                                     height_at(rng, cx, cy) * rng.uniform(0.5, 0.95)))
            else:
                inset = rng.uniform(4, 12)
                lots.append(("b", cx, cy, BLOCK - inset, BLOCK - inset, h))

    records = []
    for idx, (kind, x, y, w, d, h) in enumerate(lots):
        mb = MeshBuilder()
        if kind == "plaza":
            build_plaza(mb, rng, x, y, w)
            mb.build(f"Plaza_{idx:03d}", coll)
            continue
        arch = pick_archetype(rng, h, w)
        fac, neon = rng.choice(FACADES), rng.choice(NEONS[:4])
        base_h = ARCHETYPES[arch](mb, rng, x, y, w, d, h, fac, neon)
        signage(mb, rng, x, y, w, d, h, base_h if base_h else h * 0.4)
        mb.build(f"Tower_{arch}_{idx:03d}", coll)
        records.append((x, y, w, d, h, base_h))
    return records


def build_plaza(mb, rng, x, y, s):
    """Open block: landing pad, pylons and a hologram stack."""
    mb.prism(ngon(x, y, 0.6, s * 0.36, 32), ngon(x, y, 2.0, s * 0.34, 32), "metal", "podium")
    mb.torus(s * 0.35, 0.5, rng.choice(NEONS), Matrix.Translation((x, y, 2.2)), 48, 6)
    mb.torus(s * 0.2, 0.35, "neon_white", Matrix.Translation((x, y, 2.2)), 48, 6)
    col = rng.choice(HOLOS)
    for k in range(3):
        a = k * math.pi / 3
        hw, hh = s * 0.3, rng.uniform(50, 90)
        dx, dy = math.cos(a) * hw, math.sin(a) * hw
        mb.poly([(x - dx, y - dy, 14), (x + dx, y + dy, 14), (x + dx, y + dy, 14 + hh), (x - dx, y - dy, 14 + hh)],
                col, [(0, 0), (1, 0), (1, 1), (0, 1)])
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.box(x + sx * s * 0.44, y + sy * s * 0.44, 0.6, 2, 2, 22, "metal")
            mb.box(x + sx * s * 0.44, y + sy * s * 0.44, 22.6, 2.6, 2.6, 1.2, "neon_white")


def build_megaspire(coll):
    """The Nexus: a kilometre-high arcology spire anchoring the skyline."""
    mb = MeshBuilder()
    n = 24
    for r, z0, z1 in ((125, 0.6, 26), (104, 26, 60), (84, 60, 96)):
        mb.prism(ngon(0, 0, z0, r, n), ngon(0, 0, z1, r * 0.94, n), "facade_mega", "podium")
        mb.torus(r * 0.96, 1.0, "neon_cyan", Matrix.Translation((0, 0, z1 + 0.5)), 96, 6)

    def radius(z):
        t = (z - 96) / (SPIRE_H * 0.86 - 96)
        return 62 * (1 - t) ** 1.55 + 9

    body_top = SPIRE_H * 0.86
    z, prev = 96.0, ngon(0, 0, 96, radius(96), n)
    while z < body_top - 1:
        z2 = min(z + 32, body_top)
        cur = ngon(0, 0, z2, radius(z2), n)
        mb.prism(prev, cur, "facade_mega", "roof" if z2 >= body_top else None)
        prev, z = cur, z2
    # vertical light channels cut up the full height
    for i in range(6):
        a = i * math.pi / 3 + math.pi / 6
        zz = 96.0
        while zz < body_top - 1:
            z2 = min(zz + 32, body_top)
            p0 = Vector((math.cos(a) * (radius(zz) + 0.4), math.sin(a) * (radius(zz) + 0.4), zz))
            p1 = Vector((math.cos(a) * (radius(z2) + 0.4), math.sin(a) * (radius(z2) + 0.4), z2))
            t = Vector((-math.sin(a), math.cos(a), 0)) * 1.3
            mb.poly([p0 - t, p0 + t, p1 + t, p1 - t], "core_glow")
            zz = z2
    # great buttresses
    for i in range(6):
        a = i * math.pi / 3
        dx, dy = math.cos(a), math.sin(a)
        base = rect(dx * 112, dy * 112, 0.6, 76, 9, a)
        top = rect(dx * 24, dy * 24, 610, 6, 3, a)
        mb.prism(base, top, "metal", "metal")
        o0 = Vector((dx * 150.5, dy * 150.5, 0.6))
        o1 = Vector((dx * 27.3, dy * 27.3, 610))
        t = Vector((-dy, dx, 0)) * 1.0
        mb.poly([o0 - t, o0 + t, o1 + t, o1 - t], "neon_cyan")
    # sky-decks and halo rings
    for zc, extra, col in ((300, 46, "neon_cyan"), (470, 40, "neon_magenta"), (640, 30, "neon_cyan"), (770, 22, "neon_violet")):
        r = radius(zc) + extra
        mb.prism(ngon(0, 0, zc - 3, r * 0.8, 48), ngon(0, 0, zc, r, 48), "metal", "podium", "metal")
        mb.prism(ngon(0, 0, zc, r, 48), ngon(0, 0, zc + 5, r, 48), "facade_b", "podium")
        mb.torus(r + 1.5, 1.2, col, Matrix.Translation((0, 0, zc + 2.5)), 96, 6)
    # crown + needle
    mb.prism(ngon(0, 0, body_top, 14, n), ngon(0, 0, body_top + 30, 5, n), "metal_light", "metal")
    mb.prism(ngon(0, 0, body_top + 30, 3.2, 8), ngon(0, 0, SPIRE_H, 0.5, 8), "metal_light", "beacon")
    mb.prism(ngon(0, 0, body_top + 4, 15, n), ngon(0, 0, body_top + 9, 13.6, n), "core_glow", None)
    obj = mb.build("Nexus_Megaspire", coll)

    fx = MeshBuilder()
    # tilted orbital halo rings around the crown
    for tilt, R, col in ((0.42, 120, "holo_cyan"), (-0.3, 95, "holo_magenta")):
        mtx = Matrix.Translation((0, 0, body_top - 70)) @ Matrix.Rotation(tilt, 4, "X") @ Matrix.Rotation(tilt * 0.6, 4, "Y")
        ring_in = [mtx @ Vector((math.cos(2 * math.pi * i / 96) * R, math.sin(2 * math.pi * i / 96) * R, 0)) for i in range(97)]
        ring_out = [mtx @ Vector((math.cos(2 * math.pi * i / 96) * (R + 9), math.sin(2 * math.pi * i / 96) * (R + 9), 0)) for i in range(97)]
        for i in range(96):
            fx.poly([ring_in[i], ring_out[i], ring_out[i + 1], ring_in[i + 1]], col,
                    [(i / 8 % 1, 0), (i / 8 % 1, 1), (i / 8 % 1 + 0.125, 1), (i / 8 % 1 + 0.125, 0)])
        fx.torus(R + 9.5, 0.5, "neon_cyan" if tilt > 0 else "neon_magenta", mtx, 96, 5)
    # sky beam
    fx.prism(ngon(0, 0, SPIRE_H, 2.5, 12), ngon(0, 0, SPIRE_H + 2600, 9, 12), "beam_core", None)
    fx.build("Nexus_FX", coll)
    return obj


def build_ground(rng, coll):
    mb = MeshBuilder()
    s = 40000
    mb.poly([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], "asphalt")
    # raised block podiums
    for i in range(-NB, NB + 1):
        for j in range(-NB, NB + 1):
            if max(abs(i), abs(j)) <= 1:
                continue
            mb.box(i * PITCH, j * PITCH, 0, BLOCK + 6, BLOCK + 6, 0.6, "podium")
    mb.prism(ngon(0, 0, 0, 150, 48), ngon(0, 0, 0.6, 150, 48), "podium", "podium")
    # luminous lane guides
    length = 2 * EXTENT
    for k in range(-NB - 1, NB + 1):
        c = (k + 0.5) * PITCH
        if abs(k + 0.5) < 1.5:
            continue
        for off in (-ROAD / 2 + 4.2, ROAD / 2 - 4.2, 0):
            wdt = 0.5 if off else 0.25
            mb.box(c + off, 0, 0.02, wdt, length, 0.06, "road_line")
            mb.box(0, c + off, 0.02, length, wdt, 0.06, "road_line")
    mb.build("Ground", coll)


def build_skyways(rng, coll):
    """Elevated expressway loops and radial maglev lines above the street grid."""
    mb = MeshBuilder()

    def deck(x0, y0, x1, y1, z, width, neon):
        horiz = abs(x1 - x0) > abs(y1 - y0)
        L = abs(x1 - x0) + abs(y1 - y0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, d = (L + width, width) if horiz else (width, L + width)
        mb.box(cx, cy, z, w, d, 1.8, "metal", "asphalt")
        for s in (-1, 1):
            o = s * (width / 2 + 0.2)
            if horiz:
                mb.box(cx, cy + o, z + 1.2, L + width, 0.5, 1.1, neon)
            else:
                mb.box(cx + o, cy, z + 1.2, 0.5, L + width, 1.1, neon)
        steps = int(L / PITCH)
        for k in range(steps + 1):
            t = k / max(steps, 1)
            px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            mb.box(px, py, 0, 3.2, 3.2, z, "metal")

    for k, z, neon in ((3.5, 48, "neon_amber"), (7.5, 78, "neon_cyan")):
        e = k * PITCH
        deck(-e, -e, e, -e, z, 15, neon)
        deck(-e, e, e, e, z, 15, neon)
        deck(-e, -e, -e, e, z, 15, neon)
        deck(e, -e, e, e, z, 15, neon)
    # radial maglev spines into the Nexus
    r0 = 1.5 * PITCH
    for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c = PITCH * 1.5
        if sx:
            deck(sx * r0, -c * sy if sy else c, sx * EXTENT * 0.95, c, 112, 7, "neon_magenta")
        else:
            deck(-c, sy * r0, -c, sy * EXTENT * 0.95, 112, 7, "neon_magenta")
    mb.build("Skyways", coll)
    return [(3.5 * PITCH, 48), (7.5 * PITCH, 78)]


def build_bridges(rng, records, coll):
    mb = MeshBuilder()
    lookup = {(round(x / PITCH), round(y / PITCH)): (x, y, w, d, h, bh) for x, y, w, d, h, bh in records
              if abs(x / PITCH - round(x / PITCH)) < 1e-6 and abs(y / PITCH - round(y / PITCH)) < 1e-6 and bh > 0}
    for (i, j), a in lookup.items():
        for di, dj in ((1, 0), (0, 1)):
            b = lookup.get((i + di, j + dj))
            if not b or rng.random() < 0.35:
                continue
            top = min(a[5], b[5])
            if top < 125:
                continue
            z = rng.uniform(122, top - 8)
            if di:
                x0, x1 = a[0] + a[2] / 2 - 1, b[0] - b[2] / 2 + 1
                cy = (a[1] + b[1]) / 2
                mb.box((x0 + x1) / 2, cy, z, x1 - x0, 7, 5, "facade_b", "metal")
                mb.box((x0 + x1) / 2, cy, z - 0.5, x1 - x0, 7.6, 0.5, "neon_white")
            else:
                y0, y1 = a[1] + a[3] / 2 - 1, b[1] - b[3] / 2 + 1
                cx = (a[0] + b[0]) / 2
                mb.box(cx, (y0 + y1) / 2, z, 7, y1 - y0, 5, "facade_b", "metal")
                mb.box(cx, (y0 + y1) / 2, z - 0.5, 7.6, y1 - y0, 0.5, "neon_white")
    mb.build("SkyBridges", coll)


def build_traffic(rng, skyways, coll):
    """Thousands of light streaks: street traffic, expressways and air lanes."""
    mb = MeshBuilder()

    def streak(x, y, z, along_x, mat, length=7.0):
        if along_x:
            mb.box(x, y, z, length, 1.7, 0.9, mat)
        else:
            mb.box(x, y, z, 1.7, length, 0.9, mat)

    for k in range(-NB - 1, NB + 1):
        c = (k + 0.5) * PITCH
        if abs(k + 0.5) < 1.5:
            continue
        for _ in range(46):
            t = rng.uniform(-EXTENT, EXTENT) * 0.97
            lane = rng.choice([3.0, 6.5, 9.5])
            fwd = rng.random() < 0.5
            streak(c + (lane if fwd else -lane), t, 0.6, False, "light_white" if fwd else "light_red", 4.5)
            t = rng.uniform(-EXTENT, EXTENT) * 0.97
            streak(t, c + (lane if fwd else -lane), 0.6, True, "light_red" if fwd else "light_white", 4.5)
        # stacked air corridors above the avenues
        for alt, mat, count in ((150, "light_cyan", 10), (235, "light_amber", 7), (330, "light_cyan", 4)):
            if (k + alt // 10) % 2:
                continue
            for _ in range(count):
                t = rng.uniform(-EXTENT, EXTENT) * 0.98
                s = rng.choice([-1, 1])
                streak(c + s * 5, t, alt + s * 4, False, mat if s > 0 else "light_white", 8)
                t = rng.uniform(-EXTENT, EXTENT) * 0.98
                streak(t, c + s * 5, alt + 22 + s * 4, True, mat if s > 0 else "light_red", 8)
    for e, z in skyways:
        for _ in range(int(e / 4)):
            t = rng.uniform(-e, e)
            s = rng.choice([-1, 1])
            lane = rng.choice([2.5, 5.5])
            mat = "light_white" if rng.random() < 0.5 else "light_red"
            if rng.random() < 0.5:
                streak(t, s * e + (lane if mat == "light_white" else -lane), z + 2.0, True, mat, 5)
            else:
                streak(s * e + (lane if mat == "light_white" else -lane), t, z + 2.0, False, mat, 5)
    # maglev trains
    for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c = PITCH * 1.5
        for _ in range(2):
            t = rng.uniform(250, EXTENT * 0.85)
            for car in range(7):
                p = t + car * 16
                if sx:
                    mb.box(sx * p, c, 114.2, 15, 3.6, 3.4, "hull")
                    mb.box(sx * p, c, 115.6, 13.5, 3.8, 0.9, "light_cyan")
                else:
                    mb.box(-c, sy * p, 114.2, 3.6, 15, 3.4, "hull")
                    mb.box(-c, sy * p, 115.6, 3.8, 13.5, 0.9, "light_cyan")
    mb.build("Traffic", coll)


def build_ship(name, coll, scale=1.0):
    """Hero flying craft: faceted hull, swept wings, twin engines, nav lights."""
    mb = MeshBuilder()
    stations = [(-15, 0.6, 0.5), (-11, 2.6, 1.7), (-3, 3.6, 2.4), (5, 3.2, 2.1), (11, 1.8, 1.2), (15.5, 0.25, 0.25)]

    def section(xs, hw, hh):
        return [(xs, -hw, -hh * 0.4), (xs, -hw * 0.55, -hh), (xs, hw * 0.55, -hh), (xs, hw, -hh * 0.4),
                (xs, hw * 0.7, hh), (xs, -hw * 0.7, hh)]

    secs = [section(*s) for s in stations]
    for a, b in zip(secs, secs[1:]):
        for i in range(6):
            j = (i + 1) % 6
            mb.poly([a[i], b[i], b[j], a[j]], "hull")
    mb.poly(secs[0], "metal")
    mb.poly(list(reversed(secs[-1])), "hull")
    # canopy strip
    mb.poly([(4, -1.6, 2.15), (10, -0.9, 1.3), (10, 0.9, 1.3), (4, 1.6, 2.15)], "light_cyan")
    for s in (-1, 1):
        # wings
        w = [(-9, s * 3, 0), (1, s * 3, 0), (-7, s * 13, 0.8), (-11, s * 13, 0.8)]
        up = [(p[0], p[1], p[2] + 0.5) for p in w]
        order = (0, 1, 2, 3) if s > 0 else (3, 2, 1, 0)
        mb.poly([up[i] for i in order], "hull")
        mb.poly([w[i] for i in reversed(order)], "metal")
        for i in range(4):
            j = (i + 1) % 4
            mb.poly([w[i], w[j], up[j], up[i]] if s > 0 else [w[j], w[i], up[i], up[j]], "metal")
        mb.box(-9, s * 13, 0.6, 5, 0.5, 0.8, "light_red" if s < 0 else "light_cyan")
        # engine pods
        e0 = [(-16, s * 5 + 1.4 * math.cos(a), 0.2 + 1.4 * math.sin(a)) for a in [2 * math.pi * k / 10 for k in range(10)]]
        e1 = [(-8, p[1], p[2]) for p in e0]
        for i in range(10):
            j = (i + 1) % 10
            mb.poly([e0[j], e0[i], e1[i], e1[j]], "metal")
        mb.poly(e0, "light_cyan")
        mb.poly(list(reversed(e1)), "metal")
    obj = mb.build(name, coll)
    obj.scale = (scale,) * 3
    return obj


def build_fx(rng, records, coll):
    mb = MeshBuilder()
    tall = sorted(records, key=lambda r: -r[4])[:60]
    for x, y, w, d, h, _ in rng.sample(tall, 10):
        tilt = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), 1)).normalized()
        L = rng.uniform(500, 900)
        apex = Vector((x, y, h + 2))
        end = apex + tilt * L
        n = 10
        ring0 = [tuple(apex + Vector((math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0)) * 1.5) for i in range(n)]
        ring1 = [tuple(end + Vector((math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0)) * 26) for i in range(n)]
        mat = rng.choice(["beam_cyan", "beam_white"])
        for i in range(n):
            j = (i + 1) % n
            mb.poly([ring0[i], ring0[j], ring1[j], ring1[i]], mat, [(0, 0), (0, 0), (0, 1), (0, 1)])
    mb.build("Searchlights", coll)

    # giant wireframe holo-globe hovering over the western district
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=48)
    me = bpy.data.meshes.new("HoloGlobe")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MATS["neon_cyan"])
    globe = bpy.data.objects.new("HoloGlobe", me)
    globe.location = (-4 * PITCH, -2 * PITCH - PITCH / 2, 520)
    globe.rotation_euler = (0.3, 0.2, 0.5)
    mod = globe.modifiers.new("Wire", "WIREFRAME")
    mod.thickness = 0.35
    coll.objects.link(globe)


def build_environment(coll):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("DuskSky")
    world.use_nodes = True
    scene.world = world
    nt = world.node_tree
    bg = nt.nodes["Background"]
    d = node(nt, "ShaderNodeTexCoord").outputs["Generated"]
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(d, sep.inputs[0])
    elev = node(nt, "ShaderNodeMapRange")
    elev.inputs["From Min"].default_value = -0.02
    nt.links.new(sep.outputs[2], elev.inputs["Value"])
    sky = ramp(nt, elev.outputs[0], [
        (0.0, (1.0, 0.36, 0.13)), (0.05, (0.78, 0.16, 0.24)), (0.14, (0.30, 0.07, 0.32)),
        (0.30, (0.06, 0.04, 0.20)), (0.55, (0.012, 0.018, 0.075)), (1.0, (0.002, 0.004, 0.02))])
    # sun glow lobe
    dot = node(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
    nt.links.new(d, dot.inputs[0])
    dot.inputs[1].default_value = SUN_DIR
    lobe = math_node(nt, "POWER", math_node(nt, "MAXIMUM", dot.outputs["Value"], 0.0), 14.0)
    wide = math_node(nt, "POWER", math_node(nt, "MAXIMUM", dot.outputs["Value"], 0.0), 3.0)
    horizon = math_node(nt, "POWER", math_node(nt, "SUBTRACT", 1.0, elev.outputs[0]), 10.0)
    glow_f = math_node(nt, "ADD", math_node(nt, "MULTIPLY", lobe, 3.0),
                       math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", wide, horizon), 1.4))
    glow = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="ADD")
    glow.inputs[0].default_value = 1.0
    nt.links.new(sky, glow.inputs[6])
    nt.links.new(mix_color(nt, glow_f, (0, 0, 0), (1.0, 0.42, 0.14)), glow.inputs[7])
    # stars
    vor = node(nt, "ShaderNodeTexVoronoi", feature="F1")
    vor.inputs["Scale"].default_value = 260.0
    nt.links.new(d, vor.inputs["Vector"])
    star = math_node(nt, "MULTIPLY", math_node(nt, "LESS_THAN", vor.outputs["Distance"], 0.035),
                     math_node(nt, "POWER", elev.outputs[0], 0.8))
    stars = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="ADD")
    stars.inputs[0].default_value = 1.0
    nt.links.new(glow.outputs[2], stars.inputs[6])
    nt.links.new(mix_color(nt, star, (0, 0, 0), (0.9, 0.95, 1.2)), stars.inputs[7])
    nt.links.new(stars.outputs[2], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0

    def light(name, direction, color, strength, angle):
        ld = bpy.data.lights.new(name, "SUN")
        ld.color, ld.energy, ld.angle = color, strength, angle
        ob = bpy.data.objects.new(name, ld)
        ob.rotation_euler = (-Vector(direction)).to_track_quat("-Z", "Y").to_euler()
        coll.objects.link(ob)

    light("DuskSun", SUN_DIR, (1.0, 0.5, 0.32), 0.45, math.radians(3))
    light("SkyFill", Vector((-0.5, -0.6, 0.6)).normalized(), (0.35, 0.45, 1.0), 0.18, math.radians(20))

    # atmosphere: thin haze dome + denser street-level smog
    for name, mat, z1 in (("Haze", "haze", 2600), ("Smog", "smog", 170)):
        mb = MeshBuilder()
        mb.prism(rect(0, 0, 0.7, 14000, 14000), rect(0, 0, z1, 14000, 14000), mat, mat, mat)
        ob = mb.build(name, coll)
        ob.display_type = "WIRE"
        ob.visible_shadow = False


def build_cameras(coll):
    scene = bpy.context.scene

    def cam(name, loc, target, lens):
        cd = bpy.data.cameras.new(name)
        cd.lens, cd.clip_start, cd.clip_end, cd.sensor_width = lens, 1.0, 100000.0, 36.0
        ob = bpy.data.objects.new(name, cd)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        coll.objects.link(ob)
        return ob

    cams = {
        "hero": cam("Cam_Hero", (-760, -1060, 150), (-30, 0, 430), 24),
        "street": cam("Cam_Street", (PITCH / 2 - 5, -660, 11), (10, 0, 400), 18),
        "aerial": cam("Cam_Aerial", (1180, -1080, 620), (0, 40, 330), 28),
    }
    scene.camera = cams["hero"]
    return cams


def setup_render(res, samples):
    scene = bpy.context.scene
    try:
        import addon_utils
        addon_utils.enable("cycles")
    except Exception:
        pass
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.max_bounces = 5
    cy.diffuse_bounces = 2
    cy.glossy_bounces = 3
    cy.transparent_max_bounces = 12
    cy.volume_bounces = 0
    cy.sample_clamp_indirect = 6.0
    cy.sample_clamp_direct = 0.0
    cy.caustics_reflective = cy.caustics_refractive = False
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.threads_mode = "AUTO"
    vs = scene.view_settings
    vs.view_transform = "AgX"
    vs.look = "AgX - Punchy"
    vs.exposure = 0.0
    setup_compositor(scene)


def setup_compositor(scene):
    """Bloom + subtle chromatic dispersion, the 'lens' of the final frame."""
    try:
        ng = bpy.data.node_groups.new("TechnocityGrade", "CompositorNodeTree")
        ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = ng.nodes.new("CompositorNodeRLayers")
        glare = ng.nodes.new("CompositorNodeGlare")
        glare.inputs["Type"].default_value = "Bloom"
        glare.inputs["Quality"].default_value = "High"
        glare.inputs["Threshold"].default_value = 2.5
        glare.inputs["Strength"].default_value = 0.35
        glare.inputs["Size"].default_value = 0.4
        lens = ng.nodes.new("CompositorNodeLensdist")
        lens.inputs["Dispersion"].default_value = 0.012
        lens.inputs["Distortion"].default_value = 0.004
        out = ng.nodes.new("NodeGroupOutput")
        ng.links.new(rl.outputs["Image"], glare.inputs["Image"])
        ng.links.new(glare.outputs["Image"], lens.inputs["Image"])
        ng.links.new(lens.outputs["Image"], out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
        scene.render.compositor_device = "CPU"
    except Exception as exc:  # older Blender: legacy compositor API
        print("compositor (new API) unavailable:", exc)
        scene.use_nodes = True
        nt = scene.node_tree
        rl, comp = nt.nodes["Render Layers"], nt.nodes["Composite"]
        glare = nt.nodes.new("CompositorNodeGlare")
        glare.glare_type, glare.threshold = "FOG_GLOW", 1.6
        nt.links.new(rl.outputs["Image"], glare.inputs[0])
        nt.links.new(glare.outputs[0], comp.inputs[0])


def build_city(seed=7):
    rng = random.Random(seed)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    c_env, c_bld = new_collection("Environment"), new_collection("Buildings")
    c_nexus, c_infra = new_collection("Nexus"), new_collection("Infrastructure")
    c_traffic, c_fx, c_cam = new_collection("Traffic"), new_collection("FX"), new_collection("Cameras")

    build_ground(rng, c_env)
    build_environment(c_env)
    records = build_buildings(rng, c_bld)
    build_megaspire(c_nexus)
    skyways = build_skyways(rng, c_infra)
    build_bridges(rng, records, c_infra)
    build_traffic(rng, skyways, c_traffic)
    build_fx(rng, records, c_fx)
    # hero craft staged for each camera
    for i, (loc, yaw, pitch, scale) in enumerate([
            ((-880, -1180, 262), 0.95, 0.06, 1.0), ((-700, -1010, 330), 1.1, 0.0, 1.0),
            ((-620, -700, 420), 0.4, -0.05, 1.6), ((-330, -1000, 300), 2.1, 0.03, 1.2),
            ((-190, -640, 60), 1.45, 0.1, 0.6), ((-260, -520, 95), 1.6, 0.0, 0.7),
            ((820, -560, 600), 2.6, 0.0, 1.4), ((500, -300, 560), 0.3, 0.05, 1.8),
            ((-100, -900, 520), 0.0, 0.0, 2.2), ((300, 500, 480), 2.0, 0.0, 2.0)]):
        ship = build_ship(f"Craft_{i:02d}", c_traffic, scale)
        ship.location = loc
        ship.rotation_euler = (rng.uniform(-0.15, 0.15), -pitch, yaw)
    cams = build_cameras(c_cam)
    return cams, records


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--render", nargs="*", default=[], choices=["hero", "street", "aerial"])
    ap.add_argument("--res", nargs=2, type=int, default=[1920, 1080])
    ap.add_argument("--samples", type=int, default=160)
    ap.add_argument("--out", default=os.path.join(here, "renders"))
    ap.add_argument("--save", default=None)
    args, _ = ap.parse_known_args(argv)

    cams, records = build_city(args.seed)
    setup_render(args.res, args.samples)
    scene = bpy.context.scene
    polys = sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH")
    print(f"[technocity] {len(records)} towers, {len(scene.objects)} objects, {polys:,} polygons")
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save), compress=True)
        print("[technocity] saved", args.save)
    os.makedirs(args.out, exist_ok=True)
    for name in args.render:
        scene.camera = cams[name]
        scene.render.filepath = os.path.join(args.out, f"technocity_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("[technocity] rendered", scene.render.filepath)


if __name__ == "__main__":
    main()
