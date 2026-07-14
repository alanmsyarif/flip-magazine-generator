bl_info = {
    "name": "Magazine Forge",
    "author": "Amsy",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > N-Panel > Magazine Forge",
    "description": "Procedural magazine with physics-flavored page-flip animation (Geometry Nodes)",
    "category": "Object",
}

import bpy
from math import pi

NG_NAME = "MF_Magazine"


# ------------------------------------------------------------------
# Socket helpers — access by NAME (Blender 5.x safe), with optional
# type filter for multi-typed sockets (Compare, Mix, Store Attribute)
# ------------------------------------------------------------------

def sock_in(node, name, sock_type=None):
    if sock_type is not None:
        for s in node.inputs:
            if s.name == name and s.type == sock_type:
                return s
    for s in node.inputs:
        if s.name == name:
            return s
    raise KeyError(f"{node.bl_idname}: no input socket '{name}'")


def sock_out(node, name, sock_type=None):
    if sock_type is not None:
        for s in node.outputs:
            if s.name == name and s.type == sock_type:
                return s
    for s in node.outputs:
        if s.name == name:
            return s
    raise KeyError(f"{node.bl_idname}: no output socket '{name}'")


def sock_out_any(node, names, sock_type=None):
    """First matching output from a list of candidate names
    (handles renames across Blender versions, e.g. Fac -> Value)."""
    for name in names:
        try:
            return sock_out(node, name, sock_type)
        except KeyError:
            continue
    raise KeyError(f"{node.bl_idname}: no output socket among {names}")


def sock_in_any(node, names, sock_type=None):
    """First matching input from a list of candidate names
    (handles renames across Blender versions, e.g. Geometry -> Mesh)."""
    for name in names:
        try:
            return sock_in(node, name, sock_type)
        except KeyError:
            continue
    raise KeyError(f"{node.bl_idname}: no input socket among {names}")


def _mk(nt, idname, loc, label=""):
    nd = nt.nodes.new(idname)
    nd.location = loc
    if label:
        nd.label = label
    return nd


def _wire(nt, src, dst):
    """Link src into dst. src may be a NodeSocket or a numeric constant."""
    if isinstance(src, (int, float, bool)):
        dst.default_value = src
    else:
        nt.links.new(src, dst)


def _math(nt, op, loc, a=None, b=None, label=""):
    nd = _mk(nt, 'ShaderNodeMath', loc, label or op.title())
    nd.operation = op
    if a is not None:
        _wire(nt, a, nd.inputs[0])
    if b is not None:
        _wire(nt, b, nd.inputs[1])
    return nd.outputs[0]


def _combine_xyz(nt, loc, x=None, y=None, z=None, label=""):
    nd = _mk(nt, 'ShaderNodeCombineXYZ', loc, label)
    for i, v in enumerate((x, y, z)):
        if v is not None:
            _wire(nt, v, nd.inputs[i])
    return nd.outputs[0]


def _iface_in(ng, name, stype, default=None, min_=None, max_=None):
    s = ng.interface.new_socket(name=name, in_out='INPUT', socket_type=stype)
    if default is not None:
        s.default_value = default
    if min_ is not None:
        s.min_value = min_
    if max_ is not None:
        s.max_value = max_
    return s


# ------------------------------------------------------------------
# Node group builder
#
# Physics model (analytic, per-vertex, art-directable):
#   theta(t)  = smoothstep flip angle 0 -> pi, staggered per page
#   Bend      = follow-through:  -(1 - 2p) * sin(theta)
#               tip LAGS while accelerating, LEADS while decelerating
#   Droop     = gravity sag:     -cos(theta) * sin(theta)
#               max at 45/135 deg, zero when page vertical or flat
#   Flutter   = 4D noise, masked by sin(theta) so rest pages are clean
#   All terms scale by (x/W)^falloff so the spine root stays rigid,
#   and every vertex is rotated by its OWN angle around the spine —
#   distance to spine is preserved exactly (no stretching).
# ------------------------------------------------------------------

def build_group():
    old = bpy.data.node_groups.get(NG_NAME)
    if old is not None:
        bpy.data.node_groups.remove(old)

    ng = bpy.data.node_groups.new(NG_NAME, 'GeometryNodeTree')
    ng.is_modifier = True
    L = ng.links.new

    ng.interface.new_socket(name="Geometry", in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')

    _iface_in(ng, "Pages", 'NodeSocketInt', 24, 2, 512)
    _iface_in(ng, "Width", 'NodeSocketFloat', 0.21, 0.01, 5.0)
    _iface_in(ng, "Height", 'NodeSocketFloat', 0.28, 0.01, 5.0)
    _iface_in(ng, "Page Gap", 'NodeSocketFloat', 0.0009, 0.00005, 0.05)
    _iface_in(ng, "Res X", 'NodeSocketInt', 28, 4, 128)
    _iface_in(ng, "Res Y", 'NodeSocketInt', 10, 2, 64)
    _iface_in(ng, "Flip Start", 'NodeSocketFloat', 12.0)
    _iface_in(ng, "Flip Duration", 'NodeSocketFloat', 26.0, 2.0, 500.0)
    _iface_in(ng, "Stagger", 'NodeSocketFloat', 9.0, 0.0, 500.0)
    _iface_in(ng, "Pages To Flip", 'NodeSocketInt', 12, 0, 512)
    _iface_in(ng, "Bend", 'NodeSocketFloat', 0.35, 0.0, 1.5)
    _iface_in(ng, "Droop", 'NodeSocketFloat', 0.18, 0.0, 1.0)
    _iface_in(ng, "Flutter", 'NodeSocketFloat', 0.05, 0.0, 0.5)
    _iface_in(ng, "Stiffness Falloff", 'NodeSocketFloat', 1.6, 0.5, 4.0)
    _iface_in(ng, "Cover Stiffness", 'NodeSocketFloat', 0.35, 0.0, 1.0)
    _iface_in(ng, "Cover Material", 'NodeSocketMaterial')
    _iface_in(ng, "Page Material", 'NodeSocketMaterial')

    gi = _mk(ng, 'NodeGroupInput', (-2000, 0))
    go = _mk(ng, 'NodeGroupOutput', (2600, 0))

    def G(name):
        return sock_out(gi, name)

    # ---------------- page stack -----------------------------------
    gap_vec = _combine_xyz(ng, (-1750, 420), z=G("Page Gap"), label="Gap Offset")
    line = _mk(ng, 'GeometryNodeMeshLine', (-1550, 420), "Spine Stack")
    L(G("Pages"), sock_in(line, "Count"))
    L(gap_vec, sock_in(line, "Offset"))

    grid = _mk(ng, 'GeometryNodeMeshGrid', (-1750, 120), "Page Sheet")
    L(G("Width"), sock_in(grid, "Size X"))
    L(G("Height"), sock_in(grid, "Size Y"))
    L(G("Res X"), sock_in(grid, "Vertices X"))
    L(G("Res Y"), sock_in(grid, "Vertices Y"))

    store_uv = _mk(ng, 'GeometryNodeStoreNamedAttribute', (-1550, 120), "Store UVMap")
    store_uv.data_type = 'FLOAT2'
    store_uv.domain = 'CORNER'
    sock_in(store_uv, "Name").default_value = "UVMap"
    L(sock_out(grid, "Mesh"), sock_in(store_uv, "Geometry"))
    L(sock_out(grid, "UV Map"), sock_in(store_uv, "Value", 'VECTOR'))

    half_w = _math(ng, 'DIVIDE', (-1750, -60), G("Width"), 2.0, "W/2")
    tr_vec = _combine_xyz(ng, (-1550, -60), x=half_w, label="Spine at X=0")
    xform = _mk(ng, 'GeometryNodeTransform', (-1350, 120), "Shift Sheet")
    L(sock_out(store_uv, "Geometry"), sock_in(xform, "Geometry"))
    L(tr_vec, sock_in(xform, "Translation"))

    inst = _mk(ng, 'GeometryNodeInstanceOnPoints', (-1150, 300))
    L(sock_out(line, "Mesh"), sock_in(inst, "Points"))
    L(sock_out(xform, "Geometry"), sock_in(inst, "Instance"))

    idx = _mk(ng, 'GeometryNodeInputIndex', (-1150, 100))
    store_i = _mk(ng, 'GeometryNodeStoreNamedAttribute', (-950, 300), "Store page_i")
    store_i.data_type = 'INT'
    store_i.domain = 'INSTANCE'
    sock_in(store_i, "Name").default_value = "page_i"
    L(sock_out(inst, "Instances"), sock_in(store_i, "Geometry"))
    L(sock_out(idx, "Index"), sock_in(store_i, "Value", 'INT'))

    realize = _mk(ng, 'GeometryNodeRealizeInstances', (-750, 300))
    L(sock_out(store_i, "Geometry"), sock_in(realize, "Geometry"))

    # ---------------- per-vertex fields ----------------------------
    pos = _mk(ng, 'GeometryNodeInputPosition', (-750, -100))
    sep = _mk(ng, 'ShaderNodeSeparateXYZ', (-550, -100))
    L(sock_out(pos, "Position"), sock_in(sep, "Vector"))
    d = sock_out(sep, "X")     # distance from spine
    y = sock_out(sep, "Y")

    attr_i = _mk(ng, 'GeometryNodeInputNamedAttribute', (-750, -300), "page_i")
    attr_i.data_type = 'INT'
    sock_in(attr_i, "Name").default_value = "page_i"
    i_out = sock_out(attr_i, "Attribute")

    pages_m1 = _math(ng, 'SUBTRACT', (-550, -300), G("Pages"), 1.0, "Pages-1")
    fo = _math(ng, 'SUBTRACT', (-350, -300), pages_m1, i_out, "Flip Order")

    # gate: only the top N pages flip
    gate_cmp = _mk(ng, 'FunctionNodeCompare', (-150, -460), "fo < To Flip")
    gate_cmp.data_type = 'FLOAT'
    gate_cmp.operation = 'LESS_THAN'
    L(fo, sock_in(gate_cmp, "A", 'VALUE'))
    L(G("Pages To Flip"), sock_in(gate_cmp, "B", 'VALUE'))

    # progress p in [0,1], staggered per page
    stime = _mk(ng, 'GeometryNodeInputSceneTime', (-550, -520))
    frame = sock_out(stime, "Frame")
    t0 = _math(ng, 'MULTIPLY', (-350, -520), fo, G("Stagger"), "fo*Stagger")
    f1 = _math(ng, 'SUBTRACT', (-150, -560), frame, G("Flip Start"))
    f2 = _math(ng, 'SUBTRACT', (50, -560), f1, t0)
    p_raw = _math(ng, 'DIVIDE', (250, -560), f2, G("Flip Duration"), "p raw")

    clamp = _mk(ng, 'ShaderNodeClamp', (450, -560), "Clamp p")
    L(p_raw, sock_in(clamp, "Value"))
    p_gated = _math(ng, 'MULTIPLY', (650, -560),
                    sock_out(clamp, "Result"),
                    sock_out(gate_cmp, "Result"), "p")
    p = p_gated

    # ease e = smoothstep(p), theta = e * pi
    p2 = _math(ng, 'MULTIPLY', (850, -460), p, p)
    tp = _math(ng, 'MULTIPLY', (850, -620), p, 2.0)
    t3 = _math(ng, 'SUBTRACT', (1050, -620), 3.0, tp)
    e = _math(ng, 'MULTIPLY', (1050, -460), p2, t3, "ease")
    theta = _math(ng, 'MULTIPLY', (1250, -460), e, pi, "theta")

    sin_t = _math(ng, 'SINE', (1450, -380), theta, label="sin(theta)")
    cos_t = _math(ng, 'COSINE', (1450, -540), theta, label="cos(theta)")

    # follow-through: -(Bend)*(1-2p)  -> lags on accel, leads on decel
    two_p = _math(ng, 'MULTIPLY', (850, -780), p, 2.0)
    accel = _math(ng, 'SUBTRACT', (1050, -780), 1.0, two_p, "accel shape")
    lag = _math(ng, 'MULTIPLY', (1250, -780), G("Bend"), accel)
    lag_n = _math(ng, 'MULTIPLY', (1450, -780), lag, -1.0, "Follow-through")

    # gravity droop: -(Droop)*cos(theta)
    droop = _math(ng, 'MULTIPLY', (1250, -920), G("Droop"), cos_t)
    droop_n = _math(ng, 'MULTIPLY', (1450, -920), droop, -1.0, "Droop")

    # flutter: centered 4D noise
    noise = _mk(ng, 'ShaderNodeTexNoise', (850, -1080), "Flutter Noise")
    noise.noise_dimensions = '4D'
    sock_in(noise, "Scale").default_value = 1.4
    nvy = _math(ng, 'MULTIPLY', (450, -1040), y, 3.0)
    nvz = _math(ng, 'MULTIPLY', (450, -1180), i_out, 4.7)
    nvec = _combine_xyz(ng, (650, -1080), x=nvy, y=d, z=nvz)
    L(nvec, sock_in(noise, "Vector"))
    wf = _math(ng, 'MULTIPLY', (450, -1320), frame, 0.07)
    wi = _math(ng, 'MULTIPLY', (450, -1460), i_out, 13.7)
    w = _math(ng, 'ADD', (650, -1380), wf, wi)
    L(w, sock_in(noise, "W"))
    noise_fac = sock_out_any(noise, ("Fac", "Value", "Factor"), 'VALUE')
    n_c1 = _math(ng, 'SUBTRACT', (1050, -1080), noise_fac, 0.5)
    n_c = _math(ng, 'MULTIPLY', (1250, -1080), n_c1, 2.0, "noise +-1")
    flut = _math(ng, 'MULTIPLY', (1450, -1080), G("Flutter"), n_c, "Flutter")

    # sum dynamic terms, all masked by sin(theta) so rest state is clean
    dyn1 = _math(ng, 'ADD', (1650, -860), lag_n, droop_n)
    dyn2 = _math(ng, 'ADD', (1650, -1000), dyn1, flut)
    dyn = _math(ng, 'MULTIPLY', (1850, -900), dyn2, sin_t, "dyn * sin(theta)")

    # stiffness profile from spine: (x/W)^falloff
    x_norm = _math(ng, 'DIVIDE', (1650, -200), d, G("Width"))
    profile = _math(ng, 'POWER', (1850, -200), x_norm, G("Stiffness Falloff"),
                    "Root Stiffness")

    # covers are stiffer
    eq0 = _mk(ng, 'FunctionNodeCompare', (1450, 60), "i == 0")
    eq0.data_type = 'INT'
    eq0.operation = 'EQUAL'
    L(i_out, sock_in(eq0, "A", 'INT'))
    eql = _mk(ng, 'FunctionNodeCompare', (1450, -100), "i == last")
    eql.data_type = 'INT'
    eql.operation = 'EQUAL'
    L(i_out, sock_in(eql, "A", 'INT'))
    L(pages_m1, sock_in(eql, "B", 'INT'))
    is_cover = _mk(ng, 'FunctionNodeBooleanMath', (1650, -20), "Is Cover")
    is_cover.operation = 'OR'
    L(sock_out(eq0, "Result"), is_cover.inputs[0])
    L(sock_out(eql, "Result"), is_cover.inputs[1])

    stiff_sw = _mk(ng, 'GeometryNodeSwitch', (1850, -20), "Cover Stiffness")
    stiff_sw.input_type = 'FLOAT'
    L(sock_out(is_cover, "Boolean"), sock_in(stiff_sw, "Switch"))
    sock_in(stiff_sw, "False").default_value = 1.0
    L(G("Cover Stiffness"), sock_in(stiff_sw, "True"))

    bend1 = _math(ng, 'MULTIPLY', (2050, -500), dyn, profile)
    bend2 = _math(ng, 'MULTIPLY', (2050, -660), bend1,
                  sock_out(stiff_sw, "Output"))
    alpha = _math(ng, 'ADD', (2050, -340), theta, bend2, "alpha")

    # rebuild position: rotate each vertex by its own angle around spine (Y)
    cos_a = _math(ng, 'COSINE', (2250, -260), alpha)
    sin_a = _math(ng, 'SINE', (2250, -420), alpha)
    x_new = _math(ng, 'MULTIPLY', (2450, -260), d, cos_a, "x'")
    z_rot = _math(ng, 'MULTIPLY', (2450, -420), d, sin_a, "z rot")

    z_rest = _math(ng, 'MULTIPLY', (2050, -820), i_out, G("Page Gap"), "z rest")
    z_land = _math(ng, 'MULTIPLY', (2050, -960), fo, G("Page Gap"), "z land")
    z_mix = _mk(ng, 'ShaderNodeMix', (2250, -880), "Land Stack")
    z_mix.data_type = 'FLOAT'
    L(e, sock_in(z_mix, "Factor", 'VALUE'))
    L(z_rest, sock_in(z_mix, "A", 'VALUE'))
    L(z_land, sock_in(z_mix, "B", 'VALUE'))
    z_new = _math(ng, 'ADD', (2450, -640), z_rot,
                  sock_out(z_mix, "Result", 'VALUE'), "z'")

    new_pos = _combine_xyz(ng, (2650, -420), x=x_new, y=y, z=z_new,
                           label="New Position")

    set_pos = _mk(ng, 'GeometryNodeSetPosition', (2050, 300), "Flip Pages")
    L(sock_out(realize, "Geometry"), sock_in(set_pos, "Geometry"))
    L(new_pos, sock_in(set_pos, "Position"))

    # ---------------- materials & output ---------------------------
    mat_pages = _mk(ng, 'GeometryNodeSetMaterial', (2250, 300), "Pages Mat")
    L(sock_out(set_pos, "Geometry"), sock_in(mat_pages, "Geometry"))
    L(G("Page Material"), sock_in(mat_pages, "Material"))

    mat_cover = _mk(ng, 'GeometryNodeSetMaterial', (2450, 300), "Cover Mat")
    L(sock_out(mat_pages, "Geometry"), sock_in(mat_cover, "Geometry"))
    L(sock_out(is_cover, "Boolean"), sock_in(mat_cover, "Selection"))
    L(G("Cover Material"), sock_in(mat_cover, "Material"))

    smooth = _mk(ng, 'GeometryNodeSetShadeSmooth', (2650, 300))
    L(sock_out(mat_cover, "Geometry"),
      sock_in_any(smooth, ("Geometry", "Mesh")))

    go.location = (2850, 300)
    L(sock_out_any(smooth, ("Geometry", "Mesh")), sock_in(go, "Geometry"))

    return ng


# ------------------------------------------------------------------
# Materials / modifier helpers
# ------------------------------------------------------------------

def _ensure_material(name, color, rough):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = rough
    return mat


def _mod_set(mod, name, value):
    ng = mod.node_group
    for item in ng.interface.items_tree:
        if (getattr(item, "item_type", None) == 'SOCKET'
                and item.in_out == 'INPUT' and item.name == name):
            mod[item.identifier] = value
            return


# ------------------------------------------------------------------
# Operator & panel
# ------------------------------------------------------------------

class MAGFORGE_OT_create(bpy.types.Operator):
    """Create a procedural magazine with page-flip animation"""
    bl_idname = "magforge.create"
    bl_label = "Create Magazine"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ng = build_group()

        mesh = bpy.data.meshes.new("Magazine")
        obj = bpy.data.objects.new("Magazine", mesh)
        context.collection.objects.link(obj)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        mod = obj.modifiers.new("Magazine Forge", 'NODES')
        mod.node_group = ng

        cover = _ensure_material("MF Cover", (0.02, 0.02, 0.05, 1.0), 0.35)
        pages = _ensure_material("MF Pages", (0.92, 0.90, 0.86, 1.0), 0.6)
        _mod_set(mod, "Cover Material", cover)
        _mod_set(mod, "Page Material", pages)

        self.report({'INFO'}, "Magazine created — press Play to flip")
        return {'FINISHED'}


class MAGFORGE_PT_main(bpy.types.Panel):
    bl_label = "Magazine Forge"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Magazine Forge"

    def draw(self, context):
        layout = self.layout
        layout.operator("magforge.create", icon='DOCUMENTS')

        obj = context.active_object
        mod = None
        if obj:
            for m in obj.modifiers:
                if m.type == 'NODES' and m.node_group \
                        and m.node_group.name.startswith(NG_NAME):
                    mod = m
                    break
        if mod is None:
            layout.label(text="Create or select a magazine", icon='INFO')
            return

        col = layout.column(align=True)
        for item in mod.node_group.interface.items_tree:
            if (getattr(item, "item_type", None) == 'SOCKET'
                    and item.in_out == 'INPUT'
                    and item.socket_type != 'NodeSocketGeometry'):
                col.prop(mod, f'["{item.identifier}"]', text=item.name)


# ------------------------------------------------------------------
# Registration — safe re-register with ghost-class eviction
# ------------------------------------------------------------------

_CLASSES = (MAGFORGE_OT_create, MAGFORGE_PT_main)


def _evict(cls):
    ghost = getattr(bpy.types, cls.__name__, None)
    if ghost is not None and ghost is not cls:
        try:
            bpy.utils.unregister_class(ghost)
        except Exception:
            pass


def register():
    for cls in _CLASSES:
        _evict(cls)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
