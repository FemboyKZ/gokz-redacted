"""Dump the textures packed in .bsp files and where each is used.

    python -m scripts.bsptex maps/*.bsp   (from the repo root)
        ->   scripts/out/<map>/textures.tsv, scripts/out/<map>/img/*.png

Sort the thumbnails into img/xxx and img/fine for bspcover.py; a rerun leaves sorted ones in place.

Thumbnails are named "<usage>,<vtf path with ',' for '/'>.png", '%' ',' ';'
%XX-escaped, plus a ";frames" sheet for animated textures.
"""

import csv
import glob
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageStat
from srctools.bsp import BSP
from srctools.filesys import ZipFileSystem
from srctools.vmt import Material
from srctools.vtf import VTF, VTFFlags

THUMB = 512
FRAME = 128
TEX_PARAMS = ("$basetexture", "$basetexture2")
# Baked cubemaps.
CUBEMAP = re.compile(
    r"^materials/maps/[^/]+/(c-?\d+_-?\d+_-?\d+|cubemapdefault)(\.hdr)?\.vtf$"
)


class PakFS(ZipFileSystem):
    # Packed VMTs can hold cp1252 bytes; latin-1 always decodes.
    def open_str(self, name, encoding="utf8"):
        return super().open_str(name, "latin-1")


def thumb(img, size):
    # Resizing RGBA premultiplies alpha, usually a specular mask, which blacks out the picture.
    rgb, alpha = img.convert("RGB"), img.getchannel("A")
    rgb.thumbnail((size, size))
    alpha.thumbnail((size, size))
    if max(ImageStat.Stat(rgb).stddev) < 6 and ImageStat.Stat(alpha).stddev[0] > 30:
        # Flat colour with the picture in alpha (text, decals).
        return alpha.convert("RGB")
    return rgb


def png_stem(usage, vtf):
    path = vtf[len("materials/") : -4]
    for c in "%,;":
        path = path.replace(c, f"%{ord(c):02X}")
    return f"{usage},{path.replace('/', ',')}"


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


def analyse(bsp_path, out_root):
    bsp = BSP(bsp_path)
    pak = bsp.pakfile
    pak_names = {norm(n): n for n in pak.namelist()}
    fsys = PakFS("pak", pak)

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

    out = out_root / Path(bsp_path).stem
    (out / "img").mkdir(parents=True, exist_ok=True)
    sorted_into = {png.name: png.parent for png in (out / "img").glob("*/*.png")}

    vtf_usage = {}
    rows = []
    for mat in sorted(set(world) | set(ent_faces) | set(overlays) | set(decals)):
        vtfs = basetextures(mat, pak_names, fsys)
        if vtfs is None:
            continue
        usage = (
            "brush"
            if mat in world or mat in ent_faces
            else "overlay" if mat in overlays else "decal"
        )
        for v in vtfs:
            vtf_usage.setdefault(v, usage)
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

    with open(out / "textures.tsv", "w", newline="", encoding="utf8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(
            [
                "material",
                "world_faces",
                "entities(hammerid:class:name:faces)",
                "overlays",
                "decals",
                "vtfs",
            ]
        )
        w.writerows(rows)

    dumped = failed = 0
    for name, real in sorted(pak_names.items()):
        if not name.endswith(".vtf") or CUBEMAP.match(name):
            continue
        usage = vtf_usage.get(name, "other")
        try:
            with pak.open(real) as f:
                vtf = VTF.read(f)
                # NORMAL is not skipped: mappers set it on ordinary images too.
                if vtf.flags & VTFFlags.ENVMAP:
                    continue
                vtf.load()
                frames = [vtf.get(frame=i).to_PIL() for i in range(vtf.frame_count)]
        except Exception as exc:
            print(f"  ! {name}: {exc}")
            failed += 1
            continue
        stem = png_stem(usage, name)
        stem = sorted_into.get(f"{stem}.png", out / "img") / stem
        thumb(frames[0], THUMB).save(f"{stem}.png")
        if len(frames) > 1:
            # Every frame can be a different picture.
            cols = math.ceil(math.sqrt(len(frames)))
            sheet = Image.new(
                "RGB", (cols * FRAME, math.ceil(len(frames) / cols) * FRAME)
            )
            for i, frame in enumerate(frames):
                sheet.paste(thumb(frame, FRAME), (i % cols * FRAME, i // cols * FRAME))
            sheet.save(f"{stem};frames.png")
        dumped += 1

    print(
        f"{Path(bsp_path).stem}: {len(rows)} packed materials on brushes/overlays/decals, "
        f"{dumped} images dumped, {failed} failed"
    )


if __name__ == "__main__":
    paths = [p for arg in sys.argv[1:] for p in sorted(glob.glob(arg))]
    if not paths:
        sys.exit(__doc__)
    for p in paths:
        analyse(p, Path("scripts/out"))
