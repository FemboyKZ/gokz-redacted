"""Print where each packed material of .bsp files is used, as tsv. Exports nothing.

    python bsptsv.py maps/*.bsp > textures.tsv

Stands alone: needs only srctools. Maps that fail to parse are named on stderr.
"""

import csv
import glob
import sys
from collections import defaultdict
from pathlib import Path

from srctools.bsp import BSP
from srctools.filesys import ZipFileSystem
from srctools.vmt import Material

TEX_PARAMS = ("$basetexture", "$basetexture2")
HEADER = [
    "material",
    "world_faces",
    "entities(hammerid:class:name:faces)",
    "overlays",
    "decals",
    "vtfs",
]


class PakFS(ZipFileSystem):
    # Packed VMTs can hold cp1252 bytes; latin-1 always decodes.
    def open_str(self, name, encoding="utf8"):
        return super().open_str(name, "latin-1")


def norm(name):
    return name.replace("\\", "/").lower().strip("/")


def basetextures(mat_name, pak_names, fsys):
    """VTF pak paths a packed material draws, or None if the material is stock."""
    path = pak_names.get(f"materials/{mat_name}.vmt")
    if path is None:
        return None
    with fsys.open_str(path) as f:
        mat = Material.parse(f, path)
    try:
        mat = mat.apply_patches(fsys)
    except ValueError:
        # Patches a stock material: no packed image.
        return []
    return [f"materials/{norm(mat[p])}.vtf" for p in TEX_PARAMS if p in mat]


def usage(bsp):
    """One HEADER row per packed material in use, and {vtf: brush/overlay/decal}."""
    pak_names = {norm(n): n for n in bsp.pakfile.namelist()}
    fsys = PakFS("pak", bsp.pakfile)

    decals = defaultdict(int)
    for ent in bsp.ents.by_class["infodecal"]:
        decals[norm(ent["texture"])] += 1

    world = defaultdict(int)
    ent_faces = defaultdict(lambda: defaultdict(int))
    for ent, model in bsp.bmodels.items():
        for face in model.faces:
            if face.texinfo is None:
                continue
            mat = norm(face.texinfo.mat)
            if ent is bsp.ents.spawn:
                world[mat] += 1
            else:
                ent_faces[mat][ent] += 1

    overlays = defaultdict(int)
    for over in bsp.overlays:
        overlays[norm(over.texture.mat)] += 1

    vtf_usage = {}
    rows = []
    for mat in sorted(set(world) | set(ent_faces) | set(overlays) | set(decals)):
        vtfs = basetextures(mat, pak_names, fsys)
        if vtfs is None:
            continue
        kind = (
            "brush"
            if mat in world or mat in ent_faces
            else "overlay" if mat in overlays else "decal"
        )
        for v in vtfs:
            vtf_usage.setdefault(v, kind)
        ents = [
            f"{ent['hammerid']}:{ent['classname']}:{ent['targetname']}:{count}"
            for ent, count in ent_faces[mat].items()
        ]
        rows.append(
            [
                mat,
                world[mat],
                " | ".join(ents),
                overlays[mat],
                decals[mat],
                " | ".join(vtfs),
            ]
        )
    return rows, vtf_usage


if __name__ == "__main__":
    paths = [p for arg in sys.argv[1:] for p in sorted(glob.glob(arg))]
    if not paths:
        sys.exit(__doc__)
    out = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    out.writerow(["map"] + HEADER)
    for p in paths:
        try:
            rows, _ = usage(BSP(p))
        except Exception as exc:
            # One unreadable map must not end a run over a whole maps folder.
            print(f"{p}: {exc}", file=sys.stderr)
            continue
        out.writerows([Path(p).stem] + row for row in rows)
        sys.stdout.flush()
