# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blend.core import Image, blend_pixel  # noqa: E402


def test_image_default():
    img = Image(3, 2)
    assert img.at(0, 0) == (0, 0, 0, 0)
    assert len(img.pixels) == 6


def test_blend_normal_full_alpha():
    base = (10, 20, 30, 255)
    top = (200, 100, 50, 255)
    out = blend_pixel(base, top, "normal", 1.0)
    assert out[0] == 200


def test_blend_multiply_darkens():
    base = (128, 128, 128, 255)
    top = (128, 128, 128, 255)
    out = blend_pixel(base, top, "multiply", 1.0)
    assert out[0] <= 128


def test_blend_screen_brightens():
    base = (128, 128, 128, 255)
    top = (128, 128, 128, 255)
    out = blend_pixel(base, top, "screen", 1.0)
    assert out[0] >= 128
