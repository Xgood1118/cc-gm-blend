# -*- coding: utf-8 -*-
"""图层混合核心。

合成使用非预乘（straight）alpha 的 RGBA，按业界通用公式（W3C Compositing
and Blending / Photoshop 等）处理：

    a_out = a_s + a_b * (1 - a_s)
    C_out = (a_s*(1-a_b)*C_s + a_s*a_b*B(C_b, C_s) + a_b*(1-a_s)*C_b) / a_out

其中 a_s 是图层像素 alpha 乘以图层不透明度，B 是混合模式函数：

    normal   B(C_b, C_s) = C_s
    multiply B(C_b, C_s) = C_b * C_s
    screen   B(C_b, C_s) = C_b + C_s - C_b * C_s

颜色在 0..1 的浮点空间计算，最后四舍五入回 8 位，避免截断造成的色阶损失。
"""

import json
import math
import os
import struct
import zlib


class Image(object):
    def __init__(self, width, height, pixels=None):
        self.width = int(width)
        self.height = int(height)
        if pixels is None:
            pixels = [(0, 0, 0, 0)] * (self.width * self.height)
        self.pixels = list(pixels)

    def at(self, x, y):
        return self.pixels[y * self.width + x]

    def set(self, x, y, rgba):
        self.pixels[y * self.width + x] = tuple(rgba)


# ---------------------------------------------------------------------------
# PNG 读写（仅标准库）
# ---------------------------------------------------------------------------

def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, width, height, channels):
    """还原 PNG 扫描线过滤（0..4），返回展平的通道字节。"""
    stride = width * channels
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        if pos >= len(raw):
            raise ValueError("PNG 数据不完整")
        ftype = raw[pos]
        pos += 1
        line = raw[pos:pos + stride]
        if len(line) != stride:
            raise ValueError("PNG 数据不完整")
        pos += stride
        cur = bytearray(stride)
        for i in range(stride):
            x = line[i]
            a = cur[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if ftype == 0:
                v = x
            elif ftype == 1:
                v = x + a
            elif ftype == 2:
                v = x + b
            elif ftype == 3:
                v = x + ((a + b) >> 1)
            elif ftype == 4:
                v = x + _paeth(a, b, c)
            else:
                raise ValueError("不支持的 PNG 过滤类型 %d" % ftype)
            cur[i] = v & 0xFF
        out[y * stride:(y + 1) * stride] = cur
        prev = cur
    return out


def load_png(path):
    """读取 8 位 PNG，统一返回 RGBA Image。"""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("不是合法的 PNG 文件")
    pos = 8
    idat = []
    width = height = bit = ctype = interlace = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit, ctype, _, _, interlace = struct.unpack(
                ">IIBBBBB", body[:13])
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG 缺少 IHDR")
    if bit != 8:
        raise ValueError("只支持 8 位 PNG")
    if interlace != 0:
        raise ValueError("不支持隔行扫描 PNG")
    channels = {0: 1, 2: 3, 6: 4}.get(ctype)
    if channels is None:
        raise ValueError("只支持灰度、RGB 或 RGBA PNG")
    raw = zlib.decompress(b"".join(idat))
    flat = _unfilter(raw, width, height, channels)
    pixels = []
    stride = width * channels
    for y in range(height):
        base = y * stride
        for x in range(width):
            off = base + x * channels
            if channels == 4:
                pixels.append(tuple(flat[off:off + 4]))
            elif channels == 3:
                pixels.append((flat[off], flat[off + 1], flat[off + 2], 255))
            else:
                g = flat[off]
                pixels.append((g, g, g, 255))
    return Image(width, height, pixels)


def _png_chunk(tag, body):
    return (struct.pack(">I", len(body)) + tag + body +
            struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))


def save_png(img, path):
    """保存为 8 位 RGBA PNG（固定过滤 0、固定压缩级别，输出可复现）。"""
    raw = bytearray()
    for y in range(img.height):
        raw.append(0)
        for x in range(img.width):
            r, g, b, a = img.at(x, y)
            raw.extend((r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF))
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) +
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
            _png_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


# ---------------------------------------------------------------------------
# 混合
# ---------------------------------------------------------------------------

_MODES = ("normal", "multiply", "screen")


def _blend_channel(cb, cs, mode):
    """在 0..1 空间执行混合模式函数。"""
    if mode == "normal":
        return cs
    if mode == "multiply":
        return cb * cs
    if mode == "screen":
        return cb + cs - cb * cs
    raise ValueError("未知混合模式 %s" % mode)


def _to_byte(v):
    """0..1 浮点转 0..255 整数，四舍五入并夹紧，避免越界与截断色阶。"""
    v = int(math.floor(v * 255.0 + 0.5))
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def blend_pixel(base, top, mode, opacity=1.0):
    """混合一个像素。base 与 top 都是 0..255 的 RGBA，返回 RGBA。

    top 的 alpha 会乘以 opacity；base 自己的 alpha 也参与合成，因此支持
    透明底图。透明像素的 RGB 不参与任何计算。
    """
    if mode not in _MODES:
        raise ValueError("未知混合模式 %s" % mode)
    try:
        opacity = float(opacity)
    except (TypeError, ValueError):
        raise ValueError("不透明度必须是数字")
    if opacity < 0.0:
        opacity = 0.0
    elif opacity > 1.0:
        opacity = 1.0

    ab = base[3] / 255.0
    a_s = top[3] / 255.0 * opacity
    a_out = a_s + ab * (1.0 - a_s)
    if a_out <= 0.0:
        return (0, 0, 0, 0)

    out = []
    for i in range(3):
        cb = base[i] / 255.0
        cs = top[i] / 255.0
        blended = _blend_channel(cb, cs, mode)
        # 源覆盖 + 混合项 + 背景残留，再除以输出 alpha 回到直通 alpha。
        co = (a_s * (1.0 - ab) * cs +
              a_s * ab * blended +
              ab * (1.0 - a_s) * cb) / a_out
        out.append(_to_byte(co))
    return (out[0], out[1], out[2], _to_byte(a_out))


def _load_layer_source(layer):
    source = layer["path"] if isinstance(layer, dict) else layer
    if isinstance(source, Image):
        return source
    return load_png(source)


def composite(base, layers):
    """按 layers 的数组顺序依次叠加图层，返回新 Image。

    layers 中每项为含 path/mode/opacity 的字典（也接受 Image 本身）。
    每层的不透明度按顺序逐层叠乘，输出尺寸与底图一致。
    """
    out = Image(base.width, base.height, list(base.pixels))
    for layer in layers:
        if isinstance(layer, dict):
            mode = layer.get("mode", "normal")
            opacity = layer.get("opacity", 1.0)
        else:
            mode = "normal"
            opacity = 1.0
        top = _load_layer_source(layer)
        # 尺寸不一致时按左上角对齐，超出底图的部分裁剪，缺失部分视为透明。
        for y in range(out.height):
            if y >= top.height:
                continue
            for x in range(out.width):
                if x >= top.width:
                    continue
                out.set(x, y,
                        blend_pixel(out.at(x, y), top.at(x, y), mode, opacity))
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="blend")
    ap.add_argument("stack")
    ap.add_argument("--out", default="blend.png")
    args = ap.parse_args(argv)
    with open(args.stack, "r", encoding="utf-8") as f:
        spec = json.load(f)
    base_path = spec["base"]
    if not os.path.isabs(base_path):
        base_path = os.path.join(os.path.dirname(os.path.abspath(args.stack)),
                                 base_path)
    base = load_png(base_path)
    layers = []
    for layer in spec["layers"]:
        item = dict(layer)
        path = item.get("path")
        if path is not None and not os.path.isabs(path):
            item["path"] = os.path.join(
                os.path.dirname(os.path.abspath(args.stack)), path)
        layers.append(item)
    out = composite(base, layers)
    save_png(out, args.out)
    print("已输出 %s，图层 %d" % (args.out, len(spec["layers"])))
    return 0
