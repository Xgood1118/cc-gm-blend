# -*- coding: utf-8 -*-
"""合成器行为测试：透明度、混合模式、不透明度、顺序与输出稳定性。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blend.core import (  # noqa: E402
    Image, blend_pixel, composite, load_png, main, save_png,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")


def solid(width, height, rgba):
    return Image(width, height, [rgba] * (width * height))


def gradient(width, height):
    """横向 0..255 灰度渐变，alpha 255。"""
    pixels = []
    for _ in range(height):
        for x in range(width):
            v = round(x * 255 / (width - 1))
            pixels.append((v, v, v, 255))
    return Image(width, height, pixels)


def write_img(img, tmp_path, name):
    path = str(tmp_path / name)
    save_png(img, path)
    return path


# ---------------------------------------------------------------------------
# 透明度
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["normal", "multiply", "screen"])
def test_fully_transparent_layer_keeps_base(mode):
    """完全透明的像素在任何模式下都不能改变底图，也不能留下灰块/黑边。"""
    base = (37, 99, 201, 77)
    # 透明像素故意带非零 RGB，结果必须与它无关。
    top = (255, 255, 255, 0)
    assert blend_pixel(base, top, mode) == base
    assert blend_pixel(base, (0, 0, 0, 0), mode) == base


@pytest.mark.parametrize("mode", ["normal", "multiply", "screen"])
def test_transparent_layer_rgb_never_leaks(mode):
    """半透明图层的 RGB 参与计算，但完全透明的 RGB 不影响任何通道。"""
    base = (10, 20, 30, 255)
    for rgb in [(0, 0, 0), (255, 255, 255), (12, 200, 99)]:
        assert blend_pixel(base, rgb + (0,), mode) == base


def test_half_alpha_layer_on_opaque_base():
    """50% 红色叠在蓝色上：结果不含黑色污染，等于常见软件的 100/50/25。"""
    assert blend_pixel((0, 0, 0, 255), (200, 100, 50, 128), "normal") == (
        100, 50, 25, 255)


def test_half_alpha_layer_on_transparent_base():
    """底图完全透明时，半透明层自身保持直通 alpha 与原本 RGB（无黑边）。"""
    assert blend_pixel((0, 0, 0, 0), (200, 100, 50, 128), "normal") == (
        200, 100, 50, 128)


def test_opaque_layer_replaces_transparent_base():
    assert blend_pixel((0, 0, 0, 0), (200, 100, 50, 255), "normal") == (
        200, 100, 50, 255)


def test_both_layers_with_alpha_matches_standard_formula():
    """两层都半透明（蓝 128 底、红 128 顶）的标准合成结果。"""
    assert blend_pixel((0, 0, 255, 128), (255, 0, 0, 128), "normal") == (
        170, 0, 85, 192)


def test_both_transparent_stays_transparent():
    assert blend_pixel((0, 0, 0, 0), (200, 100, 50, 0), "normal") == (
        0, 0, 0, 0)


# ---------------------------------------------------------------------------
# 混合模式公式
# ---------------------------------------------------------------------------

def test_normal_formula():
    assert blend_pixel((10, 20, 30, 255), (200, 100, 50, 255), "normal") == (
        200, 100, 50, 255)


def test_multiply_formula():
    # round(200*128/255)=100, round(100*64/255)=25, round(50*32/255)=6
    assert blend_pixel((200, 100, 50, 255), (128, 64, 32, 255),
                       "multiply") == (100, 25, 6, 255)


def test_screen_formula():
    # 255 - (255-a)(255-b)/255 每通道四舍五入
    assert blend_pixel((10, 200, 50, 255), (100, 100, 200, 255),
                       "screen") == (106, 222, 211, 255)


def test_multiply_with_white_is_identity():
    base = (60, 120, 180, 255)
    assert blend_pixel(base, (255, 255, 255, 255), "multiply")[:3] == base[:3]


def test_multiply_with_black_darkens_to_black():
    assert blend_pixel((60, 120, 180, 255), (0, 0, 0, 255), "multiply")[:3] == (
        0, 0, 0)


def test_screen_with_black_is_identity():
    base = (60, 120, 180, 255)
    assert blend_pixel(base, (0, 0, 0, 255), "screen")[:3] == base[:3]


def test_screen_with_white_is_white():
    assert blend_pixel((60, 120, 180, 255), (255, 255, 255, 255),
                       "screen")[:3] == (255, 255, 255)


def test_modes_on_gradient_match_formula(tmp_path):
    """渐变上逐点验证三种模式，允许四舍五入误差 ±1。"""
    base = gradient(256, 2)
    for mode in ("normal", "multiply", "screen"):
        top_val = 128
        expected = []
        for x in range(256):
            cb = x / 255.0
            cs = top_val / 255.0
            if mode == "normal":
                b = cs
            elif mode == "multiply":
                b = cb * cs
            else:
                b = cb + cs - cb * cs
            expected.append(round(b * 255))
        for x in range(256):
            got = blend_pixel(base.at(x, 0), (top_val, top_val, top_val, 255),
                              mode)[0]
            assert abs(got - expected[x]) <= 1, (mode, x, got, expected[x])


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        blend_pixel((0, 0, 0, 255), (0, 0, 0, 255), "overlay")


# ---------------------------------------------------------------------------
# 不透明度
# ---------------------------------------------------------------------------

def test_opacity_035_differs_from_10():
    base = (100, 150, 200, 255)
    top = (0, 0, 0, 255)
    low = blend_pixel(base, top, "normal", 0.35)
    full = blend_pixel(base, top, "normal", 1.0)
    assert low != full
    assert low == (65, 98, 130, 255)
    assert full == (0, 0, 0, 255)


def test_opacity_multiplies_alpha():
    assert blend_pixel((0, 0, 0, 255), (200, 100, 50, 128),
                       "normal", 0.5) == (50, 25, 13, 255)

def test_opacity_zero_is_transparent():
    base = (12, 34, 56, 255)
    for mode in ("normal", "multiply", "screen"):
        assert blend_pixel(base, (200, 100, 50, 255), mode, 0.0) == base


# ---------------------------------------------------------------------------
# 顺序
# ---------------------------------------------------------------------------

def make_layers(tmp_path):
    a = write_img(solid(6, 4, (200, 40, 40, 255)), tmp_path, "a.png")
    b = write_img(solid(6, 4, (100, 100, 100, 255)), tmp_path, "b.png")
    return (
        {"path": a, "mode": "normal", "opacity": 1.0},
        {"path": b, "mode": "multiply", "opacity": 1.0},
    )


def test_layer_order_matters(tmp_path):
    base = solid(6, 4, (100, 100, 100, 255))
    a, b = make_layers(tmp_path)
    ab = composite(base, [a, b])
    ba = composite(base, [b, a])
    assert ab.at(0, 0) != ba.at(0, 0)
    # 先 normal 红盖住，再 multiply 灰：得到灰度的红
    assert ab.at(0, 0) == (78, 16, 16, 255)
    # 先 multiply 变暗，再 normal 红完全覆盖
    assert ba.at(0, 0) == (200, 40, 40, 255)


def test_composite_respects_opacity(tmp_path):
    base = solid(4, 3, (100, 150, 200, 255))
    top = write_img(solid(4, 3, (0, 0, 0, 255)), tmp_path, "black.png")
    low = composite(base, [{"path": top, "mode": "normal", "opacity": 0.35}])
    full = composite(base, [{"path": top, "mode": "normal", "opacity": 1.0}])
    assert low.at(0, 0) == (65, 98, 130, 255)
    assert full.at(0, 0) == (0, 0, 0, 255)
    assert low.at(0, 0) != full.at(0, 0)


def test_composite_ignores_transparent_layer_pixels(tmp_path):
    base = solid(4, 3, (100, 150, 200, 255))
    top = write_img(solid(4, 3, (0, 0, 0, 0)), tmp_path, "clear.png")
    out = composite(base, [{"path": top, "mode": "multiply", "opacity": 1.0}])
    assert out.at(2, 1) == (100, 150, 200, 255)


# ---------------------------------------------------------------------------
# 颜色与输出
# ---------------------------------------------------------------------------

def test_rounding_not_truncation():
    """0.5 应进位到 1，截断会得到 0 并产生色阶偏差。"""
    assert blend_pixel((1, 1, 1, 255), (0, 0, 0, 255), "normal", 0.5) == (
        1, 1, 1, 255)


def test_gradient_composite_has_no_banding(tmp_path):
    base = gradient(256, 2)
    top = write_img(
        Image(256, 2, [(128, 128, 128, 255)] * 512), tmp_path, "gray.png")
    out = composite(base, [{"path": top, "mode": "multiply", "opacity": 1.0}])
    values = [out.at(x, 0)[0] for x in range(256)]
    assert values[0] == 0
    assert values[-1] == 128
    for a, b in zip(values, values[1:]):
        assert b >= a
        assert b - a <= 1


def test_png_roundtrip(tmp_path):
    img = Image(5, 3, [(x, y, (x + y) % 256, 255)
                       for y in range(3) for x in range(5)])
    path = write_img(img, tmp_path, "rt.png")
    back = load_png(path)
    assert (back.width, back.height) == (5, 3)
    assert back.pixels == img.pixels


def test_png_roundtrip_with_alpha(tmp_path):
    """带 alpha 的像素经 PNG 读写后完全一致（含半透明与全透明）。"""
    px = [(0, 0, 0, 0), (255, 255, 255, 0), (200, 100, 50, 128),
          (1, 2, 3, 254)] + [(x * 7 % 256, 255 - x, x, 100)
                             for x in range(5, 15)]
    img = Image(19, 2, px[:19] + [(0, 0, 0, 0)] * (38 - len(px)))
    path = write_img(img, tmp_path, "alpha.png")
    assert load_png(path).pixels == img.pixels


def test_load_png_handles_filters(tmp_path):
    """load_png 能解码 Sub/Up/Average/Paeth 过滤的行。"""
    import struct
    import zlib

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body +
                struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    width, height = 3, 4
    pixels = [((x * 40 + y * 10) % 256, (y * 50 + x) % 256,
               (x * 20 + y * 30) % 256, 255)
              for y in range(height) for x in range(width)]
    # 逐行用不同过滤编码；编码器与解码器独立。
    raw = bytearray()
    prev = bytes(width * 4)
    for y in range(height):
        line = bytes(c for p in pixels[y * width:(y + 1) * width] for c in p)
        ftype = y % 5
        enc = bytearray()
        for i, v in enumerate(line):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            if ftype == 0:
                e = v
            elif ftype == 1:
                e = v - a
            elif ftype == 2:
                e = v - b
            elif ftype == 3:
                e = v - ((a + b) >> 1)
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                e = v - pred
            enc.append(e & 0xFF)
        raw.append(ftype)
        raw.extend(enc)
        prev = line
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))
    path = str(tmp_path / "filters.png")
    with open(path, "wb") as f:
        f.write(data)
    assert load_png(path).pixels == pixels


def test_output_size_matches_base(tmp_path):
    base = solid(7, 5, (1, 2, 3, 255))
    top = write_img(solid(3, 2, (200, 0, 0, 255)), tmp_path, "small.png")
    out = composite(base, [{"path": top, "mode": "normal", "opacity": 1.0}])
    assert (out.width, out.height) == (base.width, base.height)


def test_all_channels_in_range(tmp_path):
    """真实 stack 跑完所有通道都在 0..255。"""
    with open(os.path.join(DATA, "stack.json"), "r", encoding="utf-8") as f:
        spec = json.load(f)
    base = load_png(spec["base"])
    out = composite(base, spec["layers"])
    assert (out.width, out.height) == (base.width, base.height)
    for px in out.pixels:
        assert len(px) == 4
        for c in px:
            assert 0 <= c <= 255


def test_cli_output_is_byte_identical(tmp_path):
    stack = os.path.join(DATA, "stack.json")
    p1 = str(tmp_path / "one.png")
    p2 = str(tmp_path / "two.png")
    assert main([stack, "--out", p1]) == 0
    assert main([stack, "--out", p2]) == 0
    with open(p1, "rb") as f:
        a = f.read()
    with open(p2, "rb") as f:
        b = f.read()
    assert a == b
    img = load_png(p1)
    base = load_png(os.path.join(DATA, "base.png"))
    assert (img.width, img.height) == (base.width, base.height)
