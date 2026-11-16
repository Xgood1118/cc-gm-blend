# -*- coding: utf-8 -*-
"""生成底图与三个图层：半透明色块、正片叠底纹理、滤色高光。"""
import json
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 200, 140


def write_png(path, pixel_fn):
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        for x in range(W):
            raw.extend(pixel_fn(x, y))
    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body +
                struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    write_png(os.path.join(HERE, "data", "base.png"),
              lambda x, y: (int(40 + x * 0.6), int(60 + y * 0.8), 120, 255))
    write_png(os.path.join(HERE, "data", "layer_dark.png"),
              lambda x, y: (180, 90, 60, 128) if x < W // 2 else (0, 0, 0, 0))
    write_png(os.path.join(HERE, "data", "layer_grid.png"),
              lambda x, y: (200, 200, 200, 255) if (x // 16 + y // 16) % 2 else (80, 80, 80, 255))
    write_png(os.path.join(HERE, "data", "layer_glow.png"),
              lambda x, y: (255, 220, 120, 90) if ((x - 150) ** 2 + (y - 40) ** 2) < 900 else (0, 0, 0, 0))
    spec = {
        "base": os.path.join(HERE, "data", "base.png"),
        "layers": [
            {"path": os.path.join(HERE, "data", "layer_dark.png"), "mode": "normal", "opacity": 0.5},
            {"path": os.path.join(HERE, "data", "layer_grid.png"), "mode": "multiply", "opacity": 0.35},
            {"path": os.path.join(HERE, "data", "layer_glow.png"), "mode": "screen", "opacity": 0.8},
        ],
    }
    with open(os.path.join(HERE, "data", "stack.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print("已生成底图与三层")


if __name__ == "__main__":
    main()
