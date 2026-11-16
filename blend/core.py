# -*- coding: utf-8 -*-
"""图层混合骨架。

normal 模式不做预乘，multiply 公式写反，图层不透明度没有逐层叠乘。
"""

import json
import struct
import zlib


class Image(object):
    def __init__(self, width, height, pixels=None):
        self.width = int(width)
        self.height = int(height)
        self.pixels = pixels or [(0, 0, 0, 0)] * (self.width * self.height)

    def at(self, x, y):
        return self.pixels[y * self.width + x]

    def set(self, x, y, rgba):
        self.pixels[y * self.width + x] = rgba


def load_png(path):
    with open(path, "rb") as f:
        data = f.read()
    pos = 8
    idat = b""
    width = height = bit = ctype = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit, ctype = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if bit != 8 or ctype != 6:
        raise ValueError("只支持 8 位 RGBA")
    raw = zlib.decompress(idat)
    stride = width * 4
    pixels = []
    for y in range(height):
        ft = raw[y * (stride + 1)]
        line = raw[y * (stride + 1) + 1: y * (stride + 1) + 1 + stride]
        if ft != 0:
            raise ValueError("只支持无过滤")
        for x in range(width):
            pixels.append(tuple(line[x * 4:x * 4 + 4]))
    return Image(width, height, pixels)


def save_png(img, path):
    raw = bytearray()
    for y in range(img.height):
        raw.append(0)
        for x in range(img.width):
            raw.extend(img.at(x, y))
    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body +
                struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


def blend_pixel(base, top, mode, opacity=1.0):
    """混合一个像素。base 与 top 都是 0..255 的 RGBA。"""
    a = top[3] / 255.0 * opacity
    if mode == "normal":
        return (int(top[0] * a + base[0] * (1 - a)),
                int(top[1] * a + base[1] * (1 - a)),
                int(top[2] * a + base[2] * (1 - a)),
                255)
    if mode == "multiply":
        r = base[0] * top[0] / 255.0
        g = base[1] * top[1] / 255.0
        b = base[2] * top[2] / 255.0
        return (int(r), int(g), int(b), 255)
    if mode == "screen":
        r = 255 - (255 - base[0]) * (255 - top[0]) / 255.0
        g = 255 - (255 - base[1]) * (255 - top[1]) / 255.0
        b = 255 - (255 - base[2]) * (255 - top[2]) / 255.0
        return (int(r), int(g), int(b), 255)
    raise ValueError("未知混合模式 %s" % mode)


def composite(base, layers):
    """依次叠图层。当前每层都用 1.0 的不透明度，忽略 layers 里的值。"""
    out = Image(base.width, base.height, list(base.pixels))
    for layer in layers:
        top = load_png(layer["path"])
        mode = layer["mode"]
        for y in range(out.height):
            for x in range(out.width):
                out.set(x, y, blend_pixel(out.at(x, y), top.at(x, y), mode))
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="blend")
    ap.add_argument("stack")
    ap.add_argument("--out", default="blend.png")
    args = ap.parse_args(argv)
    with open(args.stack, "r", encoding="utf-8") as f:
        spec = json.load(f)
    base = load_png(spec["base"])
    out = composite(base, spec["layers"])
    save_png(out, args.out)
    print("已输出 %s，图层 %d" % (args.out, len(spec["layers"])))
    return 0
