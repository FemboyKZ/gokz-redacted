"""Rewrite the "## Maps" section of README.md from the sorted thumbnails.

    python -m scripts.readme   (from the repo root)

Lists the maps that have a cover config; needs their .bsp in maps/.
"""

import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from PIL import Image
from srctools.bsp import BSP

from scripts.bspcover import OUT as CONFIGS
from scripts.bspcover import SORTED
from scripts.bsptsv import norm

README = Path("README.md")
# Thumbnails are one picture if their 256-bit hashes differ by at most this.
# Re-saved copies differ by under 10 bits, unrelated pictures by over 40.
SAME = 10
MB = 1 << 20
# Figure space: as wide as a digit, and not collapsed when the table is rendered.
PAD = "\u2007"

LEGEND = "Repeats: pictures another listed map has too.\nWasted: explicit textures / whole map."


def look(png):
    """Gradient hash: one bit per pixel brighter than its right-hand neighbour."""
    px = list(Image.open(png).convert("L").resize((17, 16)).getdata())
    return sum(1 << i for i in range(256) if px[i + i // 16] > px[i + i // 16 + 1])


def column(values, spec):
    """Format numbers to one width, so they line up in source and rendered."""
    texts = [format(v, spec) for v in values]
    return [t.rjust(max(map(len, texts)), PAD) for t in texts]


def main():
    pics = []  # (map, hash, bytes in the bsp)
    bsp_size = {}
    for cfg in sorted(CONFIGS.glob("*.cfg")):
        name = cfg.stem
        folder = SORTED / "checked" / name
        if not folder.is_dir():
            folder = SORTED / name
        bsp = Path(f"maps/{name}.bsp")
        if not folder.is_dir() or not bsp.exists():
            print(f"{name}: no sorted folder or no bsp, left out")
            continue
        bsp_size[name] = bsp.stat().st_size
        packed = {
            norm(i.filename): i.compress_size for i in BSP(bsp).pakfile.infolist()
        }
        for png in sorted((folder / "img" / "xxx").glob("*.png")):
            if png.stem.endswith(";frames"):
                continue
            vtf = "/".join(unquote(part) for part in png.stem.split(",")[1:])
            pics.append((name, look(png), packed[f"materials/{vtf}.vtf"]))

    # Union-find over pictures that look the same.
    group = list(range(len(pics)))

    def find(i):
        while group[i] != i:
            i = group[i]
        return i

    for i, (_, a, _) in enumerate(pics):
        for j in range(i):
            if (a ^ pics[j][1]).bit_count() <= SAME:
                group[find(i)] = find(j)
    groups = [find(i) for i in range(len(pics))]
    maps_with = Counter(g for g, _ in {(g, pic[0]) for g, pic in zip(groups, pics)})

    counts, repeats, wasted = [], [], []
    for name in bsp_size:
        mine = [g for g, pic in zip(groups, pics) if pic[0] == name]
        counts.append(len(mine))
        repeats.append(sum(1 for g in set(mine) if maps_with[g] > 1))
        wasted.append(sum(pic[2] for pic in pics if pic[0] == name))
    sizes = list(bsp_size.values())
    rows = list(
        zip(
            bsp_size,
            column(counts, "d"),
            column(repeats, "d"),
            (
                f"{w} / {s} MB ({p}%)"
                for w, s, p in zip(
                    column([w / MB for w in wasted], ".1f"),
                    column([s / MB for s in sizes], ".1f"),
                    column([100 * w / s for w, s in zip(wasted, sizes)], ".1f"),
                )
            ),
        )
    )

    head = ("Map Name", "Count", "Repeats", "Wasted")
    widths = [max(len(row[i]) for row in [head, *rows]) for i in range(len(head))]
    table = [head, tuple("-" * w for w in widths), *rows]
    body = [
        "## Maps",
        "",
        f"Total: {len(pics)} textures, {len(set(groups))} unique images, "
        f"{sum(wasted) / MB:.0f} / {sum(sizes) / MB:.0f} MB wasted "
        f"({100 * sum(wasted) / sum(sizes):.1f}%)",
        "",
        LEGEND,
        "",
        *(
            "| " + " | ".join(c.ljust(w) for c, w in zip(row, widths)) + " |"
            for row in table
        ),
        "",
    ]

    raw = README.read_bytes().decode("utf8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    start = text.index("## Maps\n")
    end = text.find("\n## ", start)
    rest = "" if end == -1 else text[end:]
    README.write_bytes(
        (text[:start] + "\n".join(body) + rest).replace("\n", eol).encode("utf8")
    )
    print(body[2])


if __name__ == "__main__":
    sys.exit(main())
