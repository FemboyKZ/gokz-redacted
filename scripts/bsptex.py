"""Dump the textures packed in .bsp files and where each is used.

    python -m scripts.bsptex maps/*.bsp   (from the repo root)
        ->   scripts/out/<map>/textures.tsv, scripts/out/<map>/img/*.png

Sort the thumbnails into img/xxx and img/fine, then move the map's folder into scripts/out/checked/.
A rerun leaves sorted ones in place.

Thumbnails are named "<usage>,<vtf path with ',' for '/'>.png", '%' ',' ';'
%XX-escaped, plus a ";frames" sheet for animated textures.
"""

import csv
import glob
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageStat
from srctools.bsp import BSP
from srctools.vtf import VTF, VTFFlags

from scripts.bsptsv import HEADER, norm, usage

THUMB = 512
FRAME = 128
# Baked cubemaps.
CUBEMAP = re.compile(
    r"^materials/maps/[^/]+/(c-?\d+_-?\d+_-?\d+|cubemapdefault)(\.hdr)?\.vtf$"
)


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


def analyse(bsp_path, out_root):
    bsp = BSP(bsp_path)
    pak = bsp.pakfile
    pak_names = {norm(n): n for n in pak.namelist()}
    rows, vtf_usage = usage(bsp)

    out = out_root / "checked" / Path(bsp_path).stem
    if not out.is_dir():
        out = out_root / Path(bsp_path).stem
    (out / "img").mkdir(parents=True, exist_ok=True)
    sorted_into = {png.name: png.parent for png in (out / "img").glob("*/*.png")}

    with open(out / "textures.tsv", "w", newline="", encoding="utf8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(HEADER)
        w.writerows(rows)

    dumped = failed = 0
    for name, real in sorted(pak_names.items()):
        if not name.endswith(".vtf") or CUBEMAP.match(name):
            continue
        kind = vtf_usage.get(name, "other")
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
        stem = png_stem(kind, name)
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
