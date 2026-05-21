"""Interactive 3D viewer — rotate/zoom/pan with mouse.

Usage:
    python show3d.py                   # all variants
    python show3d.py --variant 1       # only variant 1
    python show3d.py --file my.json    # different output file
"""

import argparse
import json
import sys

import matplotlib
matplotlib.use("TkAgg")          # interactive backend — must be before pyplot import
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, ".")
from layout import LayoutVisualizer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="latest_run.json")
    parser.add_argument("--variant", type=int, default=None, help="1-based index")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    layouts = data.get("layouts", [])
    if not layouts:
        sys.exit("No layouts found in the file.")

    if args.variant is not None:
        idx = args.variant - 1
        if idx < 0 or idx >= len(layouts):
            sys.exit(f"Variant {args.variant} out of range (1–{len(layouts)}).")
        layouts = [layouts[idx]]

    viz = LayoutVisualizer()

    for variant in layouts:
        vid = variant.get("id", "?")
        score = variant.get("score", "")
        family = variant.get("family", "")
        title = f"{vid} ({family})  score={score}"

        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection="3d")
        viz._draw_3d_scene(ax, variant["environment"], variant["layout"])
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_zlabel("Z (m)")
        ax.set_title(title)
        ax.set_box_aspect([1, 1, 0.4])
        ax.view_init(elev=25, azim=45)
        try:
            ax.legend()
        except Exception:
            pass
        plt.tight_layout()

    plt.show()   # single blocking call — all variant windows open together


if __name__ == "__main__":
    main()
