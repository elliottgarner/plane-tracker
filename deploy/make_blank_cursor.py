#!/usr/bin/env python3
"""Create an invisible X cursor theme.   make_blank_cursor.py <theme_dir>

The kiosk's page hides the pointer with CSS, but the Wayland compositor (labwc) still draws its own
arrow wherever no application sets a cursor. Pointing XCURSOR_THEME at this theme hides that too.
"""
import struct
import sys
from pathlib import Path

NAMES = [
    "left_ptr", "default", "arrow", "top_left_arrow", "pointer", "hand1", "hand2", "text", "xterm",
    "ibeam", "watch", "wait", "progress", "crosshair", "cross", "grab", "grabbing", "move", "fleur",
    "help", "question_arrow", "not-allowed", "crossed_circle", "all-scroll", "col-resize", "row-resize",
    "n-resize", "s-resize", "e-resize", "w-resize", "ne-resize", "nw-resize", "se-resize", "sw-resize",
    "sb_h_double_arrow", "sb_v_double_arrow", "left_side", "right_side", "top_side", "bottom_side",
    "top_left_corner", "top_right_corner", "bottom_left_corner", "bottom_right_corner", "context-menu",
    "copy", "alias", "zoom-in", "zoom-out", "vertical-text", "dnd-none", "dnd-move", "dnd-copy", "dnd-link",
]


def blank_cursor() -> bytes:
    """Xcursor file holding a single 1x1 fully transparent image."""
    img_type, nominal = 0xFFFD0002, 24
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, 1)
    toc = struct.pack("<III", img_type, nominal, 28)           # chunk starts right after header + toc
    chunk = struct.pack("<IIIIIIIII", 36, img_type, nominal, 1, 1, 1, 0, 0, 0) + struct.pack("<I", 0)
    return header + toc + chunk


def main(theme: Path):
    cursors = theme / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)
    (theme / "index.theme").write_text("[Icon Theme]\nName=blank\nComment=Invisible cursor\n")
    data = blank_cursor()
    for name in NAMES:
        (cursors / name).write_bytes(data)
    print(f"Invisible cursor theme written to {theme} ({len(NAMES)} cursors)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
