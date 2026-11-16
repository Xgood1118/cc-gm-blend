# 图层混合

骨架能读三层、能按模式合成、能出 PNG，但三种模式的结果都不符合常规图像软件。

## 已知缺口

- `normal` 模式只用 top 的 alpha 与 opacity，没有考虑 base 自己的 alpha，
  底图有透明区域时会露出黑边。
- 颜色按 0 到 255 直接混合，没有预乘 alpha，半透明图层的 RGB 会被透明区域污染。
- `multiply` 对 alpha 完全没有处理，透明区域在底图上叠加出灰块。
- `screen` 同理，透明区域会把底图提亮。
- `composite` 忽略 `layers[i]["opacity"]`，三层都用满不透明度。
- 图层叠乘顺序写死，改顺序不生效。

## 运行

```
python gen_samples.py
python -m blend.cli data/stack.json --out blend.png
python -m pytest tests -q
```

底图 200x140 带横向渐变，三个图层分别是左上角半透明色块、棋盘格正片叠底、右上角光晕滤色。
第三层的不透明度是 0.8，第二层是 0.35。
