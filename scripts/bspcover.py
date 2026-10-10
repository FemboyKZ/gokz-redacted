"""Write the cover configs for the textures sorted into xxx.

    python -m scripts.bspcover   (from the repo root)

scripts/out/<map>/img/xxx + maps/<map>.bsp
    ->   addons/sourcemod/configs/gokz-redacted/<map>.cfg

One block per cover, read by gokz-redacted.sp:

    origin  centre of the rectangle, on the surface
    angles  forward = surface normal
    width   along the entity's right axis; never less than height
    height  along the entity's up axis
    parent  hammerid of the owning brush entity; absent for world
    kind    cover model, if not "cover"; see MATERIALS in covermodel.py
"""

import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

from srctools import Vec
from srctools.bsp import BSP
from srctools.vmt import Material

from scripts.bsptex import PakFS, norm

SORTED = Path("scripts/out")
OUT = Path("addons/sourcemod/configs/gokz-redacted")
# Narrower surfaces are brush edges.
MIN_SIDE = 4
# Share of its bounding rectangle a surface must fill to count as one.
FILL = 0.98
# Covers further apart are never joined.
MAX_GAP = 64
# A joined cover floats over the gap between two panels; the wall may be this far behind.
DEPTH = 32
# Width:height of the cover models; also in gokz-redacted.sp.
# Doubling means two overlapping copies fill any rectangle.
ASPECTS = (1, 2, 4, 8, 16, 32, 64)


def xxx_materials(map_dir):
    vtfs = {
        "materials/"
        + "/".join(unquote(p) for p in png.stem.removesuffix(";frames").split(",")[1:])
        + ".vtf"
        for png in (map_dir / "img" / "xxx").glob("*.png")
    }
    with open(map_dir / "textures.tsv", encoding="utf8") as f:
        return {
            r["material"]
            for r in csv.DictReader(f, delimiter="\t")
            if vtfs & set(r["vtfs"].split(" | "))
        }


def translucent(bsp, mats):
    """Those of `mats` the engine draws in its translucent pass."""
    names = {norm(n): n for n in bsp.pakfile.namelist()}
    fsys = PakFS("pak", bsp.pakfile)
    found = set()
    for mat in mats:
        with fsys.open_str(names[f"materials/{mat}.vmt"]) as f:
            vmt = Material.parse(f, mat)
        try:
            vmt = vmt.apply_patches(fsys)
        except ValueError:
            pass  # patches a stock material
        flags = {
            key.lower(): value for key, value in vmt.items() if isinstance(value, str)
        }
        if any(
            flags.get(flag, "0") not in ("0", "")
            for flag in ("$translucent", "$additive")
        ):
            found.add(mat)
    return found


def area(poly):
    total = Vec()
    for i in range(1, len(poly) - 1):
        total += Vec.cross(poly[i] - poly[0], poly[i + 1] - poly[0])
    return total.mag() / 2


def rect(polys, normal):
    """Smallest bounding rectangle: origin, (forward, left, up), width, height, share filled."""
    pts = [p for poly in polys for p in poly]
    best = None
    for poly in polys:
        for a, b in zip(poly, poly[1:] + poly[:1]):
            if (b - a).mag() < 0.01:
                continue
            # The smallest one always has a side along an edge.
            u = (b - a).norm()
            v = Vec.cross(normal, u)
            us = [Vec.dot(p, u) for p in pts]
            vs = [Vec.dot(p, v) for p in pts]
            size = (max(us) - min(us)) * (max(vs) - min(vs))
            if best is None or size < best[0] - 0.01:
                best = size, u, v, us, vs
    size, u, v, us, vs = best
    # Cover models are wider than tall.
    if max(us) - min(us) < max(vs) - min(vs):
        u, v, us, vs = v, u, vs, us
    width, height = max(us) - min(us), max(vs) - min(vs)
    origin = (
        u * ((max(us) + min(us)) / 2)
        + v * ((max(vs) + min(vs)) / 2)
        + normal * Vec.dot(pts[0], normal)
    )
    up = v if v.z >= 0 else -v
    left = Vec.cross(up, normal)
    return origin, (normal, left, up), width, height, sum(map(area, polys)) / size


def angles(forward, left, up):
    flat = math.hypot(forward.x, forward.y)
    if flat > 0.001:
        return (
            math.degrees(math.atan2(-forward.z, flat)),
            math.degrees(math.atan2(forward.y, forward.x)),
            math.degrees(math.atan2(left.z, up.z)),
        )
    return (
        math.degrees(math.atan2(-forward.z, flat)),
        math.degrees(math.atan2(-left.x, left.y)),
        0.0,
    )


def plane_key(parent, normal, dist):
    return (
        parent,
        round(normal.x, 2),
        round(normal.y, 2),
        round(normal.z, 2),
        round(dist),
    )


def covers(bsp, mats):
    """Surfaces showing `mats` as (material, parent, polygons, normal), and every drawn face by plane."""
    owner = {}
    groups = defaultdict(list)
    walls = defaultdict(list)
    for ent, model in bsp.bmodels.items():
        world = ent is bsp.ents.spawn
        # Brush entity vertices are relative to its origin.
        offset = Vec() if world else Vec.from_str(ent["origin"])
        for face in model.faces:
            parent = owner[id(face)] = "" if world else ent["hammerid"]
            if face.texinfo is None:
                continue
            mat = norm(face.texinfo.mat)
            poly = [e.a + offset for e in face.edges]
            # Winding gives the visible side; the lump's plane-side flag does not.
            normal = Vec()
            for a, b in zip(poly, poly[1:] + poly[:1]):
                normal -= Vec.cross(a, b)
            normal = normal.norm()
            if not mat.startswith("tools/"):
                dist = Vec.dot(poly[0], normal)
                walls[plane_key(parent, normal, dist)].append((dist, poly))
            if mat in mats:
                # vbsp splits a brush side into faces; orig_face groups them.
                groups[parent, mat, id(face.orig_face or face)].append((poly, normal))
    found = [
        (mat, parent, [poly for poly, _ in faces], faces[0][1])
        for (parent, mat, _), faces in groups.items()
    ]

    for over in bsp.overlays:
        mat = norm(over.texture.mat)
        if mat not in mats:
            continue
        basis_v = Vec.cross(over.normal, over.basis_u) * (
            -1 if over.basis_v_flipped else 1
        )
        poly = [
            over.origin + over.basis_u * uv.x + basis_v * uv.y
            for uv in (over.uv1, over.uv2, over.uv3, over.uv4)
        ]
        parents = {owner[id(bsp.faces[i])] for i in over.faces}
        found.append(
            (mat, parents.pop() if len(parents) == 1 else "", [poly], over.normal)
        )
    return found, walls


def corners(origin, left, up, width, height):
    return [
        origin + left * (sl * width / 2) + up * (su * height / 2)
        for sl, su in ((1, 1), (-1, 1), (-1, -1), (1, -1))
    ]


def clip(pts, axis, bound, above):
    """Cut a 2D polygon down to the side of `bound` it is kept on."""
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        a_in, b_in = (a[axis] >= bound) == above, (b[axis] >= bound) == above
        if a_in:
            out.append(a)
        if a_in != b_in:
            t = (bound - a[axis]) / (b[axis] - a[axis])
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def wall_share(quad, normal, parent, walls):
    """Share of a rectangle with wall at most DEPTH behind it."""
    left, up = (quad[0] - quad[1]).norm(), (quad[1] - quad[2]).norm()
    l0, l1 = Vec.dot(quad[2], left), Vec.dot(quad[0], left)
    u0, u1 = Vec.dot(quad[2], up), Vec.dot(quad[0], up)
    dist = Vec.dot(quad[0], normal)
    # Planes overlap (wall behind a panel), so each is summed on its own.
    layers = defaultdict(float)
    for back in range(-DEPTH - 1, 2):
        for face_dist, poly in walls.get(plane_key(parent, normal, dist + back), ()):
            if not dist - DEPTH <= face_dist <= dist + 0.25:
                continue
            pts = [(Vec.dot(p, left), Vec.dot(p, up)) for p in poly]
            if (
                max(x for x, _ in pts) <= l0
                or min(x for x, _ in pts) >= l1
                or max(y for _, y in pts) <= u0
                or min(y for _, y in pts) >= u1
            ):
                continue
            for axis, bound, above in (
                (0, l0, True),
                (0, l1, False),
                (1, u0, True),
                (1, u1, False),
            ):
                pts = clip(pts, axis, bound, above)
            layers[round(face_dist)] += (
                abs(
                    sum(
                        a[0] * b[1] - b[0] * a[1]
                        for a, b in zip(pts, pts[1:] + pts[:1])
                    )
                )
                / 2
            )
    return max(layers.values(), default=0) / ((l1 - l0) * (u1 - u0))


def joined(a, b, normal, parent, walls):
    """The rectangle holding quads a and b, if they are close and all of it is wall."""
    # Covers sit a fraction of a unit off the surface, so both must be level.
    if abs(Vec.dot(a[0] - b[0], normal)) > 0.05 or any(
        min(p[k] for p in a) > max(p[k] for p in b) + MAX_GAP
        or min(p[k] for p in b) > max(p[k] for p in a) + MAX_GAP
        for k in range(3)
    ):
        return None
    origin, (_, left, up), width, height, _ = rect([a, b], normal)
    quad = corners(origin, left, up, width, height)
    return quad if wall_share(quad, normal, parent, walls) >= FILL else None


def merge(found, walls):
    """Join neighbouring covers to spend fewer entities, only where wall lies between them."""
    planes = defaultdict(list)
    for mat, parent, polys, normal in found:
        origin, (_, left, up), width, height, fill = rect(polys, normal)
        if fill < FILL:
            yield {mat}, parent, polys, normal
        else:
            key = plane_key(parent, normal, Vec.dot(origin, normal))
            planes[key].append(
                ({mat}, corners(origin, left, up, width, height), normal)
            )
    for (parent, *_), group in planes.items():
        changed = True
        while changed:
            changed = False
            i = 0
            while i < len(group):
                j = i + 1
                while j < len(group):
                    both = joined(group[i][1], group[j][1], group[i][2], parent, walls)
                    if both:
                        group[i] = group[i][0] | group[j][0], both, group[i][2]
                        del group[j]
                        changed = True
                    else:
                        j += 1
                i += 1
        for mats, quad, normal in group:
            yield mats, parent, [quad], normal


def fmt(values):
    # "+ 0.0" turns -0.0 into 0.0.
    return " ".join(f"{round(v, 2) + 0.0:.2f}".rstrip("0").rstrip(".") for v in values)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for map_dir in sorted(SORTED.iterdir()):
        mats = xxx_materials(map_dir)
        if not mats:
            continue
        bsp = BSP(f"maps/{map_dir.name}.bsp")
        notes = Counter()
        found = []
        surfaces, walls = covers(bsp, mats)
        see_through = translucent(bsp, mats)
        overlay_mats = {norm(over.texture.mat) for over in bsp.overlays}
        for cover in surfaces:
            notes["surfaces"] += 1
            _, _, width, height, _ = rect(cover[2], cover[3])
            if min(width, height) < MIN_SIDE:
                notes["slivers dropped"] += 1
            else:
                found.append(cover)

        blocks = []
        seen = set()
        for names, parent, polys, normal in merge(found, walls):
            origin, axes, width, height, fill = rect(polys, normal)
            seen |= names
            notes["parented" if parent else "world"] += 1
            if fill < FILL:
                notes["not rectangular (cover is larger than surface)"] += 1
            # Same model choice as the plugin.
            notes["entities"] += math.ceil(
                width / height / max(a for a in ASPECTS if a <= width / height + 0.001)
                - 0.001
            )
            kind = ""
            if see_through & names:
                kind = "solid" if parent else "late"
            elif overlay_mats & names:
                kind = "late"
            notes[kind or "cover"] += 1
            blocks.append(
                (sorted(names), origin, angles(*axes), width, height, parent, kind)
            )

        with open(OUT / f"{map_dir.name}.cfg", "w", encoding="utf8") as f:
            f.write('"covers"\n{\n')
            for i, (names, origin, ang, width, height, parent, kind) in enumerate(
                blocks
            ):
                f.write(f'\t// {", ".join(names)}\n\t"{i}"\n\t{{\n')
                values = {
                    "origin": fmt(origin),
                    "angles": fmt(ang),
                    "width": fmt([width]),
                    "height": fmt([height]),
                }
                if parent:
                    values["parent"] = parent
                if kind:
                    values["kind"] = kind
                for key, value in values.items():
                    # Spaces, not a tab, so the values line up.
                    quoted = f'"{key}"'
                    f.write(f'\t\t{quoted:<9}"{value}"\n')
                f.write("\t}\n")
            f.write("}\n")

        missing = mats - seen
        print(
            f"{map_dir.name}: {len(blocks)} covers for {len(mats)} materials  "
            + "  ".join(f"{k}={v}" for k, v in sorted(notes.items()))
            + f"  map_entities={len(bsp.ents.entities)}"
            + (f"  !! no surface found for {sorted(missing)}" if missing else "")
        )


if __name__ == "__main__":
    sys.exit(main())
