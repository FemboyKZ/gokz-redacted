"""Build the cover models and materials gokz-redacted.sp spawns.

    python -m scripts.covermodel <studiomdl.exe>   (from the repo root)

studiomdl only runs from a CS:GO bin folder, beside the engine dlls.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.bspcover import ASPECTS

SIZE = 32  # COVER_SIZE in gokz-redacted.sp

# $decal pulls a cover towards the camera so it does not flicker against its wall from afar,
# but then it writes no depth: anything drawn later shows through.
# Kinds are separate models, not skins: two skins on one spot drew one of them huge.
MATERIALS = {
    # Drawn before anything translucent, so glass cannot sort behind it.
    "cover": """
	"$decal"	"1"
""",
    # Overlays and translucent world brushes draw after "cover"; this draws later still.
    "late": """
	"$translucent"	"1"
	"$decal"	"1"
""",
    # Translucent brush entities can sort in front of "late". This writes depth, but flickers from afar.
    "solid": "\n",
}

VMT = """"UnlitGeneric"
{
	"$basetexture"	"tools/toolsblack"
	"$model"	"1"
	"$nocull"	"1"%s}
"""

GAMEINFO = """"GameInfo"
{
	game	"covermodel"
	FileSystem
	{
		SteamAppId	730
		SearchPaths
		{
			Game	|gameinfo_path|.
		}
	}
}
"""


def smd(aspect, material):
    y, z = SIZE * aspect / 2, SIZE / 2
    corner = {(-1, -1): (0, 0), (1, -1): (1, 0), (1, 1): (1, 1), (-1, 1): (0, 1)}
    lines = [
        "version 1",
        "nodes",
        '0 "root" -1',
        "end",
        "skeleton",
        "time 0",
        "0 0 0 0 0 0 0",
        "end",
        "triangles",
    ]
    for tri in (((-1, -1), (1, -1), (1, 1)), ((-1, -1), (1, 1), (-1, 1))):
        lines.append(material)
        # studiomdl turns an smd 90 degrees about Z: -Y here faces +X in game.
        lines += [
            f"0 {sy * y} 0 {sz * z} 0 -1 0 {corner[sy, sz][0]} {corner[sy, sz][1]}"
            for sy, sz in tri
        ]
    return "\n".join(lines + ["end", ""])


def main(studiomdl):
    Path("materials/gokz-redacted").mkdir(parents=True, exist_ok=True)
    for kind, flags in MATERIALS.items():
        Path(f"materials/gokz-redacted/{kind}.vmt").write_text(VMT % flags)
    out = Path("models/gokz-redacted")
    out.mkdir(parents=True, exist_ok=True)
    # studiomdl writes into its -game folder.
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        (game / "gameinfo.txt").write_text(GAMEINFO)
        shutil.copytree("materials", game / "materials")
        for kind in MATERIALS:
            for aspect in ASPECTS:
                name = f"{kind}{aspect}"
                (game / f"{name}.smd").write_text(smd(aspect, kind))
                (game / f"{name}.qc").write_text(
                    f'$modelname "gokz-redacted/{name}.mdl"\n$cdmaterials "gokz-redacted"\n'
                    f'$body body "{name}.smd"\n$sequence idle "{name}.smd"\n'
                )
                subprocess.run(
                    [studiomdl, "-nop4", "-game", str(game), str(game / f"{name}.qc")],
                    check=True,
                )
        for built in (game / "models" / "gokz-redacted").iterdir():
            # CS:GO only loads the dx90 mesh.
            if built.suffix in (".mdl", ".vvd") or built.name.endswith(".dx90.vtx"):
                shutil.copy(built, out / built.name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
