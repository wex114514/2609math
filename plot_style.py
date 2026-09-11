"""科研论文级 matplotlib 绘图样式(中文兼容)。

用法(在每个绘图脚本开头):
    from plot_style import (apply, combo_axes, response_surface, series_style,
                            series_color, legend_outside, figure_legend_above,
                            panel_labels, save_publication)
    apply()                      # 默认 Nature(NPG) 配色
    fig, axes = combo_axes(2)    # 有第二类证据就横排组图,不要单面板素图
    ax.plot(x, y, label=名, **series_style(名))   # 多条曲线:色+线型按量名固定
    apply(palette="nejm")        # 或切换其它期刊风格(见 PALETTES)

可选配色风格(PALETTES 键名):
    nature  Nature/NPG(默认):藏蓝+正红,顶刊气质
    okabe   Okabe–Ito:色盲安全,对比最强
    nejm    新英格兰医学:砖红+藏蓝,沉稳权威
    lancet  柳叶刀:深蓝正红,经典印刷风
    jama    JAMA:灰调低饱和,最内敛
    muted   Tol Muted:色盲安全的柔和替代
    morandi 莫兰迪高级灰:适合汇报/封面(数据对比稍弱)
    earth   大地 Circos:低饱和大地色+青绿+淡紫,弦图/环形热图气质
    mma     竞赛蓝红:钢蓝+珊瑚红+灰绿,数模竞赛经典搭配
切换优先级:apply(palette=...) 参数 > 环境变量 MS_PLOT_PALETTE >
工程根 plot_palette.txt(数模工坊在项目设置里勾选配色后自动写入)> 默认 nature。
**同一篇论文只用一套**。

设计目标:贴近 SCI 期刊/数模论文配图规范——
- 西文 Times New Roman、中文宋体优先,数学公式 STIX 字体;
  字体按【实际字形】筛选,装了但缺汉字字形的一律不用,杜绝方块字
- 默认开启约束布局 + savefig 紧凑边界:标题/标签/图例互不遮挡,也不会被裁切
- 刻度向内、主次刻度、四边边框,线宽统一
- 期刊级配色预设,默认 500 dpi(可在「结果图预设」里调);禁用 jet 与装饰性 3D
  (柱/饼),双参数灵敏度用响应曲面
- 默认横排组图 (a)(b)(c);鼓励同时存 PNG+PDF/SVG
- 图内信息量要高:关键指标/数值标注、误差带、极值 annotate;三点散点/三点灵敏度单独成图算硬伤
- 图种宜丰富:优先组图/3D 响应面/热图/平行坐标/Pareto/诊断散点,避免默认条形图刷屏;禁用雷达图
"""
import json
import logging
import math
import os
import re
import warnings

import matplotlib

# 西文衬线字体(论文常用 Times New Roman)
_SERIF_LATIN = ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"]
# 中文衬线/正文字体候选(宋体优先,黑体兜底)
_CJK_FONTS = [
    "SimSun", "Songti SC", "Noto Serif CJK SC", "STSong",   # 宋体系
    "Microsoft YaHei", "SimHei", "PingFang SC",              # 黑体兜底
    "Noto Sans CJK SC", "WenQuanYi Zen Hei", "Arial Unicode MS",
]

# 可选字体族:每族按优先级给候选,实际用哪款由字形探测决定(装了就用,没装往后退)
# 只有细体字面的字体(如 macOS 的 STSong,整个 Songti.ttc 里只有 weight=300)
# 会被 _rank_by_weight 自动挪到最后,这里的先后只表达偏好。
CJK_FAMILIES = {
    "song": ["SimSun", "Songti SC", "Noto Serif CJK SC", "STSong",
             "Source Han Serif SC"],
    "hei": ["SimHei", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
            "Source Han Sans SC", "WenQuanYi Zen Hei"],
    "kai": ["KaiTi", "STKaiti", "Kaiti SC", "SimSun"],
}
LATIN_FAMILIES = {
    "times": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "arial": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
    "dejavu": ["DejaVu Serif", "DejaVu Sans"],
}

# 结果图预设:一套完整的版式参数。用户在技能库「结果图预设」里选,
# 工程根会落一份 plot_prefs.json,apply() 自动读取——脚本不必改一行代码。
DEFAULT_PREFS = {
    "cjk_font": "song",       # song 宋体 / hei 黑体 / kai 楷体
    "latin_font": "times",    # times / arial / dejavu
    "base_size": 11,          # 正文字号(pt),其余字号按它联动
    "bold_labels": False,     # 标题与轴标签是否加粗
    "ticks": "in",            # in 向内 / out 向外 / none 不显示刻度线
    "minor_ticks": True,      # 是否显示次刻度
    "frame": "box",           # box 四边框 / lb 仅左下轴 / none 无边框
    "grid": "y",              # none 不要网格 / y 仅横向 / both 双向
    # 默认淡横向网格:无网格的折线看起来像一张空白坐标纸,结果图会显得素。
    "legend_frame": True,     # 图例是否带边框
    # 默认去掉图内标题:论文里图题写在图下方(「图 3.2 …」),图内再写一遍就是重复,
    # 还会把版心高度吃掉一行。审图口径由 main._fig_title_rule 跟着这里走。
    "title": "none",          # keep 保留图内标题 / sup 只去总标题 / none 全去掉
    "line_width": 1.8,
    "dpi": 500,
}
# apply() 解析出的当前版式,供 tidy()/savefig 保护层读取(脚本不必层层传参)
_ACTIVE_PREFS: dict = dict(DEFAULT_PREFS)
PRESETS = {
    # SCI 期刊风(默认):刻度向内、四边框、淡横向网格——无网格的结果图太空
    "sci": {},
    # 教科书/国标风:刻度向外、仅左下轴、淡横向网格,读数友好
    "classic": {"ticks": "out", "frame": "lb", "grid": "y",
                "minor_ticks": False},
    # 答辩/汇报风:字大加粗、线粗,投影仪上也看得清
    "slides": {"base_size": 13, "bold_labels": True, "line_width": 2.4,
               "grid": "y", "minor_ticks": False},
    # 极简风:无边框无刻度线,只留数据本身
    "minimal": {"ticks": "none", "frame": "none", "grid": "y",
                "minor_ticks": False, "legend_frame": False},
}
_PREFS_FILE = "plot_prefs.json"
# 探针字符:光看字体名装没装不够——名字在、字形缺,画出来照样是一排方块。
# 汉字取常用字,西文取字母数字与连字符(负号另由 axes.unicode_minus 关掉)。
_PROBE_CJK = "模型分析问题结果图表"
_PROBE_LATIN = "AZaz09"
# matplotlib 3.6 起支持「按字形逐个回退」:font.family 给一串字体名时,
# 西文用第一款、缺字形的汉字自动落到后面的中文字体。低版本没有这个能力。
_GLYPH_FALLBACK = tuple(
    int(x) for x in matplotlib.__version__.split(".")[:2]
    if x.isdigit()) >= (3, 6)


def _font_file(name: str) -> str | None:
    """字体名 → 实际字体文件;没装则 None(不回落到默认字体,否则探测失真)。"""
    from matplotlib import font_manager
    try:
        return font_manager.findfont(
            font_manager.FontProperties(family=name),
            fallback_to_default=False)
    except Exception:  # noqa: BLE001  未安装 / 字体库损坏
        return None


def _has_glyphs(name: str, probe: str) -> bool:
    """这款字体是否真的画得出这些字符(而不是渲染成方块)。"""
    path = _font_file(name)
    if not path:
        return False
    try:
        from matplotlib.ft2font import FT2Font
        face = FT2Font(path)
        return all(face.get_char_index(ord(ch)) for ch in probe)
    except Exception:  # noqa: BLE001  取不到字形表就当它不可用
        return False

# 期刊配色预设。每套 8 色,顺序按语义:第1色=本文方法/主结果,第2色=基线,
# 第3色=对照,末位黑色留给参考线/真值线。同一篇论文只用一套。
PALETTES = {
    # Nature/NPG:藏蓝+正红,顶刊气质(默认)
    "nature": ["#3C5488", "#E64B35", "#00A087", "#4DBBD5",
               "#F39B7F", "#8491B4", "#91D1C2", "#000000"],
    # Okabe–Ito:色盲安全,科研标准,对比最强
    "okabe": ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
              "#E69F00", "#56B4E9", "#F0E442", "#000000"],
    # NEJM 新英格兰医学:砖红+藏蓝,沉稳权威
    "nejm": ["#0072B5", "#BC3C29", "#20854E", "#E18727",
             "#7876B1", "#6F99AD", "#FFDC91", "#000000"],
    # Lancet 柳叶刀:深蓝正红,经典印刷风
    "lancet": ["#00468B", "#ED0000", "#42B540", "#0099B4",
               "#925E9F", "#FDAF91", "#AD002A", "#000000"],
    # JAMA:灰调低饱和,最内敛
    "jama": ["#374E55", "#DF8F44", "#00A1D5", "#B24745",
             "#79AF97", "#6A6599", "#80796B", "#000000"],
    # Tol Muted:色盲安全的低饱和替代,柔和耐看
    "muted": ["#332288", "#CC6677", "#117733", "#88CCEE",
              "#DDCC77", "#882255", "#44AA99", "#000000"],
    # 莫兰迪高级灰:适合汇报/封面,数据对比稍弱
    "morandi": ["#7A8B99", "#C08552", "#8F9E8B", "#B4869F",
                "#A5A58D", "#6B705C", "#9A8C98", "#000000"],
    # 大地 Circos:低饱和大地色+青绿+淡紫(BrBG/PRGn 系),弦图/环形热图气质
    "earth": ["#35978F", "#8C510A", "#5AAE61", "#9970AB",
              "#BF812D", "#80CDC1", "#999999", "#000000"],
    # 竞赛蓝红:钢蓝+珊瑚红+灰绿(源自 MathModelAgent 竞赛配色,补紫/沙填满循环)
    "mma": ["#2E5B88", "#E85D4C", "#4A9B7F", "#B8D4E8",
            "#8C6BB1", "#C8A464", "#7F7F7F", "#000000"],
}
_DEFAULT_PALETTE = "nature"

# 当前生效色板(apply() 可原地切换;先 import PALETTE 再 apply() 也能拿到新色)
PALETTE = list(PALETTES[_DEFAULT_PALETTE])
# 兼容旧引用
OKABE_ITO = list(PALETTES["okabe"])

FORBIDDEN = {
    "colormaps": ["jet", "rainbow", "hsv", "nipy_spectral"],
    "effects": ["decorative_3d", "shadow", "fancybox_gradient"],
}


def _font_weights(name: str) -> set:
    """这款字体在本机注册了哪些字重(400=常规,700=粗体)。"""
    from matplotlib.font_manager import fontManager, weight_dict
    out = set()
    for f in fontManager.ttflist:
        if f.name != name:
            continue
        w = f.weight
        if isinstance(w, str):
            w = weight_dict.get(w.lower())
        try:
            out.add(int(w))
        except (TypeError, ValueError):      # 字重写成了认不出的字面值
            continue
    return out


def _rank_by_weight(names):
    """去重,并把没有常规字重(400)字面的字体挪到最后。

    macOS 的 STSong 在整个 Songti.ttc 里只有一个 weight=300 的细体,而它的字形
    覆盖与排在它前面的 Songti SC 完全重合:留在字体栈前排,既让正文落到细体上,
    又会让 matplotlib 逐次打 `findfont: Failed to find font weight`。挪后不删——
    机器上只有细体可用时,细一点的中文仍然远好过一屏方块。
    """
    ordered = list(dict.fromkeys(names))     # 候选表本身有交集,先去重
    return ([n for n in ordered if 400 in _font_weights(n)]
            + [n for n in ordered if 400 not in _font_weights(n)])


def _installed_font_names() -> set:
    """本机 matplotlib 登记过的字体名。测试可替换,避免用例绑死某台机器的字体库存。"""
    from matplotlib.font_manager import fontManager
    return {f.name for f in fontManager.ttflist}


def _available(cands, probe: str = ""):
    """按字形可用性筛字体:装了但缺字形的一律排除,从源头杜绝方块字。"""
    installed = _installed_font_names()
    named = [f for f in cands if f in installed]
    if probe:
        named = [f for f in named if _has_glyphs(f, probe)]
    return _rank_by_weight(named)


def font_report() -> dict:
    """当前可用的中西文字体与生效字体栈,排查方块字时用。"""
    latin = _available(_SERIF_LATIN, _PROBE_LATIN)
    cjk = _available(_CJK_FONTS, _PROBE_CJK)
    return {
        "latin": latin, "cjk": cjk,
        "glyph_fallback": _GLYPH_FALLBACK,
        "family": list(matplotlib.rcParams["font.family"]),
    }


def resolve_prefs(prefs: dict | None = None) -> dict:
    """合成最终版式参数:内置默认 ← 预设名 ← 工程根 plot_prefs.json ← 显式入参。

    返回值额外带 ``_explicit``:用户真正动过的字段名列表。savefig 保护层据此
    判断「用户设了 dpi」——脚本里 `savefig(..., dpi=300)` 是提示词教的习惯写法,
    matplotlib 里显式实参永远压过 rcParams,不强制覆盖的话用户在界面上设的
    dpi 一辈子不生效。
    """
    out = dict(DEFAULT_PREFS)
    explicit: set = set()
    layers = []
    from_file = _prefs_from_file()
    if from_file:
        layers.append(from_file)
    if prefs:
        layers.append(prefs)
    for layer in layers:
        name = str(layer.get("preset") or "").strip().lower()
        if name in PRESETS:
            out.update(PRESETS[name])
        picked = {k: v for k, v in layer.items()
                  if k in DEFAULT_PREFS and v is not None}
        out.update(picked)
        explicit.update(picked)
    out["_explicit"] = sorted(explicit)
    return out


def _prefs_from_file() -> dict:
    """读工程根 plot_prefs.json(与本文件同目录)里保存的版式设置。"""
    try:
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          _PREFS_FILE)
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _palette_from_file() -> str | None:
    """读工程根 plot_palette.txt(与本文件同目录)中记录的配色名。"""
    try:
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "plot_palette.txt")
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8") as f:
                name = f.read().strip().lower()
            return name or None
    except OSError:
        pass
    return None


_SERIES_MAP_FILE = "_palette_map.json"

# 色板只有 8 色,第 9 个量起靠线型+marker 接着分辨:8 色 × 4 组线型 = 32 个量互不撞车。
# 旧写法是发完 8 色就取模回头再发一遍同色同线型,实测产物里「发动机 1」与「发动机 3」
# 在六个面板里全是黑实线,图例列了两条、图上认不出哪条是哪条——比配色不统一严重得多。
_SERIES_LS = ("-", "--", "-.", ":")
_SERIES_MK = (None, "o", "s", "^")


def _series_map_path() -> str:
    """figures/_palette_map.json:量名 → 色板下标 的全篇固定映射。"""
    root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "figures", _SERIES_MAP_FILE)


def _load_series_map() -> dict:
    try:
        with open(_series_map_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _dedupe_series_map(mapping: dict) -> bool:
    """把历史遗留的重复槽位改开(先来的保留,后来的挪到空槽);改动过返回 True。

    旧版发号发到 8 就取模回头,老会话的映射表里躺着好几对同槽的量名。表不修,
    重跑老脚本照样撞色——修表比重画便宜,且先定色的量颜色不变,只有本来就撞车的
    那几个换色,跨图一致性反而是被修复的一方。
    """
    used, dups, changed = set(), [], False
    for key in list(mapping):
        val = mapping.get(key)
        if not isinstance(val, int) or val < 0:
            mapping.pop(key)
            changed = True
        elif val in used:
            dups.append(key)          # 先收着:得等所有原槽位都记全再挪
        else:
            used.add(val)
    for key in dups:
        mapping[key] = _free_slot(used)
        used.add(mapping[key])
        changed = True
    return changed


def _free_slot(used: set) -> int:
    """最小的空槽位。槽位不封顶:超过 8 的部分由线型接着分辨,不再回头发同色。"""
    i = 0
    while i in used:
        i += 1
    return i


def _series_slot(name: str) -> int:
    """按【量名】取全篇固定的槽位,槽位再决定颜色与线型。

    统稿环节会另写一个脚本重画部分图,各脚本自己按 PALETTE[0]、PALETTE[1] 顺序
    取色时,「一阶指数」在原图是蓝色、在统稿新图里就成了橙色——同一个量在相邻两张
    图里换了颜色,比不统一风格更糟。把映射落盘成 figures/_palette_map.json,
    谁先用谁定色,后来的脚本(含统稿)读同一份表,跨图一致就成了确定性的事。
    """
    key = str(name or "").strip()
    if not key:
        return 0
    mapping = _load_series_map()
    changed = _dedupe_series_map(mapping)
    if key not in mapping:
        mapping[key] = _free_slot({int(v) for v in mapping.values()})
        changed = True
    if changed:
        try:
            fp = _series_map_path()
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except OSError:
            pass          # 落盘失败不该连累出图,本次仍返回一个稳定槽位
    return int(mapping[key])


def _shade(color: str, turn: int) -> str:
    """同一个基色的第 turn 档明暗:深色往白里调、浅色往黑里调,保证与背景仍有对比。

    映射表是【全篇共用】的:一篇论文动辄二十几个量名,于是一张只画 5 条线的图,
    也可能因为前面已经发掉 20 个槽位而拿到两个同色。实测产物里「发动机 1」拿到
    槽位 7、「发动机 3」拿到槽位 23,两者取模后都是黑色——图上认不出哪条是哪条。
    色板只有 8 色改不了,但每个基色再分三档明暗就有 24 个可辨的色,
    足够覆盖真实论文的量名数量,而且老脚本只调 series_color 也能直接受益。
    """
    if turn <= 0:
        return color
    import matplotlib.colors as mcolors

    r, g, b = mcolors.to_rgb(color)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    # 调亮的幅度不能太狠:0.66 会把黑色调成 #a8a8a8,打印在白纸上已经发飘
    k = (0.32, 0.52)[min(turn, 2) - 1]
    end = 1.0 if lum <= 0.5 else 0.0        # 深色调亮、浅色调暗,别调成一片白
    return mcolors.to_hex(tuple(c + (end - c) * k for c in (r, g, b)))


def series_color(name: str):
    """按【量名】取颜色,全篇同一个量永远同一种颜色。

    超过 8 个量时按基色的明暗档继续分(共 24 档);再多就分不出来了,
    此时应改用 series_style() 连线型一起取,否则两条线画出来一模一样。
    """
    slot = _series_slot(name)
    n = len(PALETTE)
    return _shade(PALETTE[slot % n], (slot // n) % 3)


def series_colors(*names):
    """一次取多个量的颜色,顺序与入参一致。"""
    return [series_color(n) for n in names]


def series_style(name: str, marker: bool = True) -> dict:
    """按【量名】取一整套可辨识样式:`ax.plot(x, y, label=n, **series_style(n))`。

    颜色仍按量名固定(跨图一致):8 个基色先各分 3 档明暗(共 24 种),24 个量之后
    才开始换线型与 marker,所以第 9、第 25 个量都不会与前面的量画成同一个样子。
    黑白打印同样分得开——明暗档在灰度下就是深浅不同的线。
    marker=False 用于点很密的曲线(marker 会连成一片糊掉),此时靠线型区分。
    """
    slot = _series_slot(name)
    n = len(PALETTE)
    turn = slot // n
    out = {"color": _shade(PALETTE[slot % n], turn % 3),
           "linestyle": _SERIES_LS[(turn // 3) % len(_SERIES_LS)]}
    mk = _SERIES_MK[(turn // 3) % len(_SERIES_MK)]
    if marker and mk:
        # markevery 用小数:按曲线长度均匀放几个点,不随数据点数暴涨成一条粗线
        out.update(marker=mk, markevery=0.12, markersize=4.0)
    return out


def set_palette(name: str) -> list:
    """按名称切换当前色板(原地更新 PALETTE,已 import 的引用同步生效)。"""
    key = (name or "").strip().lower()
    colors = PALETTES.get(key)
    if not colors:
        colors = PALETTES[_DEFAULT_PALETTE]
    PALETTE[:] = colors
    matplotlib.rcParams["axes.prop_cycle"] = matplotlib.cycler(color=PALETTE)
    return PALETTE


# 画布尺寸契约。**宽度**锁定成该角色在 A4 正文里的实际显示宽度,缩放比才是 1:1,
# 图内字号 = 排版后磅值;md2word._image_role_width_cm 按图里写着的 dpi 反推物理宽度
# 照此摆放,所以这里画多宽,排进 Word 就是多宽(上限版心 16cm):
#   single 11.2cm(窄图,右边会空掉近三成版心) / panel 13.7cm(对比、多面板)
#   wide 14.7cm(单面板的默认档) / row2、row3 16.0cm(横排组图,占满版心)
# **版面是稀缺资源,一张图就得把分到的宽度吃满**:同样占掉一段版面,11.2cm 的窄图
# 右侧白掉 4.8cm,而 16cm 的一行两列能多讲一格证据。所以默认单图走 wide、
# 有第二类证据一律走 row2;single 只留给确实需要窄图的场合。
# **面板一律横排**:三格竖着堆(subplots(3,1))宽度只能吃掉版心一半、却占掉大半页,
# 图内文字排出来比正文还小;同样三格横排成 16cm×5cm 一条,占版面小一半还更清楚。
# **高度**随面板行数增长:宽度锁死后,再把 2×2 面板塞进单图高度,文字就会把轴域挤没
# (实测 2×2 挤进 5.3×3.2 英寸,标题和轴标全都溢出重叠)。高度另有上限,
# 一张图最多占版面约 11cm,不然一张图吃掉半页。
FIG_W_IN = {"single": 4.4, "panel": 5.4, "wide": 5.8, "row2": 6.3, "row3": 6.3}
_H_FIRST_ROW = 3.0        # 第一行面板的高度
_H_PER_EXTRA_ROW = 1.3    # 每多一行加的高度(共用轴标,不必整行翻倍)
_H_MAX_IN = 4.3           # ≈11cm,与 md2word._FIG_MAX_H_CM 对齐

# 兼容旧写法 FIGSIZE["panel"]
FIGSIZE = {k: (w, _H_FIRST_ROW) for k, w in FIG_W_IN.items()}


def figsize(kind: str = "wide", rows: int = 1):
    """按角色取画布尺寸:宽度对齐最终排版宽度,高度随面板行数增长(有上限)。

    kind="row2"/"row3" 是横排组图的满栏档(6.3 英寸 = 版心 16cm),
    `plt.subplots(1, 2, figsize=figsize("row2"))`、
    `plt.subplots(1, 3, figsize=figsize("row3"))` 即可横排占满;
    rows 传子图的**行数**(如 plt.subplots(2, 2) 传 2)。
    缺省的 "wide"(5.8 英寸 = 14.7cm)是单面板的档:窄档 "single" 排出来只有 11.2cm,
    右边白掉近三成版心,除非确实要窄图,否则不要选它。
    多个面板优先横排,不要 subplots(3, 1) 竖着堆——竖排宽度只吃到版心一半,
    却占掉大半页,图内文字排出来比正文还小。
    面板多就加高,不要靠加宽——宽度一旦超过版心 16cm,整张图会被等比缩小,
    图内文字跟着变小。
    """
    w = FIG_W_IN.get(kind, FIG_W_IN["wide"])
    n = max(1, int(rows or 1))
    h = min(_H_MAX_IN, _H_FIRST_ROW + _H_PER_EXTRA_ROW * (n - 1))
    return (w, h)


def combo_axes(n=2, *, rows=1, projections=None, sharex=False, sharey=False,
               **kwargs):
    """横排组图的推荐入口,返回 (fig, axes)。

    有第二类证据就 ``combo_axes(2)`` / ``combo_axes(3)``,不要自己填
    ``figsize=(14, 8)`` 或 ``subplots(3, 1)`` 竖着堆。

    ``projections`` 按格给投影,让 3D 曲面和 2D 证据同图:
    ``fig, axes = combo_axes(2, projections=("3d", None))``,再把左格交给
    ``response_surface(..., ax=axes[0])``、右格画等高线。
    """
    import matplotlib.pyplot as plt

    n = max(1, min(3, int(n)))
    rows = max(1, min(2, int(rows)))
    kind = {1: "wide", 2: "row2", 3: "row3"}[n] if rows == 1 else "row2"
    size = figsize(kind, rows=rows)
    if not projections:
        return plt.subplots(rows, n, figsize=size,
                            sharex=sharex, sharey=sharey, **kwargs)
    # 逐格投影:plt.subplots 的 subplot_kw 是整图统一的,给不了「左 3D 右 2D」
    projs = list(projections) + [None] * (rows * n - len(projections))
    has_3d = any(str(p) == "3d" for p in projs)
    # 3D 轴的 z 轴标签在约束布局里量不出高度,实测整图会被压成
    # 「axes sizes collapsed to zero」的空白条。建图时就不挂约束布局,手动留白。
    fig = plt.figure(figsize=size, constrained_layout=False if has_3d else None)
    if not has_3d:
        axes = [fig.add_subplot(rows, n, i + 1, projection=projs[i], **kwargs)
                for i in range(rows * n)]
        return fig, axes
    # 3D 格的 z 轴标签排在立方体右缘、且立方体本来就比格子大一圈,给不够就会压住
    # 右格的 y 轴标签。**但富余量要加在 3D 那一列的宽度上,不是加在列间距上**:
    # 早先靠 wspace=0.5 拉开,结果两格等宽、曲面又缩到 0.78,左格画出来只有右格
    # 一半大,半格版面全喂了空白。改成按列分配宽度,空出来的地方归曲面。
    ratios = [1.24 if str(projs[c]) == "3d" else 1.0 for c in range(n)]
    gs = fig.add_gridspec(rows, n, width_ratios=ratios,
                          left=0.04, right=0.95, bottom=0.13, top=0.89,
                          wspace=0.36, hspace=0.34)
    axes = [fig.add_subplot(gs[i // n, i % n], projection=projs[i], **kwargs)
            for i in range(rows * n)]
    return fig, axes


def response_surface(x, y, z, *, ax=None, xlabel="", ylabel="", zlabel="",
                     cmap="coolwarm", elev=28, azim=-55, mark=None,
                     colorbar=True):
    """双参数平滑响应曲面,返回 (fig, ax)。

    ``x``/``y``/``z`` 与 ``np.meshgrid`` 同形;``mark`` 为最优点 ``(x, y, z)``。
    ``ax`` 传 ``combo_axes(2, projections=("3d", None))`` 的 3D 格即可合成组图。
    只画平滑曲面,不要拿它画 3D 柱/饼。
    """
    import numpy as np
    import matplotlib.pyplot as plt

    xx, yy, zz = np.asarray(x), np.asarray(y), np.asarray(z)
    if ax is None:
        fig = plt.figure(figsize=figsize("wide"))
        # 3D 轴与约束布局叠加会把画布压扁,单开曲面时关掉自动布局
        try:
            fig.set_layout_engine("none")
        except Exception:  # noqa: BLE001  旧版 matplotlib 没有 layout engine
            fig.set_constrained_layout(False)
        ax = fig.add_subplot(111, projection="3d")
    else:
        fig = ax.get_figure()
    # Axes3D 画出来的立方体比自己那格大一圈,组图里 z 轴标签会直接压到隔壁格的
    # 轴标上(闸门查的是 ax.texts,查不到轴标签,只能在这里先收住)。
    others = [a for a in fig.get_axes()
              if a is not ax and a.get_label() != "<colorbar>"]
    try:
        ax.set_box_aspect(None, zoom=0.88 if others else 0.92)
    except TypeError:  # 旧版 matplotlib 的 set_box_aspect 没有 zoom
        pass
    step = max(1, min(xx.shape) // 40)
    surf = ax.plot_surface(
        xx, yy, zz, cmap=cmap, linewidth=0, antialiased=True,
        rstride=step, cstride=step, alpha=0.96)
    if colorbar:
        fig.colorbar(surf, ax=ax, shrink=0.55, pad=0.14)
    # 三维轴的默认刻度密度按 2D 给的,投影之后标签会斜着叠成一片:
    # 底面两根轴被压得最扁,只留 3 个刻度;竖直的 z 轴还排得开,留 4 个
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(3))
    ax.yaxis.set_major_locator(MaxNLocator(3))
    ax.zaxis.set_major_locator(MaxNLocator(4))
    if xlabel:
        ax.set_xlabel(xlabel, labelpad=8)
    if ylabel:
        ax.set_ylabel(ylabel, labelpad=8)
    if zlabel:
        # 不留 labelpad 的话,竖排的 z 轴标签会压在刻度数字或色标上
        ax.set_zlabel(zlabel, labelpad=10)
    ax.view_init(elev=elev, azim=azim)
    _tame_3d_panes(ax)
    if mark is not None and len(mark) >= 3:
        # 三维里一个孤零零的点几乎找不到:它要么被曲面挡住,要么读者看不出它悬在
        # 哪个 (x, y) 上方。补一根落到底面的虚线,顺带把点投影到底面画个圈——
        # 读者顺着虚线就能在底面读出最优参数。
        floor = float(np.nanmin(zz))
        ax.plot([mark[0], mark[0]], [mark[1], mark[1]], [floor, mark[2]],
                color="#E64B35", lw=1.0, ls="--", zorder=5)
        ax.scatter(mark[0], mark[1], floor, s=22, facecolors="none",
                   edgecolors="#E64B35", linewidths=1.0, depthshade=False)
        ax.scatter(mark[0], mark[1], mark[2], s=58, c="#E64B35",
                   edgecolors="white", linewidths=0.8, depthshade=False,
                   zorder=6)
    # 闸门据此认出「这张曲面是走正门画的」:手搓 plot_surface 会绕掉上面所有
    # 防出丑的处理(收进画框、稀释刻度、标最优点),成图必然难看,得拦下来。
    ax._ms_response_surface = True
    return fig, ax


def _tame_3d_panes(ax) -> None:
    """收拾三维背景:三个面各一层密虚线网格,叠起来比数据还抢眼。

    实测手搓的响应面三面都是默认的深色虚线网格,曲面反而看不清。改成淡实线,
    并把背景面刷白——纸质打印时那层灰底会糊成一片。
    """
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        # 两处分开 try:旧版 matplotlib 没有 set_pane_color,不能连累网格也不改
        try:
            axis.set_pane_color((1.0, 1.0, 1.0, 1.0))
        except Exception:  # noqa: BLE001  版式微调失败绝不能连累出图
            pass
        try:
            axis._axinfo["grid"].update(
                {"color": "#D9D9D9", "linewidth": 0.6, "linestyle": "-"})
        except Exception:  # noqa: BLE001  私有结构改名了就维持默认网格
            pass


def _quiet_mathtext_cjk_warnings(cjk) -> None:
    """压掉 mathtext 的「Font 'default' does not have a glyph」刷屏。

    STIX 等数学字体本来就没有汉字字形,只要正文字体链里有中文字体,成图上的中文
    是正常的——这条警告纯属噪声。但它一次刷几十行,智能体看见就以为图坏了:实测
    一轮里为它反复读 48KB 的 plot_style.py 四遍、又跑字体查询,花掉近两分钟,
    最后只是用 `| grep -v "^Font 'default'"` 把输出过滤掉,并没有真问题可修。
    没有中文字体时【不压】——那才是真要修的事故,必须让它看见。
    """
    if not cjk:
        return
    warnings.filterwarnings(
        "ignore", message=r"Font \(default\).*does not have a glyph")
    warnings.filterwarnings(
        "ignore", message=r"Font 'default'.*does not have a glyph")


_WEIGHT_LOG_PREFIX = "findfont: Failed to find font weight"


class _FontWeightNoise(logging.Filter):
    """挡掉 findfont 的字重告警。判重按类名而不是类对象:plot_style 会被复制进
    每个工作区、测试里也会被反复按路径加载,同一个 logger 上会挂到好几个「不同
    的」本类,按对象判重挡不住,过滤器就越叠越长。"""

    def filter(self, record) -> bool:
        return not str(getattr(record, "msg", "")).startswith(
            _WEIGHT_LOG_PREFIX)


def _quiet_font_weight_warnings() -> None:
    """压掉 `findfont: Failed to find font weight ...` 的逐行刷屏。

    matplotlib 3.10 起,请求的字重在字体里配不到对应字面时就打一行,而它按
    (字号, 字形, 字重) 组合缓存,一张图能打出十几行。中文字体缺字重是常态而非
    故障:Windows 的 SimSun 整个 simsun.ttc 没有粗体字面,加粗标题由渲染器合成,
    成图完全正常。用户对此无从下手,这些行却会把 `[数据] 训练集 …` 这类真正要看的
    输出顶出屏幕——与 _quiet_mathtext_cjk_warnings 记的是同一个教训。

    只压这一条。`findfont: Font family ... not found` 留着:那条意味着真会印成
    方块,是必须让人看见的事故。
    """
    log = logging.getLogger("matplotlib.font_manager")
    name = _FontWeightNoise.__name__
    if any(type(f).__name__ == name for f in log.filters):
        return
    log.addFilter(_FontWeightNoise())


def apply(dpi: int = 500, base_size: int = 11, palette: str | None = None,
          prefs: dict | None = None, preset: str | None = None):
    """应用科研绘图样式;返回选中的中文字体名(无则 None)。

    palette:配色风格名(见 PALETTES);缺省依次取环境变量 MS_PLOT_PALETTE、
    工程根 plot_palette.txt、默认 nature。
    prefs / preset:版式设置(字体、字号、刻度、边框、网格等,见 DEFAULT_PREFS
    与 PRESETS);缺省读工程根 plot_prefs.json——用户在技能库里选好即可,
    脚本不用改。显式传参优先级最高。
    """
    # 先于任何字体查询装好:下面的字形探测本身就会触发 findfont 的字重告警
    _quiet_font_weight_warnings()
    set_palette(palette or os.environ.get("MS_PLOT_PALETTE")
                or _palette_from_file() or _DEFAULT_PALETTE)
    merged = dict(prefs or {})
    if preset:
        merged.setdefault("preset", preset)
    p = resolve_prefs(merged)
    _ACTIVE_PREFS.clear()
    _ACTIVE_PREFS.update(p)
    cjk = _available(CJK_FAMILIES.get(p["cjk_font"], _CJK_FONTS) + _CJK_FONTS,
                     _PROBE_CJK)
    latin = _available(
        LATIN_FAMILIES.get(p["latin_font"], _SERIF_LATIN) + _SERIF_LATIN,
        _PROBE_LATIN)
    rc = matplotlib.rcParams

    # 字体:西文/数字走 Times New Roman,汉字逐字回退到宋体。
    # 老版 matplotlib 不做逐字回退,整串只认第一款字体——此时宁可西文也用宋体
    # (宋体自带西文字形,观感接近),也不能让中文糊成一片方块。
    if cjk and (_GLYPH_FALLBACK or not latin):
        family = (latin[:1] if _GLYPH_FALLBACK else []) + cjk[:2]
    else:
        family = latin[:1] or ["DejaVu Serif"]
    rc["font.family"] = family
    rc["font.serif"] = latin + cjk + rc.get("font.serif", [])
    rc["font.sans-serif"] = cjk + rc.get("font.sans-serif", [])
    rc["mathtext.fontset"] = "stix"
    rc["axes.unicode_minus"] = False        # 负号用 ASCII,避免 U+2212 缺字形
    _quiet_mathtext_cjk_warnings(cjk)
    if not cjk:
        warnings.warn(
            "未找到带中文字形的字体,图中所有中文都会渲染成方块。"
            "请安装宋体(SimSun)或 Noto Serif CJK SC 后重画。",
            RuntimeWarning, stacklevel=2)

    # 字号:以正文字号为基准联动,预设里改一个数值全图跟着变
    size = float(p["base_size"] or base_size)
    weight = "bold" if p["bold_labels"] else "normal"
    rc["font.size"] = size
    rc["axes.titlesize"] = size + 1
    rc["axes.labelsize"] = size
    rc["axes.titleweight"] = weight
    rc["axes.labelweight"] = weight
    rc["xtick.labelsize"] = size - 1
    rc["ytick.labelsize"] = size - 1
    rc["legend.fontsize"] = size - 1

    # 刻度:向内(期刊常见)/向外(教科书常见)/不显示
    ticks = p["ticks"]
    show_ticks = ticks != "none"
    rc["xtick.direction"] = ticks if show_ticks else "in"
    rc["ytick.direction"] = ticks if show_ticks else "in"
    rc["xtick.major.size"] = 5 if show_ticks else 0
    rc["ytick.major.size"] = 5 if show_ticks else 0
    rc["xtick.minor.size"] = 3 if show_ticks else 0
    rc["ytick.minor.size"] = 3 if show_ticks else 0
    minor = bool(p["minor_ticks"]) and show_ticks
    rc["xtick.minor.visible"] = minor
    rc["ytick.minor.visible"] = minor
    rc["xtick.major.width"] = 1.0
    rc["ytick.major.width"] = 1.0

    # 边框:四边 / 仅左下轴 / 无框。刻度只画在有边框的那几条轴上
    frame = p["frame"]
    rc["axes.spines.top"] = frame == "box"
    rc["axes.spines.right"] = frame == "box"
    rc["axes.spines.left"] = frame != "none"
    rc["axes.spines.bottom"] = frame != "none"
    rc["xtick.top"] = show_ticks and frame == "box"
    rc["ytick.right"] = show_ticks and frame == "box"
    rc["xtick.bottom"] = show_ticks and frame != "none"
    rc["ytick.left"] = show_ticks and frame != "none"

    rc["axes.linewidth"] = 1.0
    rc["lines.linewidth"] = float(p["line_width"])
    rc["lines.markersize"] = 5
    rc["axes.prop_cycle"] = matplotlib.cycler(color=PALETTE)

    grid = p["grid"]
    rc["axes.grid"] = grid in ("y", "both")
    rc["axes.grid.axis"] = "both" if grid == "both" else "y"
    rc["grid.linewidth"] = 0.6
    rc["grid.alpha"] = 0.3
    rc["grid.linestyle"] = "--"

    rc["legend.frameon"] = bool(p["legend_frame"])
    rc["legend.framealpha"] = 1.0
    rc["legend.edgecolor"] = "0.2"
    rc["legend.fancybox"] = False

    # 默认按单面板的满栏尺寸出图(见 FIG_W_IN):画多大排多大,缩放比 1:1,
    # 图内 10~11pt 的字排进正文就是 10~11pt,比正文 12pt 小一号,正好。
    # 缺省档从窄图 4.4 提到 5.8:没传 figsize 的脚本原来排出来只有 11.2cm,
    # 右边白掉近三成版心——版面本就不够用,不该靠脚本自觉才填得满。
    rc["figure.figsize"] = figsize("wide")
    rc["figure.dpi"] = 120
    rc["savefig.dpi"] = max(int(p["dpi"] or dpi), 150)
    rc["savefig.bbox"] = "tight"          # 伸到画布外的标签也不会被裁掉
    rc["savefig.pad_inches"] = 0.05

    # 防遮挡:约束布局会自动给标题/轴标签/刻度/图例/颜色条留位,
    # 多子图也不会互相压住。脚本里再调 tight_layout() 也不冲突(退化为紧凑布局)。
    rc["figure.constrained_layout.use"] = True
    rc["figure.constrained_layout.h_pad"] = 0.08
    rc["figure.constrained_layout.w_pad"] = 0.08
    rc["figure.constrained_layout.hspace"] = 0.06
    rc["figure.constrained_layout.wspace"] = 0.06
    _install_savefig_guard()

    return cjk[0] if cjk else None


def _legend_ncols(labels, requested=None) -> int:
    if requested is not None:
        return max(1, int(requested))
    count = len(labels)
    # 短标签（SO2/PM10/O3 等）优先单行排满。固定最多 4 列会把 5~6 个短标签
    # 硬拆成两行，图例反而比坐标区还高，典型结果是「大图例、小数据」。
    if count <= 6 and all(len(str(label)) <= 8 for label in labels):
        return max(1, count)
    return max(1, min(4, count))


def _legend_entries(ax):
    """优先读取当前图例，保留代理色块和人工筛选过的条目。"""
    old = ax.get_legend()
    if old is not None:
        labels = [text.get_text() for text in old.get_texts()]
        handles = list(getattr(
            old, "legend_handles", getattr(old, "legendHandles", ())))
        if labels and len(handles) == len(labels):
            return handles, labels
    return ax.get_legend_handles_labels()


def legend_outside(ax, *, loc=None, bbox=None, ncol=None, **kw):
    """单面板图例放在整图顶部；显式传 loc/bbox 时仍可自定图外位置。"""
    if loc is None and bbox is None:
        return figure_legend_above(ax.get_figure(), [ax], ncol=ncol, **kw)

    handles, labels = _legend_entries(ax)
    if "ncols" not in kw and "ncol" not in kw:
        kw["ncols"] = _legend_ncols(labels, ncol)
    return ax.legend(
        handles, labels, loc=loc or "upper left", bbox_to_anchor=bbox,
        borderaxespad=0.0, **kw)


def figure_legend_above(fig, axes=None, *, ncol=None, **kw):
    """把多面板的重复图例合并为整图顶部的一套横排图例。

    Matplotlib 3.10 的 ``outside upper center`` 会与 constrained layout
    协同为图例留出上边距，不压子图标题，也不会靠 ``bbox_inches`` 硬撑出空白。
    """
    if axes is None:
        flat = [ax for ax in fig.get_axes()
                if ax.get_label() != "<colorbar>"]
    elif hasattr(axes, "get_legend_handles_labels"):
        flat = [axes]
    elif hasattr(axes, "flat"):
        flat = list(axes.flat)
    else:
        flat = list(axes)

    handles, labels, seen = [], [], set()
    for ax in flat:
        hs, ls = _legend_entries(ax)
        for handle, label in zip(hs, ls):
            if not label or label.startswith("_") or label in seen:
                continue
            seen.add(label)
            handles.append(handle)
            labels.append(label)
    if not handles:
        return None

    for old in list(getattr(fig, "legends", ())):
        old.remove()
    for ax in flat:
        old = ax.get_legend()
        if old is not None:
            old.remove()

    if "ncols" not in kw and "ncol" not in kw:
        kw["ncols"] = _legend_ncols(labels, ncol)
    kw.setdefault("loc", "outside upper center")
    # 图外图例本身已有留白分区，不再套醒目的矩形框；同时收紧横向间距，
    # 避免图例喧宾夺主、把真实坐标区挤成一小块。
    kw.setdefault("frameon", False)
    kw.setdefault("columnspacing", 1.1)
    kw.setdefault("handlelength", 1.8)
    kw.setdefault("handletextpad", 0.45)
    kw.setdefault("labelspacing", 0.45)
    kw.setdefault("borderaxespad", 0.2)
    return fig.legend(handles, labels, **kw)


def _renderer(fig):
    # 必须先把布局跑完再测量:约束布局会改变坐标区大小,拿没排版前的旧坐标
    # 判断「标注在不在框内」,会把文字挪到错误的方向(典型表现是压住标题)。
    try:
        fig.draw_without_rendering()
    except Exception:           # noqa: BLE001  老版本没有这个方法
        pass
    try:
        return fig.canvas.get_renderer()
    except AttributeError:      # 个别后端没有 get_renderer
        try:
            fig.canvas.draw()
            return fig.canvas.get_renderer()
        except Exception:       # noqa: BLE001
            return None


def pull_annotations_inside(ax, renderer=None) -> int:
    """把跑到坐标区外的 annotate 文字拉回数据点旁边,返回纠正条数。

    `annotate` 的 xytext 若按数据坐标随手给个远处的值,文字会飘到坐标区外老远;
    再叠加 `bbox_inches="tight"`,保存时画布会被撑大到把它包进来——成图就是
    一大片空白配一根长箭头,真正的子图被压到角落。这里统一改成「相对数据点的
    小偏移」,既不遮挡数据,也不会把画布撑爆。
    """
    from matplotlib.text import Annotation
    renderer = renderer or _renderer(ax.get_figure())
    if renderer is None:
        return 0
    try:
        box = ax.get_window_extent(renderer)
    except Exception:  # noqa: BLE001
        return 0
    allowed = box.expanded(1.12, 1.12)     # 稍微出界一点不算问题
    fixed = 0
    for ann in list(ax.texts):
        if not isinstance(ann, Annotation) or not ann.get_text():
            continue
        try:
            tb = ann.get_window_extent(renderer)
            if (allowed.x0 <= tb.x0 and tb.x1 <= allowed.x1
                    and allowed.y0 <= tb.y0 and tb.y1 <= allowed.y1):
                continue
            # 按锚点在坐标区里的位置决定往哪偏,避免又顶到边框上
            px, py = ax.transData.transform(ann.xy)
            fx = (px - box.x0) / max(box.width, 1e-9)
            fy = (py - box.y0) / max(box.height, 1e-9)
            dx, ha = (14, "left") if fx < 0.6 else (-14, "right")
            dy, va = (14, "bottom") if fy < 0.6 else (-14, "top")
            ann.set_anncoords("offset points")
            ann.set_position((dx, dy))
            ann.set_ha(ha)
            ann.set_va(va)
            fixed += 1
        except Exception:  # noqa: BLE001  纠正失败就保持原样,不能连累出图
            continue
    return fixed


def strip_titles(fig, mode: str = "none") -> int:
    """按设置去掉图内标题,返回清掉的条数。

    论文里图题写在正文「图 4.1 …」那一行,图内再顶一个标题就是重复,还白占版面。
    mode:sup 只去总标题(保留 (a)(b) 子图名) / none 连子图标题一起去掉。

    去标题时 **(a)(b) 标号要留下来**:标题是装饰,标号是正文「见图 3.1(b)」的
    锚点,一起抹掉读者就对不上格了。而且抹掉之后 auto_panel_labels 会发现「这图
    没标号」,再自己插一套——作者只标了一格的排布意图就被覆盖成整套重编。
    """
    if mode not in ("sup", "none"):
        return 0
    dropped = 0
    sup = getattr(fig, "_suptitle", None)
    if sup is not None and sup.get_text():
        sup.set_text("")
        dropped += 1
    if mode == "none":
        for ax in fig.get_axes():
            title = ax.get_title()
            if not title:
                continue
            ax.set_title("")
            dropped += 1
            tag = _panel_tag_prefix(title)
            if tag and not _panel_tagged(ax):
                ax.set_title(tag, loc="left", fontsize=11, fontweight="bold")
    return dropped


def _xtick_labels_overlap(ax, renderer) -> bool:
    """按真实像素宽度判断相邻横轴标签是否相撞。

    只判水平标签。斜排的文字沿对角线错开、肉眼分得清,但它的包围盒仍是那个又宽又高
    的矩形,拿来判相交必然全中——斜排恰恰是 tidy() 给出的解法,再判它重叠就成了
    「照着建议改完还是硬伤」,模型无路可走。
    """
    if renderer is None:
        return False
    boxes = []
    for text in ax.get_xticklabels():
        if not text.get_visible() or not text.get_text():
            continue
        if abs(float(text.get_rotation() or 0.0)) > 1.0:
            return False
        try:
            boxes.append(text.get_window_extent(renderer))
        except Exception:  # noqa: BLE001
            return True
    boxes.sort(key=lambda box: box.x0)
    return any(left.x1 + 3 > right.x0
               for left, right in zip(boxes, boxes[1:]))


def panel_axes(axes) -> list:
    """只留真正的面板:去掉颜色条,也去掉插图轴(放大镜/小地图)。

    `ax.inset_axes()` 画出来的插图不在 `fig.get_axes()` 里,天然照不到;但
    `axes_grid1.inset_locator.inset_axes()` 会进去,不滤掉的话一张带放大镜的图会被
    当成两个面板——既要被追着标 (a)(b),自动补号还会往放大镜上扣一个 (b)。
    这类轴都带 axes_locator,颜色条也是。
    """
    return [ax for ax in axes
            if ax.get_label() != "<colorbar>" and ax.get_axes_locator() is None]


def _panel_groups(axes) -> dict:
    """按位置把 axes 归成「面板」:twinx 的第二根轴与主轴完全重合,算同一格。"""
    groups: dict = {}
    for ax in panel_axes(axes):
        key = tuple(round(float(v), 3) for v in ax.get_position().bounds)
        groups.setdefault(key, []).append(ax)
    return groups


def auto_panel_labels(fig, axes) -> bool:
    """多面板没标 (a)(b)(c) 就自动补上;补过返回 True。

    实测:两个真实会话的多面板图无一例外都没标号——契约里写着「收尾加
    panel_labels(axes)」、体检也逐张报提醒,照样每一张都缺。**能在存图时确定性补上
    的事,就不该反复写进提示词再指望模型自觉**:提示词位置有限,得留给代码判不了的。
    已经手工标过的图一律不碰(哪怕只标了一格,那也是作者的排布意图)。
    发号按阅读顺序:先上后下、再左到右,与正文引用「图X(b)」的习惯一致。
    """
    groups = _panel_groups(axes)
    if len(groups) < 2:
        return False
    for members in groups.values():
        if any(_panel_tagged(ax) for ax in members):
            return False
    import string
    order = sorted(groups, key=lambda b: (-round(b[1] + b[3], 3), b[0]))
    labels = [f"({c})" for c in string.ascii_lowercase[:len(order)]]
    panel_labels([groups[key][0] for key in order], labels)
    return True


# 标签里只要出现一对 $…$，matplotlib 会把【整句】交给 mathtext(STIX)。
# STIX 没有汉字,外面的「推重比」「无量纲」一样印成 ¤——实测 adad-5fd1c5 的
# problem1_comparison.png:「推重比 $T/W_0$ (无量纲)」画成「¤¤¤ T/W_0 (¤¤¤)」。
# 闸门一度只查 $ 里面有没有汉字,这种写法查不到,issues 是空的。
_LATEX_MACROS = (
    (r"\Delta", "Δ"), (r"\delta", "δ"), (r"\lambda", "λ"), (r"\Lambda", "Λ"),
    (r"\alpha", "α"), (r"\beta", "β"), (r"\gamma", "γ"), (r"\Gamma", "Γ"),
    (r"\theta", "θ"), (r"\Theta", "Θ"), (r"\mu", "μ"), (r"\pi", "π"),
    (r"\sigma", "σ"), (r"\Sigma", "Σ"), (r"\omega", "ω"), (r"\Omega", "Ω"),
    (r"\phi", "φ"), (r"\varphi", "φ"), (r"\psi", "ψ"), (r"\rho", "ρ"),
    (r"\epsilon", "ε"), (r"\varepsilon", "ε"), (r"\eta", "η"),
    (r"\kappa", "κ"), (r"\nu", "ν"), (r"\tau", "τ"), (r"\chi", "χ"),
    (r"\xi", "ξ"), (r"\zeta", "ζ"), (r"\Phi", "Φ"), (r"\Psi", "Ψ"),
    (r"\Pi", "Π"), (r"\times", "×"), (r"\cdot", "·"), (r"\pm", "±"),
    (r"\approx", "≈"), (r"\leq", "≤"), (r"\geq", "≥"), (r"\neq", "≠"),
    (r"\infty", "∞"), (r"\partial", "∂"), (r"\sum", "Σ"),
    (r"\,", " "), (r"\;", " "), (r"\!", ""),
)
_LATEX_WRAP = (
    r"\mathrm", r"\mathbf", r"\mathit", r"\mathsf", r"\mathtt",
    r"\text", r"\textrm", r"\textbf", r"\textit",
)
def _unwrap_latex_groups(s: str) -> str:
    for name in _LATEX_WRAP:
        s = re.sub(re.escape(name) + r"\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", s)
    s = re.sub(r"_\{([^{}]+)\}", r"_\1", s)
    s = re.sub(r"\^\{([^{}]+)\}", r"^\1", s)
    return s


# 拆掉 $ 之后下标只剩一根下划线:「阻力系数 $C_D$」印出来是「阻力系数 C_D」,
# 评委看到的就是一根下划线。Unicode 有现成的上下标字形,能画就换成真下标。
# 但字体栈里未必有——实测 Times New Roman + Songti SC 一个 ₀ 都画不出,
# 画不出还硬换会印成方块,比下划线更糟。所以逐字确认字体画得出才换。
_SUB_MAP = str.maketrans("0123456789+-=()aeiouvxhklmnprst",
                         "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵤᵥₓₕₖₗₘₙₚᵣₛₜ")
_SUP_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SCRIPT_BODY_RE = r"([A-Za-z0-9+\-=]+)"


def _to_unicode_script(body: str, table: dict) -> str:
    """下标/上标内容转 Unicode 字形。有一个字转不了或画不出就整体放弃。

    整体放弃是有意的:`C_max` 只转出「C_mₐₓ」比原样留着更难读。
    """
    if not body:
        return ""
    out = body.translate(table)
    if any(ord(ch) < 0x80 for ch in out):
        return ""               # 有字符没有对应的上下标字形
    try:
        stack = _font_stack()
        if not stack or not all(
                any(_font_can_draw(f, ch) for f in stack) for ch in out):
            return ""
    except Exception:  # noqa: BLE001  字体探测失败就维持原样,绝不画成方块
        return ""
    return out


def _restore_scripts(s: str) -> str:
    """把 `X_0`、`X^2` 这类明文上下标还原成 Unicode 上下标。"""
    def _one(table):
        def _repl(m):
            return _to_unicode_script(m.group(1), table) or m.group(0)
        return _repl
    s = re.sub(r"_" + _SCRIPT_BODY_RE, _one(_SUB_MAP), s)
    return re.sub(r"\^" + _SCRIPT_BODY_RE, _one(_SUP_MAP), s)


def demath_cjk_label(text: str) -> str:
    """含汉字又含 $ 的标签:拆掉数学模式,公式改成 Unicode,汉字回到正文字体。

    不含汉字的纯公式(如 $E=mc^2$)原样留下,该走 mathtext 的还走。
    """
    s = text or ""
    if not _CJK_CHAR_RE.search(s) or "$" not in s:
        return s
    s = _unwrap_latex_groups(s)
    for a, b in _LATEX_MACROS:
        s = s.replace(a, b)
    parts, last = [], 0
    for m in _MATH_SPAN_RE.finditer(s):
        parts.append(s[last:m.start()])
        parts.append(m.group(1))
        last = m.end()
    parts.append(s[last:])
    out = "".join(parts).replace("$", "")
    out = re.sub(r"\{([^{}]*)\}", r"\1", out)
    out = _restore_scripts(out)
    return re.sub(r" {2,}", " ", out).strip()


def unmath_cjk_texts(fig) -> int:
    """存图前把「汉字+$」标签改成可印的明文,返回改动条数。"""
    n = 0
    for t in _visible_text_objects(fig):
        raw = t.get_text() or ""
        fixed = demath_cjk_label(raw)
        if fixed == raw:
            continue
        t.set_text(fixed)
        if hasattr(t, "set_parse_math"):
            t.set_parse_math(False)
        n += 1
    return n


def drop_axis_offset(axes) -> None:
    """关掉坐标轴的偏移记号(轴角那个「+2.477e1」)。

    实测事故:压比在 24.7786~24.7793 之间变化,matplotlib 把公共部分提成
    「+2.477e1」挂在轴角,刻度只剩 0.0080、0.0082——读者既读不出这条曲线到底是多少,
    也看不出它其实几乎不动。关掉之后刻度写全,那条「几乎不变」的曲线也就原形毕露,
    交给 near_flat_line 判。只动线性轴:对数轴的指数刻度是正当写法。
    """
    for ax in axes:
        for axis, scale in ((ax.xaxis, ax.get_xscale()),
                            (ax.yaxis, ax.get_yscale())):
            if scale != "linear":
                continue
            fmt = axis.get_major_formatter()
            if not hasattr(fmt, "set_useOffset"):
                continue          # 分类轴/自定义 formatter 没有这个开关
            try:
                fmt.set_useOffset(False)
            except Exception:  # noqa: BLE001  收尾保护绝不能连累存图
                continue


def tidy(fig=None, *, rotate: float = 30.0, max_chars: int = 4):
    """收尾防遮挡:清标题、拉回标注、斜排长标签、拥挤图例统一置顶。"""
    import matplotlib.pyplot as plt
    fig = fig or plt.gcf()
    strip_titles(fig, str(_ACTIVE_PREFS.get("title") or "keep"))
    renderer = _renderer(fig)
    axes = [ax for ax in fig.get_axes() if ax.get_label() != "<colorbar>"]
    drop_axis_offset(axes)
    dress_bare_lines(axes)
    unmath_cjk_texts(fig)
    auto_panel_labels(fig, axes)
    crowded_legends = [
        ax for ax in axes if _legend_covers_content(ax, renderer)]
    if crowded_legends:
        if len(axes) > 1:
            figure_legend_above(fig, axes)
        else:
            legend_outside(crowded_legends[0])
    for ax in axes:
        pull_annotations_inside(ax, renderer)
        labels = [t.get_text() for t in ax.get_xticklabels()]
        if len(labels) < 2 or not any(len(s) > max_chars for s in labels):
            continue
        # 字符数只是候选条件；像 08-25 这种四个短日期实际完全放得下，
        # 不应仅因长度为 5 就统一斜排。
        if not _xtick_labels_overlap(ax, renderer):
            continue
        for t in ax.get_xticklabels():
            t.set_rotation(rotate)
            t.set_ha("right")
            t.set_rotation_mode("anchor")
    return fig


_BARE_MARKERS = ("None", "none", "")
_DRESS_MAX_POINTS = 80
_DRESS_MARKERS = ("o", "s", "^", "D")


def dress_bare_lines(axes) -> int:
    """给没打点的折线补 marker。

    模型很少写 ``series_style``,存出来就是一根细线飘在空白坐标里,结果图显得素。
    存图收尾确定性补点:已经有 marker 的不碰,点太密(>80)会糊成粗线也不补。
    """
    n = 0
    for ax in panel_axes(axes):
        box_ids = {id(box) for box in _boxplot_boxes(ax)}
        for i, ln in enumerate(ax.lines):
            if id(ln) in box_ids:
                continue          # 默认箱线图的箱体也是 5 点 Line2D,不能补成一圈圆点
            pts = _npoints(ln)
            if pts < 3 or pts > _DRESS_MAX_POINTS:
                continue
            if str(ln.get_marker() or "None") not in _BARE_MARKERS:
                continue
            ln.set_marker(_DRESS_MARKERS[i % len(_DRESS_MARKERS)])
            ln.set_markevery(max(1, pts // 8) if pts > 12 else 1)
            ln.set_markersize(4.5)
            ln.set_markeredgecolor("white")
            ln.set_markeredgewidth(0.4)
            n += 1
    return n


# ------------------------------------------------------------------ 图面自检
# 智能体看不见自己画出来的图:压字、空面板、平线、双轴柱这类毛病,靠提示词里写
# 「存完图打开看一眼」是空转的。改为存图时就地体检,把问题写进
# figures/_figure_lint.json,再由 check_figures.py 汇总成闸门——
# 图面规范由代码判定,不依赖模型记忆。

_LINT_FILE = "_figure_lint.json"
_BAD_CMAPS = {"jet", "rainbow", "hsv", "nipy_spectral", "gist_rainbow"}
# 纵轴写成这些词等于没写单位:多指标混在一根轴上时,读者无法判断可比性
_VAGUE_YLABELS = {"", "数值", "指标值", "值", "指标", "大小", "value", "values"}
_UNIT_RE = re.compile(r"[（(]([^)）]{1,12})[)）]")
_LINTED_STEMS: set = set()      # 同一张图的 png/pdf/svg 只提示一次
_MAG_SPAN_MIN = 2.0     # 同轴量值跨多少个十进位才可疑
_MAG_GAP_MIN = 1.5      # 两簇之间的断层:达到这么多个十进位才算「小的被压平」
_LEGEND_HIDE_MIN = 0.25  # 单条曲线被图例盖掉这么多长度才算遮挡
_SEG_SAMPLES = 8        # 线段与图例框求交时的采样点数


def _npoints(line) -> int:
    try:
        return len(line.get_xdata())
    except Exception:  # noqa: BLE001
        return 0


def _overlap_ratio(a, b) -> float:
    """两个包围盒的重叠面积占较小者的比例。"""
    if a is None or b is None:
        return 0.0
    x0, x1 = max(a.x0, b.x0), min(a.x1, b.x1)
    y0, y1 = max(a.y0, b.y0), min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    small = min(abs(a.width * a.height), abs(b.width * b.height))
    return ((x1 - x0) * (y1 - y0)) / small if small > 0 else 0.0


def _legend_covers_content(ax, renderer) -> bool:
    """图例是否盖住数据点、柱体或正文标注。图外图例自然返回 False。"""
    leg = ax.get_legend()
    if leg is None or renderer is None:
        return False
    try:
        lb = leg.get_window_extent(renderer)
    except Exception:  # noqa: BLE001
        return False

    for text in ax.texts:
        if not text.get_text().strip():
            continue
        try:
            if _overlap_ratio(lb, text.get_window_extent(renderer)) > 0.2:
                return True
        except Exception:  # noqa: BLE001
            continue

    inside = total = 0
    for line in ax.lines:
        if _npoints(line) < 3:
            continue
        try:
            points = ax.transData.transform(line.get_xydata())
        except Exception:  # noqa: BLE001
            continue
        for px, py in points:
            total += 1
            if lb.x0 <= px <= lb.x1 and lb.y0 <= py <= lb.y1:
                inside += 1
    if total and inside / total > 0.05:
        return True

    for patch in ax.patches:
        try:
            if _overlap_ratio(lb, patch.get_window_extent(renderer)) > 0.2:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _legend_hides_series(ax, renderer) -> list:
    """图例盖掉了整整一段曲线。

    上面的 _legend_covers_content 按「全图顶点落在图例框内的比例」判,阈值 5%:
    一条 8 点折线被盖掉中间一段只贡献 1/24≈4%,恰好漏过去(实测 problem3.png 的
    1D-CNN 曲线在图例后消失了一整段却静默通过)。这里改按【单条曲线】被遮住的
    路径长度占比判,盖掉四分之一就算遮挡。
    """
    leg = ax.get_legend()
    if leg is None or renderer is None:
        return []
    try:
        lb = leg.get_window_extent(renderer)
    except Exception:  # noqa: BLE001
        return []
    for line in ax.lines:
        if _npoints(line) < 3:
            continue
        try:
            pts = ax.transData.transform(line.get_xydata())
        except Exception:  # noqa: BLE001
            continue
        total = hidden = 0.0
        for i in range(len(pts) - 1):
            x0, y0 = float(pts[i][0]), float(pts[i][1])
            x1, y1 = float(pts[i + 1][0]), float(pts[i + 1][1])
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg <= 0 or seg != seg:
                continue
            total += seg
            inside = sum(
                1 for k in range(_SEG_SAMPLES)
                if (lb.x0 <= x0 + (x1 - x0) * (k + 0.5) / _SEG_SAMPLES <= lb.x1
                    and lb.y0 <= y0 + (y1 - y0) * (k + 0.5) / _SEG_SAMPLES
                    <= lb.y1))
            hidden += seg * inside / _SEG_SAMPLES
        if total > 0 and hidden / total >= _LEGEND_HIDE_MIN:
            lab = line.get_label() or ""
            name = lab if lab and not lab.startswith("_") else "某条曲线"
            return [(
                "error", "legend_hides_series",
                f"图例盖住了曲线「{name}」约 {hidden / total:.0%} 的长度,"
                "读者看不到那一段;单面板用 plot_style.legend_outside(ax),"
                "多面板用 plot_style.figure_legend_above(fig, axes)")]
    return []


def _boxplot_boxes(ax) -> list:
    """箱线图的箱体。patch_artist=True 时是 PathPatch,默认样式是首尾闭合的 5 点折线。"""
    from matplotlib.patches import PathPatch

    boxes = [p for p in ax.patches if isinstance(p, PathPatch)]
    for ln in ax.lines:
        try:
            xy = ln.get_xydata()
            closed = (len(xy) == 5
                      and abs(float(xy[0][0]) - float(xy[4][0])) < 1e-9
                      and abs(float(xy[0][1]) - float(xy[4][1])) < 1e-9)
        except Exception:  # noqa: BLE001
            continue
        if closed:
            boxes.append(ln)
    return boxes


def _plotted_magnitudes(ax) -> list:
    """本坐标区画出来的纵向量值(取绝对值,去掉 0/NaN)。

    柱取柱高、箱取箱体中位、线与散点取 y。用画出来的几何量而不是解析轴标签:
    指标名常常只写在图例里,刻度上是模型名,从标签解析不出量纲。
    """
    from matplotlib.patches import Rectangle

    vals: list = []
    for p in ax.patches:
        if isinstance(p, Rectangle):
            try:
                vals.append(float(p.get_height()))
            except (TypeError, ValueError):
                continue
    for box in _boxplot_boxes(ax):
        try:
            ys = [float(v) for v in box.get_path().vertices[:, 1]]
        except Exception:  # noqa: BLE001
            continue
        if ys:
            vals.append(sum(ys) / len(ys))
    for ln in ax.lines:
        try:
            vals.extend(float(v) for v in ln.get_ydata())
        except (TypeError, ValueError):
            continue
    for coll in ax.collections:
        try:
            vals.extend(float(v) for v in coll.get_offsets()[:, 1])
        except Exception:  # noqa: BLE001
            continue
    return [abs(v) for v in vals
            if v == v and abs(v) != float("inf") and v != 0]


def _lint_magnitude_gap(ax) -> list:
    """同一根纵轴上混了差两个数量级以上的两簇量:小的那簇被压成一条平线。

    实测事故:RMSE(42)、MAE(28) 与 NASA 评分 S(85000) 挤在一根「指标值」轴上,
    前两者的箱体全部退化成 y=0 附近的一道横线,正文却还在描述它们的中位数差异。
    mixed_units 查不出来——它从 x 刻度标签解析单位,而指标名写在图例里。
    """
    if ax.images or ax.get_yscale() != "linear":
        return []          # 热图不吃纵轴;对数轴本就是为跨数量级准备的
    mags = sorted(_plotted_magnitudes(ax))
    if len(mags) < 4:
        return []
    logs = [math.log10(v) for v in mags]
    if logs[-1] - logs[0] < _MAG_SPAN_MIN:
        return []
    gap, cut = 0.0, 0
    for i in range(len(logs) - 1):
        if logs[i + 1] - logs[i] > gap:
            gap, cut = logs[i + 1] - logs[i], i
    if gap < _MAG_GAP_MIN:
        return []          # 连续铺开的宽量程(时序 0.01→100)没有断层,不算
    low = {round(v, 6) for v in mags[:cut + 1]}
    high = {round(v, 6) for v in mags[cut + 1:]}
    if len(low) < 2 or len(high) < 2:
        return []          # 一侧只剩一个孤立值:那是离群点,不是两组不可比的量
    return [(
        "error", "mixed_magnitude",
        f"同一根纵轴上混了相差 {gap:.1f} 个数量级的两组量"
        f"(约 {min(high):.3g}~{max(high):.3g} 与 {min(low):.3g}~{max(low):.3g}),"
        "小的那组会被压成一条平线,读者读不出任何差异;"
        "归一化成「相对基线倍数」后在柱顶标 ±%,或拆成各自带单位的独立面板")]


def _lint_box_without_points(ax) -> list:
    """箱线图没有叠原始数据点:样本一少,四分位和上下须全是虚构出来的分布。

    实测事故:两个随机种子的结果画成箱线图,箱体、中位线、上下须一应俱全,
    读者会当成一个分布来读——其实只有 2 个点。
    """
    boxes = _boxplot_boxes(ax)
    if not boxes or ax.collections:
        return []
    return [(
        "error", "box_without_points",
        f"{len(boxes)} 个箱体没有叠原始数据点:样本少时箱线图的四分位与上下须"
        "并不代表真实分布;用 ax.scatter 把每个样本点叠在箱体上"
        "(重复次数少于 5 时直接画点,不要画箱)")]


def _has_errorbar(ax) -> bool:
    """图上有没有误差棒。

    只查 `.errorbar` 属性会漏掉最常用的写法:ax.bar(yerr=) 把误差棒挂在
    BarContainer.errorbar 上,而直接调 ax.errorbar() 得到的 ErrorbarContainer
    【自己没有 .errorbar 属性】,一路漏检到指纹里写成「没画不确定性」。
    """
    from matplotlib.container import ErrorbarContainer

    for c in (getattr(ax, "containers", None) or []):
        if isinstance(c, ErrorbarContainer) or getattr(c, "errorbar", None):
            return True
    return False


def _has_uncertainty(ax) -> bool:
    """图上是否显式画了不确定性:误差棒、区间带/小提琴、箱体。

    hexbin 也是 PolyCollection,但它一个格子一个 offset(实测 46 个);
    fill_between/violinplot 的带子是整块多边形,offsets 只有 1 个——
    用 offsets 个数区分,别把密度图当成区间带。
    """
    from matplotlib.collections import PolyCollection

    if _has_errorbar(ax):
        return True
    for coll in ax.collections:
        if not isinstance(coll, PolyCollection):
            continue
        try:
            if len(coll.get_offsets()) <= 1:
                return True
        except Exception:  # noqa: BLE001
            continue
    return bool(_boxplot_boxes(ax))


def _is_flat(line) -> bool:
    """一条曲线是否完全没有起伏(画出来是条直线,等于没有信息)。"""
    try:
        ys = [float(v) for v in line.get_ydata()]
    except (TypeError, ValueError):
        return False
    ys = [v for v in ys if v == v]                 # 去掉 NaN
    if len(ys) < 3:
        return False
    span, scale = max(ys) - min(ys), max(abs(v) for v in ys) or 1.0
    return span / scale < 1e-9


def _ydata(artist) -> list:
    """一条线上的纵坐标(取不出数就当空)。"""
    try:
        ys = [float(v) for v in artist.get_ydata()]
    except (TypeError, ValueError):
        return []
    return [v for v in ys if v == v]


# 变化幅度不到自身量级的千分之一:刻度得写到五六位有效数字才分得出高低。
# 阈值一度定在 1%,太松——温度 300.0→300.5 K 这类正当结果(相对 0.17%)会被误伤,
# 而 matplotlib 本来就会自动缩放纵轴,0.17% 的起伏在图上看得清清楚楚。
_NEAR_FLAT_REL = 1e-3


def _rel_span(ys: list) -> float:
    if len(ys) < 3:
        return 1.0
    return (max(ys) - min(ys)) / (max(abs(v) for v in ys) or 1.0)


def _near_flat_issues(ax, lines) -> list:
    """面板里的曲线全都几乎不动:轴上写着数,图上讲不出任何变化。

    实测事故:一张收敛过程图的「压比」面板,数据在 24.7786~24.7793 之间,
    相对变化三十万分之一,matplotlib 把公共部分提成轴角的「+2.477e1」,
    于是刻度看着从 0.0080 走到 0.0086、像是有变化,其实压比全程没动。
    完全水平的线由 flat_line 判(那条更硬),这里补的是「肉眼看不出在动」的那档。
    只有本面板【所有】曲线都近似平的才报:真曲线旁边配一条水平基准线是正当画法。
    """
    if not lines:
        return []
    rels = []
    for ln in lines:
        ys = _ydata(ln)
        if len(ys) < 3:
            return []          # 取不到数就不判,宁可漏报
        rels.append(_rel_span(ys))
    if max(rels) >= _NEAR_FLAT_REL:
        return []
    if len(lines) == 1:
        ys = _ydata(lines[0])
        who = (f"唯一那条曲线只在 {min(ys):.6g}~{max(ys):.6g} 之间动"
               f"(相对幅度 {rels[0] * 100:.2g}%)")
    else:
        who = (f"{len(lines)} 条曲线的相对变化幅度都不到 "
               f"{_NEAR_FLAT_REL:.1%}(最大 {max(rels) * 100:.2g}%)")
    return [("error", "near_flat_line",
             f"{who},刻度得写到五六位有效数字才分得出高低,"
             "读者读不出这是真变化还是数值噪声:改画相对基线的变化量"
             "(y=(v-v₀)/v₀×100,轴标写「相对基线变化 / %」),把变化幅度本身讲清楚;"
             "若结论就是「该量在这个范围内不变」,写成一句话或表格一行,"
             "不要占一个面板")]


# 参考线把量程撑开这么多倍(对数轴按十进位算),数据就被压成一条线了
_BLOWN_LINEAR = 10.0
_BLOWN_DECADES = 2.0


def _blown_range_issues(ax) -> list:
    """一条参考线把纵轴撑开,真正的数据被压成顶上一条直线。

    实测事故:收敛曲线图上画了 `axhline(1e-6)` 当收敛判据,而梯度范数本身在
    10~20 之间,对数轴被撑到七个数量级——读者看到的是贴着顶边的一条平线,
    「梯度在下降」这个本要展示的结论一点都没展示出来。
    「谁是参考线」按 **transform** 认:`axhline` 画出来的线横向用轴坐标、纵向用
    数据坐标,这个混合变换是它独有的签名。一度改按「两点且 y 恒定」去认,踩了两个
    坑:`axvline` 的 ydata 是 [0,1] 轴坐标,被当成「画在 0 的水平线」——实测一张概率
    密度图(密度值 1e-8 量级)因此报了条根本不存在的撑爆量程;箱线图的须帽与中位线
    同样是两点恒定线,配一条均值曲线就会凑出误报。

    量程要跟【面板里所有画了的东西】比,不能只跟曲线比:柱子把纵轴拉到 0~100、
    曲线只在 50~52 的图,量程是柱子撑的,与参考线无关。
    """
    from matplotlib.patches import Rectangle

    yt = ax.get_yaxis_transform()
    data, refs = [], []
    for ln in ax.lines:
        ys = _ydata(ln)
        if not ys:
            continue
        if ln.get_transform() == yt:
            refs.append((ln, ys))
        elif len(ys) >= 3:
            data.append((ln, ys))
    if not data or not refs:
        return []
    spans = [v for _, ys in data for v in (min(ys), max(ys))]
    for p in ax.patches:
        if isinstance(p, Rectangle):
            spans += [p.get_y(), p.get_y() + p.get_height()]
    for coll in ax.collections:
        try:
            spans += [float(o[1]) for o in coll.get_offsets()]
        except (TypeError, ValueError, IndexError):
            continue
    spans = [v for v in spans if v == v]
    dlo, dhi = min(spans), max(spans)
    lo, hi = (float(v) for v in ax.get_ylim())
    if not (hi > lo):
        return []
    log = ax.get_yscale() == "log"
    if log:
        if min(dlo, lo) <= 0:
            return []
        blown = (math.log10(hi / lo) - math.log10(max(dhi, dlo * 1.0000001)
                                                 / dlo)) >= _BLOWN_DECADES
    else:
        dspan = dhi - dlo
        blown = dspan > 0 and (hi - lo) / dspan >= _BLOWN_LINEAR
    if not blown:
        return []
    outside = [(ln, ys) for ln, ys in refs
               if max(ys) > dhi or min(ys) < dlo]
    if not outside:
        return []
    ln, ys = outside[0]
    lab = (ln.get_label() or "").lstrip("_") or "参考线"
    return [("error", "blown_range",
             f"参考线「{lab}」画在 {ys[0]:.3g},数据本身只在 {dlo:.3g}~{dhi:.3g} 之间,"
             f"纵轴被它撑开之后真正的曲线被压成贴边的一条直线,这张图想讲的变化"
             f"一点都没讲出来:删掉这条线、改成图内一句文字标注(把「{lab}={ys[0]:.3g}、"
             f"第 N 轮达到」写在曲线旁),或改画「与它的差距」,让纵轴回到数据范围")]


def _is_3d_ax(ax) -> bool:
    return getattr(ax, "name", "") == "3d"


# 标注盖住刻度标签多少算压字。比标注互压的 0.35 略松:刻度标签本身很小,
# 稍微擦到边就会被算成高比例,阈值定太低会把排布正常的图判成硬伤。
_TICK_OVERLAP_RATIO = 0.30


def _has_surface(ax) -> bool:
    """这个 3D 面板里有没有真的画曲面。

    plot_surface / plot_trisurf 都产出 Poly3DCollection;3D 散点是
    Path3DCollection(response_surface 标最优点用的就是它),不算曲面。
    """
    return any(type(c).__name__ == "Poly3DCollection" for c in ax.collections)


def _surface_shape_issues(ax) -> list:
    """三维响应面的两条硬伤,都是实测踩出来的。

    ① **手搓 plot_surface**:3131-38beaa 的 problem2.py 明明 import 了
       ``response_surface`` 却自己开 ``projection="3d"`` 画,于是收进画框
       (set_box_aspect zoom)、稀释刻度、标最优点、压背景网格这些处理全被绕过——
       成图上 z 轴标签断成两截贴在边缘、三面密虚线网格盖过曲面、最优点是个
       看不见的半透明点,而体检判了全绿。提示词里写「双参数默认 response_surface」
       是软约束,模型 import 了都能不用,只有闸门拦得住。
    ② **曲面独占一整张图**:双参数响应面的房屋默认是「曲面 + 等高线」合成组图。
       单独一张曲面读者读不出等值线在哪、最优点落在哪个区域,得配一格平面图。
    """
    if not _has_surface(ax):
        return []
    out = []
    if not getattr(ax, "_ms_response_surface", False):
        out.append((
            "error", "handmade_surface",
            "这张三维曲面是自己开 projection=\"3d\" 手搓的,绕过了 "
            "plot_style.response_surface:立方体没收进画框(z 轴标签会顶到边缘或"
            "隔壁格)、刻度没稀释(投影后标签叠成一片)、最优点没标、背景还是三层"
            "密虚线网格。改成 "
            "`from plot_style import response_surface;"
            " response_surface(X, Y, Z, xlabel=…, ylabel=…, zlabel=…, mark=最优点)`"))
    siblings = [a for a in ax.get_figure().get_axes()
                if a is not ax and a.get_label() != "<colorbar>"]
    # 邻居必须是等高线/热图一类平面证据。任意柱图/空面板也能「有邻居」,
    # 早先只判 siblings 非空,会被无关面板糊弄过去。
    planar = [a for a in siblings if not _is_3d_ax(a) and (
        _colormapped_fills(a)
        or any("ContourSet" in type(c).__name__ for c in a.collections)
        or any(getattr(getattr(c, "cmap", None), "name", "") for c in a.collections))]
    if not planar:
        out.append((
            "error", "lonely_surface",
            "三维曲面没有配等高线/热图平面证据:读者看不出等值线走向,也读不出最优点"
            "落在哪个区域。房屋默认是曲面配平面图合成组图,照抄:"
            "`fig, axes = combo_axes(2, projections=(\"3d\", None))`,"
            "左格 `response_surface(X, Y, Z, ax=axes[0], colorbar=False, mark=最优点)`,"
            "右格用同一套网格画 `contourf` 并配 colorbar(别两格各挂一条色标);"
            "配一根无关柱图不算数"))
    return out


def _colormapped_fills(ax) -> list:
    """按色图铺满的底图图元(imshow / pcolormesh / contourf),按叠放次序。"""
    out = []
    for art in list(ax.images) + list(ax.collections):
        name = type(art).__name__
        if name in ("AxesImage", "QuadMesh", "PcolorImage"):
            out.append(art)
        elif "ContourSet" in name and getattr(art, "filled", False):
            out.append(art)
    return out


def _alpha_of(art) -> float:
    a = art.get_alpha()
    try:
        return 1.0 if a is None else float(a)
    except (TypeError, ValueError):   # 逐元素 alpha 数组,当作不透明处理
        return 1.0


# 叠在彩色底图上的填充要多不透明才看得见。0.16 的绿色可行域在 coolwarm 上完全消失。
_FAINT_FILL_ALPHA = 0.30
# 线条要同时「分量不足」且「会糊进底色」才算看不见。分量只看线宽是不够的:实测
# 新默认试画/problem2_sensitivity.png 的白色等值线只有 0.6 线宽,但它不透明,压在
# 饱和色上对比度很高,一条条清清楚楚——按纯线宽判会把这张好图判成硬伤。
# 真正让线消失的是**半透明后与底色混合**(问题图是 0.65 alpha 的蓝线压在蓝区上),
# 或者细到发丝。所以三个条件:分量不足,且(半透明 或 发丝细)。
_FAINT_LINE_WEIGHT = 0.70
_BLENDING_ALPHA = 0.85
_HAIRLINE_WIDTH = 0.45


def _faint_overlay_issues(ax) -> list:
    """彩色底图上「画了等于没画」的图元。

    实测事故:3131-38beaa/problem2_contour.png 在 coolwarm 填充上叠了
    ``contourf(..., alpha=0.16)`` 的绿色可行域和 ``linewidths=0.7, alpha=0.65``
    的风扇功耗等值线,图注郑重其事写着「绿色:热约束与风扇包络均满足」「蓝色等值线:
    风扇功耗」——成图上绿色一片都找不到,那两条等值线看着就是网格线。
    读者按图注去找,找不到,只会认为作者在编。

    只在【有彩色底图】时判:白底上 alpha 0.2 的置信带是正常画法,不能一起误伤。
    底图自己(第一层填充)也豁免——它下面是白纸,淡一点照样看得清。
    """
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    fills = _colormapped_fills(ax)
    if not fills:
        return []
    out, background = [], fills[0]
    for art in fills[1:]:
        if _alpha_of(art) < _FAINT_FILL_ALPHA:
            out.append((
                "error", "invisible_overlay",
                f"有一层填充的 alpha 只有 {_alpha_of(art):.2f},却叠在彩色底图上——"
                "底图颜色是饱和的,这层等于没画,读者一片都找不到。"
                "要么把 alpha 提到 0.35 以上并把底图调淡(contourf 的 alpha 给 0.75),"
                "要么改成画这块区域的边界线(`contour` 描边 + `clabel` 标注),"
                "别用大面积半透明色块压色块"))
            break
    def vanishing(width: float, alpha: float) -> bool:
        return (width * alpha < _FAINT_LINE_WEIGHT
                and (alpha < _BLENDING_ALPHA or width < _HAIRLINE_WIDTH))

    faint = []
    for art in ax.collections:
        if art is background or getattr(art, "filled", False):
            continue
        if isinstance(art, LineCollection) or "ContourSet" in type(art).__name__:
            # get_linewidths() 给的是 ndarray:多条等值线时 `arr or [0]` 会抛
            # 「truth value of an array is ambiguous」,而存图时的兜底会把这个异常
            # 整条吞掉——闸门于是静默失效。必须先转成 list 再判空。
            widths = [float(w) for w in list(art.get_linewidths())]
            if widths and vanishing(max(widths), _alpha_of(art)):
                faint.append(f"{max(widths):.2g}×{_alpha_of(art):.2g}")
    for ln in ax.lines:
        if _is_guide_line(ln) or _npoints(ln) < 3:
            continue
        if vanishing(float(ln.get_linewidth()), _alpha_of(ln)):
            faint.append(f"{ln.get_linewidth():.2g}×{_alpha_of(ln):.2g}")
    if faint:
        out.append((
            "error", "invisible_overlay",
            f"彩色底图上有 {len(faint)} 组线既细又半透明(线宽×不透明度 = "
            f"{faint[0]}),半透明会让线色和底色混在一起,读者只会当它是网格线。"
            "叠在填充上的线给 `linewidths=1.4, alpha=1.0`,颜色挑与底图色系对比强的"
            "(coolwarm 底图上用白色或黑色),再换一种线型和底图等值线区分开"))
    return out


# 「绿色:热约束均满足」这类写法,是在用文字块冒充图例。
# 冒号必须把全角 U+FF1A 一起收进来:中文图注里写的几乎都是全角,只放 ASCII 冒号
# 这条闸门等于没写。
_TEXT_LEGEND_RE = re.compile(
    r"[红蓝绿橙紫黄青灰黑白][色](?:实线|虚线|点线|等值线|曲线|区域|阴影|色块)?"
    r"\s*[:\uff1a]")


def _text_as_legend_issues(texts) -> list:
    """图上用文字写「某色 = 某含义」,而不是让图例给出色块。

    图例的色块是从图元本身取色的,写错不了;手写的文字块跟图元没有任何绑定,
    实测那张图写了「绿色」「蓝色」,图上一个都找不到,而体检当时全绿。
    改走图例之后,画的是什么颜色、图例就显示什么颜色,这类谎报自然消失。
    """
    hits = [t.get_text().strip() for t in texts
            if _TEXT_LEGEND_RE.search(t.get_text() or "")]
    if not hits:
        return []
    return [(
        "error", "text_legend",
        f"图上用文字块写颜色对应关系(「{hits[0][:24]}」),这是在手写图例:"
        "文字和图元没有绑定,颜色写错、或那个图元压根看不见,读者也发现不了。"
        "改成给图元加 `label=\"…\"` 再 `ax.legend()`,颜色由图元自己带出来;"
        "等值线用 `ax.clabel(cs, fmt=\"…\")` 直接标在线上")]


def _lint_axes(ax, renderer) -> list:
    """检查单个子图,返回 [(level, code, msg)]。"""
    from matplotlib.patches import Rectangle, Wedge

    out = []
    if ax.get_label() == "<colorbar>":
        return out
    # 3D 响应曲面走自己的几何,2D 的空面板/纵轴/平线规则会误伤
    if _is_3d_ax(ax):
        n_data = (len(ax.lines) + len(ax.patches) + len(ax.collections)
                  + len(ax.images))
        if n_data == 0:
            out.append(("error", "empty_panel",
                        "空面板,请删掉或补上数据"))
            return out
        for coll in list(ax.collections) + list(ax.images):
            cmap = getattr(getattr(coll, "cmap", None), "name", "")
            if cmap in _BAD_CMAPS:
                out.append(("error", "bad_cmap",
                            f"用了 {cmap} 色图(非感知均匀、灰度不可辨);"
                            "改用 viridis/RdBu_r 等"))
                break
        out.extend(_surface_shape_issues(ax))
        return out
    box_ids = {id(box) for box in _boxplot_boxes(ax)}
    lines = [ln for ln in ax.lines
             if _npoints(ln) >= 3 and id(ln) not in box_ids]
    bars = [p for p in ax.patches if isinstance(p, Rectangle)]
    wedges = [p for p in ax.patches if isinstance(p, Wedge)]
    n_data = (len(ax.lines) + len(ax.patches) + len(ax.collections)
              + len(ax.images))
    texts = [t for t in ax.texts if t.get_text().strip()]

    if n_data == 0:
        out.append((
            "error", "empty_panel",
            "面板里没有任何数据元素——文字说明/图例板不算图,请删掉这个面板或换成真数据"
            if texts else "空面板,请删掉或补上数据"))
        return out

    if not box_ids:
        for k, ln in enumerate(lines, 1):
            if _is_flat(ln):
                lab = ln.get_label() or ""
                name = lab if lab and not lab.startswith("_") else f"第{k}条"
                out.append((
                    "error", "flat_line",
                    f"曲线「{name}」全程无变化,画出来是一条直线;"
                    "结论若是「该参数无影响」,写成一句话或表格一行,不要占一个面板"))
                break
        else:
            # 完全水平的线已在上面报过,不重复;剩下的是「肉眼看不出在动」的那档
            out.extend(_near_flat_issues(ax, lines))
        out.extend(_blown_range_issues(ax))

    if (1 <= len(bars) <= 2 and not lines and not wedges
            and not ax.collections and not ax.images):
        out.append(("warn", "thin_panel",
                    f"整个面板只有 {len(bars)} 根柱,信息过稀;并进相邻面板或改用表格"))

    if len(wedges) >= 2:
        span = sum(abs(w.theta2 - w.theta1) for w in wedges)
        if span > 350:
            out.append(("error", "pie_chart",
                        "饼图在竞赛论文里读数不精确、标签易重叠;改用堆叠条或表格"))

    if ax.name == "polar" and lines:
        out.append(("error", "radar_chart",
                    "雷达图角轴量纲不可比;改用热力矩阵/平行坐标/斜率图"))

    # 多指标共用一根无单位纵轴:量纲不同的指标画在一起,柱高之间没有可比性
    if bars:
        units = set()
        for t in ax.get_xticklabels():
            m = _UNIT_RE.search(t.get_text() or "")
            if m:
                units.add(m.group(1).strip())
        if len(units) >= 2:
            out.append((
                "error", "mixed_units",
                f"同一根纵轴上混了 {len(units)} 种量纲({'、'.join(sorted(units))});"
                "改成「相对基线倍数」归一化后标 ±%,或拆成各自带单位的独立面板"))

    # 极坐标、饼图、关掉坐标轴的示意面板本就没有纵轴,别拿轴标去要求它们
    has_yaxis = (getattr(ax, "axison", True) and ax.name != "polar"
                 and not wedges and not ax.images)
    ylab = (ax.get_ylabel() or "").strip()
    if has_yaxis and ylab.lower() in _VAGUE_YLABELS:
        out.append(("warn", "vague_ylabel",
                    f"纵轴标签「{ylab or '(空)'}」没有物理量与单位"))

    if any(p.get_hatch() for p in ax.patches):
        out.append(("warn", "hatch_fill",
                    "柱子用了斜线/点阵填充,观感像 Excel;靠 PALETTE 配色区分即可"))

    for coll in list(ax.collections) + list(ax.images):
        cmap = getattr(getattr(coll, "cmap", None), "name", "")
        if cmap in _BAD_CMAPS:
            out.append(("error", "bad_cmap",
                        f"用了 {cmap} 色图(非感知均匀、灰度不可辨);"
                        "改用 viridis/RdBu_r 等"))
            break

    out.extend(_faint_overlay_issues(ax))
    out.extend(_text_as_legend_issues(texts))
    out.extend(_lint_magnitude_gap(ax))
    out.extend(_lint_box_without_points(ax))

    if renderer is None:
        return out

    # 文字互相压住:标注挤在一起时数字会糊成一团,读者根本读不出来
    boxes = []
    for t in texts:
        try:
            boxes.append((t.get_text(), t.get_window_extent(renderer)))
        except Exception:  # noqa: BLE001
            continue
    for i in range(len(boxes)):
        hit = next((boxes[j][0] for j in range(i + 1, len(boxes))
                    if _overlap_ratio(boxes[i][1], boxes[j][1]) > 0.35), None)
        if hit:
            out.append(("error", "text_overlap",
                        f"标注「{boxes[i][0][:16]}」与「{hit[:16]}」重叠成一团"))
            break

    # 标注压在刻度标签上:上面只比标注与标注,标注落到轴线附近压住刻度数字
    # 查不出来。实测「最小损失 T/W_0=1.38」正好坐在 x 轴刻度上,两层数字叠成
    # 一团,体检却是全绿。
    tick_boxes = []
    for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        if not (t.get_text() or "").strip() or not t.get_visible():
            continue
        try:
            tick_boxes.append((t.get_text(), t.get_window_extent(renderer)))
        except Exception:  # noqa: BLE001
            continue
    for label, box in boxes:
        hit = next((name for name, tb in tick_boxes
                    if _overlap_ratio(box, tb) > _TICK_OVERLAP_RATIO), None)
        if hit:
            out.append((
                "error", "text_on_ticks",
                f"标注「{label[:16]}」压住横/纵轴刻度「{hit[:8]}」,两层数字叠在一起:"
                "把标注挪进数据区(annotate 的 xytext 往图心方向偏),"
                "或改用 plot_style.tidy(fig) 统一拉回"))
            break

    hides = _legend_hides_series(ax, renderer)
    if hides:
        out.extend(hides)
    elif _legend_covers_content(ax, renderer):
        out.append((
            "warn", "legend_covers",
            "图例压住数据或标注;单面板用 plot_style.legend_outside(ax),"
            "多面板用 plot_style.figure_legend_above(fig, axes),统一置顶横排"))
    if _xtick_labels_overlap(ax, renderer):
        out.append((
            "error", "xtick_labels_overlap",
            "横轴刻度标签互相压成一片,读者认不出是哪一类:"
            "出图前调一次 plot_style.tidy(fig) 自动斜排,"
            "或把长类名换成简称并在图注里给全称"))
    return out


def lint_figure(fig) -> list:
    """对整张图做体检,返回 [{level, code, panel, msg}]。"""
    issues = []
    axes = [ax for ax in fig.get_axes() if ax.get_label() != "<colorbar>"]
    renderer = _renderer(fig)
    groups = _panel_groups(axes)
    empty_overlays = {
        id(ax)
        for members in groups.values()
        if len(members) > 1 and any(m.has_data() for m in members)
        for ax in members
        if not ax.has_data()
    }
    lint_axes = [ax for ax in axes if id(ax) not in empty_overlays]
    for i, ax in enumerate(lint_axes):
        tag = f"({chr(97 + i)})" if len(_panel_groups(lint_axes)) > 1 else ""
        for level, code, msg in _lint_axes(ax, renderer):
            issues.append({"level": level, "code": code,
                           "panel": tag, "msg": msg})

    # 双轴柱状:两根柱各挂一条纵轴,高度之间毫无可比性,是经典误导图
    from matplotlib.patches import Rectangle
    for members in groups.values():
        bar_axes = [
            ax for ax in members
            if any(isinstance(p, Rectangle) for p in ax.patches)]
        if len(bar_axes) >= 2:
            issues.append({
                "level": "error", "code": "twin_axis_bar", "panel": "",
                "msg": "双纵轴柱状图:两根柱刻度不同、高度不可比;"
                       "拆成两个面板,或归一化到同一相对尺度"})
            break
    if len(axes) > 6:
        issues.append({"level": "warn", "code": "too_many_panels", "panel": "",
                       "msg": f"一张图 {len(axes)} 个面板,拆成两张更清楚"})
    issues.extend(_stacked_panel_issues(axes))
    issues.extend(_panel_label_issues(axes))
    issues.extend(_sparse_figure_issues(axes))
    thin_sample = _thin_sample_figure_issues(axes)
    if not thin_sample:
        issues.extend(_thin_line_figure_issues(axes))
    issues.extend(thin_sample)   # 采样过稀比“无关键数字”更根本，避免同图报两条硬伤
    issues.extend(_over_annotate_issues(axes))
    issues.extend(_lint_flat_mappable(axes))
    shown = _legend_labels(fig)
    issues.extend(_lint_duplicate_series(fig, axes, shown))
    issues.extend(_lint_overlapping_lines(axes, shown))
    issues.extend(_lint_panels_overlap(axes, renderer))
    issues.extend(_lint_legend_footprint(fig))
    issues.extend(_lint_layout_scale(fig))
    issues.extend(_lint_text_scale(fig))
    issues.extend(_lint_garbled_text(fig))
    return issues


_PANEL_TAG_RE = re.compile(r"^[（(]?\s*[a-hA-H]\s*[)）.、]?\s*$")
# 「(a) 分段线性标签分布」这种把标号写进标题的也算标过号——实测脚本更爱这种写法。
# 只认纯标号的话,标题带号的图会被一张张判成「没标」,提醒刷屏之后整条规则就被
# 当成噪音忽略了;更糟的是自动补号会再插一个 (a),同一格挂两个标号。
_PANEL_TAG_HEAD_RE = re.compile(r"^[（(]\s*[a-hA-H]\s*[)）]\s*\S")


def _has_panel_tag(text: str) -> bool:
    s = (text or "").strip()
    return bool(_PANEL_TAG_RE.match(s) or _PANEL_TAG_HEAD_RE.match(s))


def _panel_tag_prefix(text: str) -> str:
    """从「(a) 需求趋势」里取出规范化的标号「(a)」;没有标号返回空串。"""
    s = (text or "").strip()
    if not _has_panel_tag(s):
        return ""
    m = re.match(r"[（(]?\s*([a-hA-H])\s*[)）.、]?", s)
    return f"({m.group(1).lower()})" if m else ""


def _panel_tagged(ax) -> bool:
    """这一格是否已经标过号:图内文字、居中标题、左/右对齐标题都算。"""
    texts = [t.get_text() for t in ax.texts]
    texts += [ax.get_title(loc) for loc in ("center", "left", "right")]
    return any(_has_panel_tag(t) for t in texts)


def _stacked_panel_issues(axes) -> list:
    """面板竖着堆成一列:占掉大半页版面,每格却只有版心一半宽。

    实测事故:三张互不相干的图(阈值曲线 / 误差贡献横条 / 改善幅度柱)用
    `subplots(3, 1)` 竖排,排进 Word 吃掉整整半页,宽度按竖图收窄到约 10cm,
    缩放比 0.6——图内 10pt 的刻度排出来只剩 6pt,比正文还小。
    同样三格横排成一条 16cm×5cm,占的版面小一半,每格还更宽更清楚。

    共用同一根 x 轴的竖排是正当排布(同一自变量的多条响应,如时间轴上的
    价格与成交量),这类不判——判它会把正确写法一起堵死。
    """
    axes = [ax for ax in panel_axes(axes) if not _is_3d_ax(ax)]
    if len(axes) < 2:
        return []
    xs = {round(float(ax.get_position().x0), 2) for ax in axes}
    ys = {round(float(ax.get_position().y0), 2) for ax in axes}
    # 单列(x 起点相同)且分了多行才算竖排;twinx 双轴位置完全重合,ys 只有一个值
    if len(xs) > 1 or len(ys) < 2:
        return []
    try:
        shared = all(axes[0].get_shared_x_axes().joined(axes[0], ax)
                     for ax in axes[1:])
    except Exception:  # noqa: BLE001  取不到共享关系就按不共享处理
        shared = False
    if shared:
        return []
    n = len(axes)
    how = (f'combo_axes({n}) 或 plt.subplots(1, {n}, figsize=plot_style.figsize("row{n}"))'
           if n <= 3 else "每张放 2–3 格,拆成两张图")
    return [{
        "level": "error", "code": "stacked_panels", "panel": "",
        "msg": (f"{n} 个面板竖着堆成一列:排进 Word 会占掉大半页,宽度却只有版心"
                f"一半,图内文字比正文还小。改成横排一行 {n} 列——{how};"
                f"只有共用同一根 x 轴(同一自变量的多条响应)才允许竖排")}]


def _panel_label_issues(axes) -> list:
    """多面板缺 (a)(b)(c):正文写「见图3.1(b)」时读者不知道该看哪一格。

    双轴(twinx)会多出一个位置完全重合的 axes,但它跟主轴是同一格,不能按两个面板
    去要求标号——否则每张双轴图都被无端报一条。所以先按位置合并再数。
    """
    groups: dict = {}
    for ax in panel_axes(axes):
        key = tuple(round(float(v), 3) for v in ax.get_position().bounds)
        groups[key] = groups.get(key, False) or _panel_tagged(ax)
    if len(groups) < 2:
        return []
    labeled = sum(1 for v in groups.values() if v)
    if labeled >= len(groups):
        return []
    return [{
        "level": "warn", "code": "missing_panel_labels", "panel": "",
        "msg": (f"{len(groups)} 个面板里只有 {labeled} 个标了 (a)(b)(c):"
                "正文引用「图X(b)」时对不上格;出图末尾加一句 "
                "plot_style.panel_labels(axes)")}]


_ROW2_RECIPE = ('改成一行两列组图横排占满版心:'
                'from plot_style import combo_axes; fig, axes = combo_axes(2)'
                '(等价于 plt.subplots(1, 2, figsize=plot_style.figsize("row2"))),'
                '左格放这组柱(柱顶标数值)、右格补另一类证据'
                '(趋势曲线/分布散点/热图);'
                # 「改写成表格」从前只是这句话的尾巴,模型看不见也不敢用,于是硬凑
                # 第二格——拿无关证据充数比原来那张更糟。数据就那么几个值时,
                # 表格才是对的载体,得说清它是被允许的、以及换载体不等于丢证据。
                '凑不出第二格就【不要硬凑】:删掉这张图,把同一批数字写成'
                'Markdown 三线表放回正文原处,表后配一句解读,'
                '把原本要靠图说明的结论说出来——换的是载体不是证据,'
                '该问的得分点一条都不能少。斜率图也可以')


def _bars_are_horizontal(bars) -> bool:
    """barh(龙卷风/重要性排序)与 bar 的区分:横条厚度一致、长度不一。"""
    hs = {round(float(b.get_height()), 6) for b in bars}
    ws = {round(float(b.get_width()), 6) for b in bars}
    return len(hs) == 1 and len(ws) > 1


def _sparse_figure_issues(axes) -> list:
    """一组柱子撑满一整张图:占半页纸讲不出半句结论,不许单独成图。

    实测事故:一张「RMSE/MAE 两组对比」4 根柱单独成图插进论文,图题却写着
    「部分依赖非线性响应」——版面被吃掉大半页,信息量不如表格一行。
    只禁不给路会被绕开(标两个数值就降级放行),所以硬伤文案直接给出
    `figsize("row2")` 的一行两列写法,照抄即可。
    判定口径按整张图(不是单面板):唯一面板 + 只有 ≤8 根柱 + 无曲线/热图/散点。
    竖柱一律硬伤——柱顶标了数值也改变不了「4 个数字占一整页」这件事;
    横条(龙卷风、重要性排序)本身就是被推荐的图种,只在没有任何数值标注时判硬伤。
    误差棒会带出 LineCollection,走上面「柱之外还有别的图元」那条豁免。
    """
    from matplotlib.patches import Rectangle

    if len(axes) != 1:
        return []          # 多面板本身就是「合并证据」,不按光柱图判
    ax = axes[0]
    if _is_3d_ax(ax):
        return []
    lines = [ln for ln in ax.lines if _npoints(ln) >= 3]
    bars = [p for p in ax.patches if isinstance(p, Rectangle)]
    others = (len(ax.patches) - len(bars)) + len(ax.collections) + len(ax.images)
    if not bars or len(bars) > 8 or lines or others:
        return []
    texts = [t for t in ax.texts if t.get_text().strip()]
    # 误差棒挂在 BarContainer 上;有它说明带了不确定性信息
    has_err = any(getattr(c, "errorbar", None)
                  for c in getattr(ax, "containers", []))
    if not texts and not has_err:
        return [{
            "level": "error", "code": "sparse_bar_figure", "panel": "",
            "msg": (f"整张图只有 {len(bars)} 根光柱,信息量太稀,不许单独成图:"
                    + _ROW2_RECIPE)}]
    if not _bars_are_horizontal(bars):
        return [{
            "level": "error", "code": "sparse_bar_figure", "panel": "",
            "msg": (f"整张图就是一组 {len(bars)} 根竖柱的简单柱状图,"
                    "柱顶标了数值也撑不起一整张版面:" + _ROW2_RECIPE)}]
    return [{
        "level": "warn", "code": "thin_bar_figure", "panel": "",
        "msg": (f"整张图只有 {len(bars)} 根横条,单独成图偏薄;"
                "建议与相关证据合成一行两列组图"
                '(figsize("row2")),或改用斜率图/表格')}]


_DENSE_RECIPE = (
    '改成一行两列组图并标出关键数字:'
    'fig, axes = plt.subplots(1, 2, figsize=plot_style.figsize("row2")),'
    '左格放这条曲线(峰值/终值/R² 用 annotate 标上),'
    '右格补另一类证据(残差/分布/对照曲线);'
    '或在本格加区间带+角标,让读者不翻表也能读出结论')

_METRIC_TEXT_RE = re.compile(
    r"(?:AUC|R(?:²|\^?2)|RMSE|MAE|MAPE|WAPE|F1|峰值|终值|最优|最大|最小|"
    r"名义|基线|偏差|误差|改善|提升).{0,16}-?\d|"
    r"-?\d(?:\.\d+)?\s*(?:%|倍|km/s|m/s|kg|s|h|dB)\b",
    re.I)
_SWEEP_AXIS_RE = re.compile(
    r"灵敏|敏感|扰动|参数|半径|阈值|sensitivity|perturb|sweep|tuning", re.I)
_DIAGNOSTIC_CURVE_RE = re.compile(
    r"真正率|假正率|召回率|精确率|\bTPR\b|\bFPR\b|precision|recall", re.I)


def _has_metric_summary(ax) -> bool:
    """图内是否写了可核验的结论数,而不是名称里的版本号/序号。"""
    texts = [t.get_text() or "" for t in ax.texts]
    lg = ax.get_legend()
    if lg is not None:
        texts.extend(t.get_text() or "" for t in lg.get_texts())
    return any(_METRIC_TEXT_RE.search(s) for s in texts)


def _looks_like_parameter_sweep(ax) -> bool:
    text = " ".join((
        ax.get_xlabel() or "", ax.get_ylabel() or "",
        ax.get_title() or ""))
    return bool(_SWEEP_AXIS_RE.search(text))


def _looks_like_diagnostic_curve(ax) -> bool:
    text = " ".join((ax.get_xlabel() or "", ax.get_ylabel() or ""))
    return bool(_DIAGNOSTIC_CURVE_RE.search(text))


def _thin_line_figure_issues(axes) -> list:
    """一两根光秃折线撑满整张图:能看趋势,读不出任何一个数。

    实测事故:一张「需求随周次变化」只有 8 个点、图上一个数字都没有,
    评委还得翻表才能知道峰值是多少。两条对照线同样素——只多了一根颜色,
    峰值、差值、R² 仍不在图上。柱状图已经按 sparse_bar 拦了,
    折线/散点漏了——模型会改画一条线绕过「禁简单柱」。
    多面板、热图、区间带、图内/图例里的数字标注都不判。
    """
    from matplotlib.collections import PathCollection, PolyCollection, QuadMesh
    from matplotlib.patches import Rectangle

    groups = _panel_groups(axes)
    if len(groups) != 1:
        return []
    members = next(iter(groups.values()))
    if any(_is_3d_ax(ax) for ax in members):
        return []
    n_lines = n_scatter = n_bars = n_other = 0
    has_heat = has_band = has_metric = False
    for ax in members:
        if _boxplot_boxes(ax):
            return []             # 箱线图由 box_without_points 专门检查
        n_lines += sum(
            1 for ln in ax.lines
            if _npoints(ln) >= 3 and not _is_guide_line(ln))
        n_bars += sum(1 for p in ax.patches if isinstance(p, Rectangle))
        n_other += sum(1 for p in ax.patches if not isinstance(p, Rectangle))
        if ax.images:
            has_heat = True
        for c in ax.collections:
            if isinstance(c, QuadMesh):
                has_heat = True
            elif isinstance(c, PolyCollection):
                has_band = True
            elif isinstance(c, PathCollection):
                n_scatter += 1
        has_metric = has_metric or _has_metric_summary(ax)
    if has_heat or has_band or has_metric or n_bars or n_other >= 3:
        return []
    series = n_lines + n_scatter
    if series == 0 or series > 2:
        return []          # 0 条由 empty_panel 管;≥3 条对照已经密
    kind = "一条曲线" if series == 1 and n_lines else (
        "一组散点" if series == 1 else f"{series} 条对照曲线")
    return [{
        "level": "error", "code": "sparse_line_figure", "panel": "",
        "msg": (f"整张图只有{kind},图上一个数字都没有,信息量太稀,不许单独成图:"
                + _DENSE_RECIPE)}]


_THIN_SAMPLE_MAX = 5
_THIN_SAMPLE_RECIPE = (
    '三个离散值不要画成散点撑满整张图:改一行两列,'
    'fig, axes = plt.subplots(1, 2, figsize=plot_style.figsize("row2")),'
    '左格对照、右格相对误差或残差;'
    '灵敏度/响应曲线用 np.linspace 密采样至少 11 个点'
    '(不要只取 -5/0/+5 三点连线);'
    '图内只标 1–2 个关键数,不要每个点都标')


def _is_guide_line(ln) -> bool:
    """axvline / axhline / 两点竖连线:不是数据系列。"""
    try:
        xd = [float(v) for v in ln.get_xdata()]
        yd = [float(v) for v in ln.get_ydata()]
    except (TypeError, ValueError):
        return True
    if len(xd) < 2:
        return True
    return (max(xd) - min(xd) <= 1e-12) or (max(yd) - min(yd) <= 1e-12)


def _series_point_counts(ax) -> list:
    """真正的数据系列点数:参考线、热图、区间带都不算。"""
    from matplotlib.collections import PathCollection

    counts = []
    box_ids = {id(box) for box in _boxplot_boxes(ax)}
    for ln in ax.lines:
        if id(ln) in box_ids or _is_guide_line(ln):
            continue
        n = _npoints(ln)
        if n >= 2:
            counts.append(n)
    for c in ax.collections:
        if not isinstance(c, PathCollection):
            continue
        try:
            n = len(c.get_offsets())
        except Exception:  # noqa: BLE001
            continue
        if n >= 2:
            counts.append(n)
    return counts


def _panel_is_heatmap(ax) -> bool:
    from matplotlib.collections import QuadMesh

    if ax.images:
        return True
    return any(isinstance(c, QuadMesh) for c in ax.collections)


def _thin_sample_figure_issues(axes) -> list:
    """三点散点 / 三点灵敏度:标了数字也撑不起一张科研图。

    实测事故:禁了简单柱之后,模型改画三种宇宙速度的 6 个散点,每个点旁标
    7.91/7.90;灵敏度只取轨道半径 0.95/1.00/1.05 三点连线。图上有数字,
    sparse_line 放行,评委看到的仍是一张空白坐标纸上的两三个点。
    多面板(对照+残差)和密采样(≥11 点)是走得通的路,热图不判。
    """
    groups = _panel_groups(axes)
    if len(groups) != 1:
        return []
    members = next(iter(groups.values()))
    if any(_is_3d_ax(ax) for ax in members):
        return []
    if any(_panel_is_heatmap(ax) for ax in members):
        return []
    if any(_boxplot_boxes(ax) for ax in members):
        return []          # 箱线图由样本点闸门检查,不按折线采样数判断
    if any(_has_errorbar(ax) for ax in members):
        return []          # 少量离散实验点 + 误差棒本身就是完整证据
    counts = []
    for ax in members:
        counts.extend(_series_point_counts(ax))
    if not counts:
        return []
    longest = max(counts)
    sweep = any(_looks_like_parameter_sweep(ax) for ax in members)
    max_allowed = 10 if sweep else _THIN_SAMPLE_MAX
    if longest > max_allowed:
        return []
    # 五个工作点的 ROC/PR 等曲线若已给出 AUC 等汇总指标,允许作为紧凑诊断图;
    # 三点图仍不放行,避免靠写一个数字绕过「三个点撑满整图」。
    if longest >= 5 and (any(_has_metric_summary(ax) for ax in members)
                         or any(_looks_like_diagnostic_curve(ax)
                                for ax in members)):
        return []
    n_series = len(counts)
    kind = (f"{n_series} 组各 {longest} 个点" if n_series > 1
            else f"{longest} 个点")
    return [{
        "level": "error", "code": "thin_sample_figure", "panel": "",
        "msg": (f"整张图只有{kind},采样过稀、空白太多,标数字也救不了:"
                + _THIN_SAMPLE_RECIPE)}]


def _over_annotate_issues(axes) -> list:
    """每个点都标数字:该标的结论被一排标签墙盖住。

    科研图只点出峰值/基线/最大偏差;其余点让刻度说话。
    """
    groups = _panel_groups(axes)
    if len(groups) != 1:
        return []
    members = next(iter(groups.values()))
    if any(_panel_is_heatmap(ax) for ax in members):
        return []
    n_pts = 0
    n_labels = 0
    for ax in members:
        n_pts += sum(_series_point_counts(ax))
        n_labels += sum(
            1 for t in ax.texts if re.search(r"\d", t.get_text() or ""))
    if n_pts < 4 or n_labels < 5 or n_labels < 0.8 * n_pts:
        return []
    return [{
        "level": "warn", "code": "over_annotated", "panel": "",
        "msg": (f"图上 {n_labels} 处数字标注,几乎每个点都标了;"
                "只留 1–2 个关键数(峰值/基线/最大偏差),其余让刻度说话")}]


def _visible_text_objects(fig) -> list:
    """图上真正会印出来的 Text 对象:标题、轴标、刻度、图例、annotate。"""
    out = []
    for ax in fig.get_axes():
        out.extend([ax.title, ax.xaxis.label, ax.yaxis.label])
        out.extend(ax.get_xticklabels())
        out.extend(ax.get_yticklabels())
        out.extend(ax.texts)
        lg = ax.get_legend()
        if lg is not None:
            out.extend(lg.get_texts())
    out.extend(getattr(fig, "texts", []))
    for lg in getattr(fig, "legends", []):
        out.extend(lg.get_texts())
    return [t for t in out
            if (t.get_text() or "").strip() and t.get_visible()]


def _visible_texts(fig) -> list:
    """图上真正会印出来的文字内容。"""
    return [t.get_text() for t in _visible_text_objects(fig)]


# 汉语拼音音节 = 声母(可空) + 韵母。存两张小表按组合判定,比硬编码 405 个音节短,
# 也不会漏掉 lüe/nüe(此处 v 即 ü)。长度按最长优先匹配,避免 "ang" 被切成 "a"+"ng"。
_PY_INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
                "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")
_PY_FINALS = ("iang", "iong", "uang", "ueng", "ang", "eng", "ing", "ong",
              "uai", "uan", "van", "iao", "ian", "iou", "uen", "ai", "ei",
              "ao", "ou", "an", "en", "er", "ia", "ie", "in", "iu", "ua",
              "uo", "ui", "un", "ve", "vn", "a", "o", "e", "i", "u", "v")

# 能被切成拼音、但确实是常用英文词的,先摘出去。漏一个的后果只是提醒作者换个词,
# 比把整张合规英文图判成乱码轻。
_PINYIN_SAFE_WORDS = frozenset("""
machine median modeling modelling hanging banana panda linear sedan human
china taiwan beijing shanghai gaussian manga anime piano radar sonar lidar
dengue mango tango bingo lingo cargo hangar mandarin gauge range change
""".split())

_PINYIN_MIN_LEN = 6        # 更短的词(time=ti+me)撞车率太高,不参与判定
_PINYIN_LONG_SYLLABLES = 5  # 单个词切出这么多音节才敢单独定罪(baseline 就有 4 个)

# 英文构词后缀。带这些尾巴的词即使切得成拼音也是英文(baseline=ba+se+li+ne、
# literature=li+te+ra+tu+re)。故意不收 -ing/-in:jing/ming/xing 全是常用汉字音。
_EN_SUFFIXES = ("line", "ine", "age", "ure", "ate", "tion", "sion", "ment",
                "ness", "able", "ible", "ance", "ence", "ity", "ive", "ous",
                "ful", "less", "ary", "ory", "ical")


def _pinyin_syllables(word: str) -> int:
    """这个词能切成几个合法拼音音节;切不完整返回 0。"""
    n = len(word)
    reach = [0] * (n + 1)
    reach[n] = 1                      # 末尾可达,音节数 0(用 1 表示「可达」)
    for i in range(n - 1, -1, -1):
        best = 0
        for ini in ("",) + _PY_INITIALS:
            if ini and not word.startswith(ini, i):
                continue
            j = i + len(ini)
            for fin in _PY_FINALS:
                k = j + len(fin)
                if k <= n and word.startswith(fin, j) and reach[k]:
                    best = max(best, reach[k] + 1)
        reach[i] = best
    return max(0, reach[0] - 1)


def _pinyin_words(texts) -> list:
    """挑出像「把中文写成拼音」的标签词。"""
    import re as _re

    hits = []
    for s in texts:
        for w in _re.findall(r"[A-Za-z]{%d,}" % _PINYIN_MIN_LEN, s):
            lw = w.lower()
            if (lw in _PINYIN_SAFE_WORDS or lw in hits
                    or lw.endswith(_EN_SUFFIXES)):
                continue
            if _pinyin_syllables(lw) >= 2:
                hits.append(lw)
    return hits


_CJK_OK = None


def _cjk_available() -> bool:
    """本机是否装了带中文字形的字体。逐图体检要问很多遍,结果缓存住。"""
    global _CJK_OK
    if _CJK_OK is None:
        _CJK_OK = bool(_available(_CJK_FONTS, _PROBE_CJK))
    return _CJK_OK


# 成对 $…$ 之间是数学模式,由 mathtext.fontset(stix 等)渲染,那些字体没有汉字
_MATH_SPAN_RE = re.compile(r"(?<!\\)\$([^$]+?)(?<!\\)\$", re.S)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
# U+FFFD 是解码失败的替换字符;「锟斤拷」是 UTF-8 被当 GBK 解的经典产物
_MOJIBAKE_RE = re.compile("[\ufffd]|锟斤拷|烫烫烫")
# 不必查字形的字符:空白与 ASCII 控制符
_SKIP_GLYPH = set(" \t\r\n\u3000")
_GLYPH_CACHE: dict = {}


def _font_can_draw(name: str, ch: str) -> bool:
    """某款字体画不画得出这个字符。逐字查会问上千遍,结果缓存住。"""
    key = (name, ch)
    hit = _GLYPH_CACHE.get(key)
    if hit is None:
        hit = _has_glyphs(name, ch)
        _GLYPH_CACHE[key] = hit
    return hit


def _font_stack() -> list:
    """当前生效的字体栈,serif/sans-serif 这类族名展开成具体字体。"""
    rc = matplotlib.rcParams
    out = []
    for fam in list(rc.get("font.family") or []):
        if fam in ("serif", "sans-serif", "monospace", "cursive", "fantasy"):
            out.extend(rc.get(f"font.{fam}") or [])
        else:
            out.append(fam)
    seen, stack = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            stack.append(f)
    return stack


def _unrenderable_chars(texts) -> str:
    """字体栈里没有任何一款画得出的字符——成图上就是一个个方块。

    只查数学模式之外的正文:℃、μ、Ω、‰、① 这类符号和生僻字,常用汉字探针
    (_PROBE_CJK)是探不到的,得逐字查。
    """
    stack = _font_stack()
    if not stack:
        return ""
    bad = []
    seen = set()
    for s in texts:
        plain = _MATH_SPAN_RE.sub(" ", s or "")
        for ch in plain:
            if ch in seen or ch in _SKIP_GLYPH or ord(ch) < 0x80:
                continue
            seen.add(ch)
            if not any(_font_can_draw(f, ch) for f in stack):
                bad.append(ch)
    return "".join(bad)


def _cjk_in_mathtext(texts) -> str:
    """会走 mathtext 的汉字。数学字体(stix)没有汉字字形,必然渲染成 ¤。

    不只查 $…$ 里面:matplotlib 只要看见一对 $,就把【整句】交给 mathtext,
    「推重比 $T/W_0$ (无量纲)」里 $ 外面的「推重比」「无量纲」一样会变成 ¤。
    闸门一度只查 $ 内,那张图 issues 是空的,乱码直接进了画廊。
    """
    bad, seen = [], set()
    for s in texts:
        if "$" not in (s or "") or not _CJK_CHAR_RE.search(s):
            continue
        for ch in _CJK_CHAR_RE.findall(s):
            if ch not in seen:
                seen.add(ch)
                bad.append(ch)
    return "".join(bad)


# 单个符号后跟 _ 或 ^ 再跟 1–4 位角标:C_D、T/W_0、V^2。要求角标前那个字母本身
# 是独立符号(前面不是字母数字),这样 max_depth、rf_model、problem1_sens 都不误伤。
_RAW_SCRIPT_RE = re.compile(
    r"(?<![0-9A-Za-z_])([A-Za-z\u0370-\u03ff])([_^])([A-Za-z0-9]{1,4})"
    r"(?![0-9A-Za-z_])")


def _raw_script_labels(texts) -> list:
    """写成明文的上下标:`C_D` 印在图上就是一根下划线。

    这多半不是作者手写的,而是 `unmath_cjk_texts` 拆 `$…$` 之后的残留——
    汉字和 $ 同处一条标签时必须拆,拆完 `_D` 就露了出来。能转 Unicode 下标的
    在 `demath_cjk_label` 里已经转掉,能走到这里的都是字体画不出的,得换写法。
    """
    bad, seen = [], set()
    for s in texts:
        plain = _MATH_SPAN_RE.sub(" ", s or "")   # 纯公式走 mathtext,渲染正常
        for m in _RAW_SCRIPT_RE.finditer(plain):
            hit = m.group(0)
            if hit not in seen:
                seen.add(hit)
                bad.append(hit)
    return bad


def _lint_garbled_text(fig) -> list:
    """图上的字能不能看:方块字与拼音标签都算乱码,一律硬伤。

    两种事故实测都出过,且智能体自己看不见:
    ① 系统没有中文字体,图里所有汉字渲染成 □□□;
    ② 智能体为了躲开方块字,主动把「锚杆强度」写成 ganggan qiangdu ——
       评委看到的是一张连图例都读不懂的图,比方块字更糟。
    ③ `$流量 Q$`:汉字写进了数学模式,由没有汉字字形的数学字体渲染,必成方块。
    ④ ℃/Ω/① 这类符号和生僻字,字体栈里可能一款都画不出。
    ⑤ 「锟斤拷」「」:读数据时编码给错了,乱码被原样当标签画上去。

    ②只在【整张图一个汉字都没有】时判:图上已有正常中文说明字体没问题,
    这时出现的英文词是作者的正常用词,不该拦。
    """
    import re as _re

    texts = _visible_texts(fig)
    if not texts:
        return []
    joined = "".join(texts)
    has_cjk = bool(_re.search(r"[\u4e00-\u9fff]", joined))
    out = []
    if has_cjk and not _cjk_available():
        out.append({
            "level": "error", "code": "cjk_font_missing", "panel": "",
            "msg": ("图上有汉字,但本机没有任何带中文字形的字体,这些字会印成方块:"
                    "装宋体(SimSun)或 Noto Serif CJK SC 后重画;"
                    "装不了就把图内文字整体改成规范英文术语,不要写拼音")})
    else:
        # 字体栈整体没问题时才逐字查,否则每个汉字都缺、报出来是一屏噪音
        missing = _unrenderable_chars(texts)
        if missing:
            out.append({
                "level": "error", "code": "missing_glyphs", "panel": "",
                "msg": (f"这些字符当前字体一个都画不出,会印成方块:「{missing[:12]}」。"
                        f"换成字体里有的写法(℃→\\u00b0C、Ω→ohm、①→(1)),"
                        f"或改用带该字形的字体")})

    mathcjk = _cjk_in_mathtext(texts)
    if mathcjk:
        out.append({
            "level": "error", "code": "cjk_in_mathtext", "panel": "",
            "msg": (f"这条标签含汉字「{mathcjk[:8]}」又含 $…$,matplotlib 会把整句"
                    f"交给没有汉字的数学字体,汉字印成 ¤:同一条里不要写 $。"
                    f"存图时会自动拆掉 $,但拆完角标会剩一根下划线(C_D),"
                    f"所以别只把 $ 去掉——轴标直接写中文量名+单位"
                    f"(阻力系数、推重比、重力损失 ΔV / (m/s)),符号交给符号说明表")})

    raw = _raw_script_labels(texts)
    if raw:
        out.append({
            "level": "error", "code": "raw_subscript", "panel": "",
            "msg": (f"图上把角标写成了明文下划线「{'、'.join(raw[:4])}」,"
                    f"印出来就是 C_D 这样一根下划线,不是真下标。"
                    f"本机字体没有对应的 Unicode 下标字形,自动转不了,"
                    f"只能换写法:轴标改写中文量名+单位"
                    f"(阻力系数 C_D → 阻力系数;推重比 T/W_0 → 推重比),"
                    f"符号留给正文的符号说明表;"
                    f"整条标签不含汉字时可以直接写 $C_D$ 走数学字体")})

    for s in texts:
        if _MOJIBAKE_RE.search(s or ""):
            out.append({
                "level": "error", "code": "mojibake_text", "panel": "",
                "msg": (f"图内文字有乱码「{s.strip()[:16]}」:多半是读数据时编码给错了"
                        f"(CSV 用 GBK 存却按 UTF-8 读)。"
                        f"在 read_csv 里指定 encoding,别把乱码当标签画上去")})
            break

    if has_cjk:
        return out
    hits = _pinyin_words(texts)
    strong = [w for w in hits if _pinyin_syllables(w) >= _PINYIN_LONG_SYLLABLES]
    if len(hits) >= 2 or strong:
        out.append({
            "level": "error", "code": "pinyin_labels", "panel": "",
            "msg": ("图内文字疑似把中文写成了拼音(" + "、".join(hits[:4])
                    + "):评委读不懂,比方块字更糟。plot_style.apply() 已配好中文"
                      "字体,直接写中文即可;若确要用英文,写规范术语"
                      "(锚杆强度→Bolt strength),绝不能用拼音")})
    return out


# 单一颜色占到这个面积比例,整张热图/等高线就等于没画东西
_FLAT_IMAGE_RATIO = 0.95
_FLAT_IMAGE_WARN = 0.85
_FLAT_IMAGE_BINS = 32
_FLAT_MIN_CELLS = 64        # 取值太少(如 4×4 示意网格)不按平板图判


# 只对「整片色块」类图判平板:散点的 c= 数组本来就允许极不均衡(标记异常点),
# 按面积占比判会把一张正常的异常点图判成硬伤。
_GRID_ARTISTS = ("AxesImage", "QuadMesh", "PolyCollection", "TriMesh",
                 "PcolorImage", "NonUniformImage")


def _mappable_arrays(ax) -> list:
    """取出这个面板里热图/等高线/网格图真正画进去的数值网格。"""
    import numpy as np

    out = []
    for im in list(getattr(ax, "images", [])) + list(ax.collections):
        if type(im).__name__ not in _GRID_ARTISTS:
            continue
        arr = None
        get = getattr(im, "get_array", None)
        if callable(get):
            arr = get()
        if arr is None:
            continue
        try:
            a = np.asarray(np.ma.filled(arr, np.nan), dtype=float).ravel()
        except (TypeError, ValueError):
            continue
        a = a[np.isfinite(a)]
        if a.size >= _FLAT_MIN_CELLS:
            out.append(a)
    return out


def _lint_flat_mappable(axes) -> list:
    """整片一个色的热图/等高线:占了半页纸,读者一个结论也读不出来。

    实测事故:一张 E-b 参数空间的失效模式图,96% 的面积是同一种蓝,
    图注却写着「三种模式分区明显」——图上根本看不出第二种模式在哪。
    判的是画进去的数值而不是像素:色标拉伸、配色深浅都骗不过它。
    """
    import numpy as np

    out = []
    for i, ax in enumerate(axes):
        tag = f"({chr(97 + i)})" if len(axes) > 1 else ""
        for a in _mappable_arrays(ax):
            lo, hi = float(np.min(a)), float(np.max(a))
            if hi <= lo:
                share, uniq = 1.0, 1
            else:
                counts, _ = np.histogram(a, bins=_FLAT_IMAGE_BINS,
                                         range=(lo, hi))
                share = float(counts.max()) / float(a.size)
                uniq = int((counts > 0).sum())
            if share >= _FLAT_IMAGE_RATIO:
                out.append({
                    "level": "error", "code": "flat_mappable", "panel": tag,
                    "msg": (f"整片图 {share:.0%} 的面积落在同一个色档"
                            f"(全图仅 {uniq} 档有值),读者看不出任何分区或梯度:"
                            "换个能拉开差异的量来画(取对数、画差值/相对变化),"
                            "或缩到真正有变化的参数区间;实在没有分区就别单独成图")})
                break
            if share >= _FLAT_IMAGE_WARN:
                out.append({
                    "level": "warn", "code": "dull_mappable", "panel": tag,
                    "msg": (f"{share:.0%} 的面积挤在同一个色档,层次偏弱;"
                            "考虑改用对数色标(LogNorm)或把色标范围收到实际数据区间")})
                break
    return out


# 两条线的差异中位数不到量程的这个比例,画出来就是一条线(线宽本身就占 1.5pt)
_LINE_OVERLAP_TOL = 0.012
_LINE_OVERLAP_MIN_PTS = 8


def _line_gap(a, b):
    """两条线的差异中位数 / 量程;x 网格不同或点太少返回 None。"""
    import numpy as np

    try:
        xa, ya = np.asarray(a.get_xdata(), float), np.asarray(a.get_ydata(), float)
        xb, yb = np.asarray(b.get_xdata(), float), np.asarray(b.get_ydata(), float)
    except (TypeError, ValueError):
        return None
    if xa.shape != xb.shape or ya.shape != yb.shape:
        return None
    if ya.size < _LINE_OVERLAP_MIN_PTS or not np.allclose(xa, xb, equal_nan=True):
        return None
    both = np.concatenate([ya, yb])
    both = both[np.isfinite(both)]
    if both.size < _LINE_OVERLAP_MIN_PTS:
        return None
    scale = float(np.ptp(both))
    if scale <= 0:
        return None
    return float(np.nanmedian(np.abs(ya - yb))) / scale


# 两个面板连标签一起重叠到这个比例,就是压在一起了。留够余量:紧凑排版下
# 相邻面板的 tightbbox 本来就会挨着甚至轻微相交。
_PANEL_OVERLAP_MAX = 0.15


def _panel_boxes(axes, renderer) -> list:
    """每个面板连同它的刻度、轴标、标题在内的完整占位。

    twinx/twiny 的兄弟轴与画在主面板内部的插图(inset)本来就该重叠,不参与判定:
    前者位置完全相同,后者整个落在另一个面板的位置框里。
    """
    keep = []
    for i, ax in enumerate(axes):
        pos = ax.get_position()
        twin_or_inset = False
        for j, other in enumerate(axes):
            if i == j:
                continue
            op = other.get_position()
            same = all(abs(a - b) < 1e-6 for a, b in
                       zip(pos.bounds, op.bounds))
            inside = (op.x0 <= pos.x0 and pos.x1 <= op.x1
                      and op.y0 <= pos.y0 and pos.y1 <= op.y1)
            if same or inside:
                twin_or_inset = True
                break
        if twin_or_inset:
            continue
        try:
            keep.append((i, ax.get_tightbbox(renderer)))
        except Exception:  # noqa: BLE001
            continue
    return [(i, b) for i, b in keep if b is not None]


def _lint_panels_overlap(axes, renderer) -> list:
    """面板连着轴标一起压到隔壁面板身上。

    约束布局本来会给标签留位,但脚本一调 subplots_adjust/tight_layout 就把它顶掉了,
    成图是「(a) 的纵轴标题印在 (b) 的刻度上」——两个面板都读不利索。
    """
    if renderer is None or len(axes) < 2:
        return []
    boxes = _panel_boxes(axes, renderer)
    for m in range(len(boxes)):
        for n in range(m + 1, len(boxes)):
            ratio = _overlap_ratio(boxes[m][1], boxes[n][1])
            if ratio > _PANEL_OVERLAP_MAX:
                ta = f"({chr(97 + boxes[m][0])})"
                tb = f"({chr(97 + boxes[n][0])})"
                return [{
                    "level": "error", "code": "panels_overlap", "panel": "",
                    "msg": (f"面板 {ta} 与 {tb} 连轴标一起重叠了 {ratio:.0%},"
                            f"一个面板的标签会印到另一个的刻度上:"
                            f"删掉脚本里的 subplots_adjust/tight_layout,"
                            f"改用 plot_style.figsize(kind, rows=行数) 按行数加高画布")}]
    return []


def _legend_labels(fig) -> set:
    """图例里真正列出来的条目名(整图级 + 各面板)。"""
    out = set()
    for lg in list(getattr(fig, "legends", [])):
        out |= {t.get_text() for t in lg.get_texts()}
    for ax in fig.get_axes():
        lg = ax.get_legend()
        if lg is not None:
            out |= {t.get_text() for t in lg.get_texts()}
    return out


def _series_style_key(artist, is_bar: bool = False):
    """这条线/这根柱在读者眼里的样子:颜色 + 线型 + marker(柱子看颜色 + 填充)。"""
    import matplotlib.colors as mcolors

    try:
        raw = artist.get_facecolor() if is_bar else artist.get_color()
        if is_bar and hasattr(raw, "__len__") and len(raw) and hasattr(raw[0], "__len__"):
            raw = raw[0]
        col = tuple(round(float(v), 2) for v in mcolors.to_rgba(raw))
    except Exception:  # noqa: BLE001  取不到颜色就不参与判重
        return None
    if is_bar:
        return col, "bar", str(artist.get_hatch() or "")
    ls = str(artist.get_linestyle())
    if ls in ("", "None", "none"):
        return None
    return col, ls, str(artist.get_marker())


def _lint_duplicate_series(fig, axes, shown: set) -> list:
    """两个量画成一模一样:图例列了两条,图上分不出哪条是哪条。

    实测事故:一张六面板的传感器退化图里,「发动机 1」与「发动机 3」都是黑色实线
    ——色板只有 8 色,旧版发号发到第 9 个量就取模回头发同一个色,线型也不跟着换。
    图例把两个名字并排列出来,读者却没法把任何一条曲线归到其中一个名字上,
    这张图想说明的「不同发动机退化轨迹不同」当场作废。
    只比图例里列出来的条目、且按量名去重:同一个量在六个面板里各画一条是正常的。
    """
    styles: dict = {}
    from matplotlib.patches import Rectangle

    for ax in axes:
        for ln in ax.lines:
            lab = (ln.get_label() or "").strip()
            if lab in shown and ln.get_visible():
                key = _series_style_key(ln)
                if key:
                    styles.setdefault(lab, key)
        for p in ax.patches:
            lab = (p.get_label() or "").strip()
            if isinstance(p, Rectangle) and lab in shown:
                key = _series_style_key(p, is_bar=True)
                if key:
                    styles.setdefault(lab, key)
    inv: dict = {}
    for lab, key in styles.items():
        inv.setdefault(key, []).append(lab)
    dup = [labs for labs in inv.values() if len(labs) > 1]
    if not dup:
        return []
    a, b = dup[0][0], dup[0][1]
    more = f";本图另有 {len(dup) - 1} 组同样撞车" if len(dup) > 1 else ""
    return [{
        "level": "error", "code": "duplicate_series_style", "panel": "",
        "msg": (f"「{a}」与「{b}」画成了同一种颜色+线型:图例列着两条,"
                f"图上认不出哪条归哪个名字{more}。改成 "
                f"`ax.plot(x, y, label=名, **plot_style.series_style(名))`"
                f"——它按量名发色,8 个基色各分 3 档明暗共 24 种,"
                f"再多就换线型与 marker,不会撞车")}]


def _lint_overlapping_lines(axes, shown: set) -> list:
    """两条曲线肉眼分不开:图例写着「优化前/优化后」,图上只看得见一条线。

    实测事故:一张 2×2 的「基线 vs 优化」对比图,四个面板的红蓝线相对差异都不到
    量程的 1%,评委看到的是四条单线——想证明的「优化有效」恰恰没被证明。
    只比图例里列出来的线:收敛轨迹图会画几十条半透明的重启曲线(它们本就不进
    图例、后期本就收敛到一处),拿它们判重合纯属噪音。
    只给提醒:若两线重合本身就是结论(实测与拟合吻合、守恒量不变),重合是对的。
    """
    out = []
    for i, ax in enumerate(axes):
        tag = f"({chr(97 + i)})" if len(axes) > 1 else ""
        lines = [ln for ln in ax.lines
                 if _npoints(ln) >= _LINE_OVERLAP_MIN_PTS
                 and ln.get_linestyle() not in ("", "None")
                 and ln.get_visible()
                 and (ln.get_label() or "") in shown]
        hit = None
        for m in range(len(lines)):
            for n in range(m + 1, len(lines)):
                gap = _line_gap(lines[m], lines[n])
                if gap is not None and gap < _LINE_OVERLAP_TOL:
                    hit = (lines[m], lines[n], gap)
                    break
            if hit:
                break
        if not hit:
            continue
        la = (hit[0].get_label() or "").lstrip("_") or "线1"
        lb = (hit[1].get_label() or "").lstrip("_") or "线2"
        out.append({
            "level": "warn", "code": "overlapping_lines", "panel": tag,
            "msg": (f"「{la}」与「{lb}」差异只有量程的 {hit[2]:.1%},"
                    f"画出来是同一条线,图例有两条、图上只看得见一条:"
                    f"改画两者之差/比值,或把差异区间做成局部放大插图;"
                    f"若「两条重合」本身就是要证的结论,忽略本条")})
    return out


# 图例占到画布这么高,绘图区就被挤成一条缝了
_LEGEND_H_WARN = 0.18


def _lint_legend_footprint(fig) -> list:
    """整图级图例吃掉画布:11 个条目排成 3 行挂在顶上,数据区只剩下面那点地方。

    只看 fig.legend:它横在所有面板上方,占多少就从每个面板身上扣多少。面板自己的
    ax.legend 落在面板内部,占的是自家地盘(实测一个 4 条目竖排图例就占面板高度
    25%,那是正常的),它压没压住数据由 _legend_covers_content 判。
    """
    out = []
    try:
        h_px = float(fig.get_size_inches()[1]) * float(fig.dpi)
        if h_px <= 0:
            return []
        renderer = _renderer(fig)
        for lg in list(getattr(fig, "legends", [])):
            if not lg.get_visible():
                continue
            share = lg.get_window_extent(renderer).height / h_px
            if share >= _LEGEND_H_WARN:
                n = len(lg.get_texts())
                out.append({
                    "level": "warn", "code": "legend_eats_canvas", "panel": "",
                    "msg": (f"图例占了画布高度的 {share:.0%}"
                            f"({n} 个条目),数据区被压扁:把随面板变化的条目改成"
                            f"各面板自己的图例,或把「均值=…」这类数值移到面板内"
                            f"标注/表格里,只在图例留下线型与量名")})
                break
    except Exception:  # noqa: BLE001  体检失败绝不能连累出图
        return out
    return out


# 排版契约:图最终要插进 A4 正文(版心 16cm)。满栏图按 14.7cm 放,收窄图按 11.2cm。
# figsize 画多大,Word 里就得按比例缩多少,图内文字跟着一起缩——figsize=(14,8) 的图
# 缩到 11.2cm 是 0.32 倍,11pt 的轴标排出来只剩 3.5pt,肉眼几乎不可读。
# 所以出图时就得按最终尺寸画:宽度 ≤6.3 英寸,缩放比才接近 1:1。
_PLACE_ROW_CM = 16.0           # 占满版心(宽高比≥2.0,如 figsize("row2") 的一行两列)
_PLACE_FULL_CM = 14.7          # 满栏(宽高比≥1.8 或多面板)
_PLACE_NARROW_CM = 11.2        # 常规单图
_PLACE_TALL_CM = 7.5           # 竖图(宽高比≤0.85)被排版侧收窄到的宽度
_PLACE_MAX_H_CM = 11.0         # 图高封顶,与 md2word._FIG_MAX_H_CM 对齐
# 排出来窄于这个宽度就算没把版面吃满(panel 档 13.7cm 刚好在线上,不误伤 2×2)
_PLACE_MIN_FILL_CM = 13.5
_MIN_RENDER_PT = 6.0           # 排版后图内字号低于此值判硬伤(明显不可读)
_MIN_AXES_IN = 1.15            # 单个面板的最小可用边长(英寸)

# 字高占画布高度的比例。学术图常态在 2%~5.5%(3.5 英寸高配 10pt 约 4%),
# 超出说明字号与画纸没按同一套尺度定:要么画布太小,要么 fontsize 是硬写的。
_TEXT_RATIO_WARN = 0.070
_TEXT_RATIO_ERROR = 0.090
_ABS_MIN_PT = 5.0              # 画布自身尺度上的绝对下限,再缩放就彻底糊了


def _lint_text_scale(fig) -> list:
    """字号与画纸是否同一套尺度——按图上实际 Text 判,不看 rcParams。

    _lint_layout_scale 读的是 rcParams,脚本里硬写 `fontsize=18` 或
    `legend(prop={'size': 16})` 它一概看不见,而这恰恰是字压字、图例吃掉半个
    面板的主因。这里按每个 Text 的实际字号除以画布高度算占比。
    """
    out = []
    try:
        h_in = float(fig.get_size_inches()[1])
        if h_in <= 0:
            return []
        items = [(t, float(t.get_fontsize())) for t in _visible_text_objects(fig)]
        items = [(t, s) for t, s in items if s > 0]
        if not items:
            return []
        h_pt = h_in * 72.0
        obj, biggest = max(items, key=lambda kv: kv[1])
        ratio = biggest / h_pt
        if ratio >= _TEXT_RATIO_ERROR:
            out.append({
                "level": "error", "code": "text_too_large_for_canvas",
                "panel": "",
                "msg": (f"图内最大字号 {biggest:.0f}pt,画布只有 {h_in:.1f} 英寸高"
                        f"(单字就占画布高度的 {ratio:.0%},常态 2%~5%):"
                        f"「{(obj.get_text() or '')[:12]}」这类文字会把图挤变形。"
                        f"删掉硬写的 fontsize,交给 plot_style.apply(base_size=…) "
                        f"统一定字号;确需大画布用 plot_style.figsize() 的档位值")})
        elif ratio >= _TEXT_RATIO_WARN:
            out.append({
                "level": "warn", "code": "text_large_for_canvas", "panel": "",
                "msg": (f"图内最大字号 {biggest:.0f}pt 占画布高度 {ratio:.0%},"
                        f"偏大(常态 2%~5%);建议交给 plot_style.apply() 定字号")})
        smallest = min(s for _t, s in items)
        if smallest < _ABS_MIN_PT:
            out.append({
                "level": "error", "code": "text_too_small_absolute", "panel": "",
                "msg": (f"图内最小字号只有 {smallest:.1f}pt(正文 12pt),"
                        f"印到纸上肉眼读不出;不要靠调小字号腾地方,"
                        f"改用 plot_style.figsize() 加大画布或减少图内元素")})
    except Exception:  # noqa: BLE001  体检失败绝不能连累出图
        return out
    return out


def _lint_layout_scale(fig) -> list:
    """画布与内容是否匹配——两头都要管。

    画布太大:排版时被等比缩小,图内文字跟着缩成蚂蚁字。
    画布太小:文字尺寸是绝对值,不会跟着缩,于是标题/轴标把轴域挤没、互相重叠
    (2×2 面板塞进 5.3×3.2 英寸就是这个下场)。后者更难看,判得更严。
    """
    import matplotlib as mpl

    out = []
    try:
        w_in, h_in = (float(v) for v in fig.get_size_inches())
        if w_in <= 0 or h_in <= 0:
            return []
        axes = [ax for ax in fig.get_axes() if ax.get_label() != "<colorbar>"]

        # ① 面板被挤没:轴域实际边长太小,再大的字也放不下
        # 面板数按位置去重:twinx 的第二根轴与主轴完全重合,是同一格,
        # 数成两个会让提示写出「装不下 4 个面板」这种对不上图的话
        n_panels = len({tuple(round(float(v), 3) for v in ax.get_position().bounds)
                        for ax in axes})
        for i, ax in enumerate(axes):
            bb = ax.get_position()
            aw, ah = bb.width * w_in, bb.height * h_in
            if aw < _MIN_AXES_IN or ah < _MIN_AXES_IN:
                tag = f"({chr(97 + i)})" if len(axes) > 1 else ""
                out.append({
                    "level": "error", "code": "axes_squeezed", "panel": tag,
                    "msg": (f"面板可用区域只有 {aw:.1f}×{ah:.1f} 英寸,"
                            f"标题与轴标会把图挤没、互相重叠。"
                            f"画布 {w_in:.1f}×{h_in:.1f} 英寸装不下 {n_panels} 个面板:"
                            f"用 plot_style.figsize(kind, rows=行数) 按行数加高,"
                            f"或干脆拆成两张图——不要靠加宽画布,"
                            f"宽度超过排版宽度会被整体缩小")})
                break

        # ② 画布过大:排版缩放后字变小。只在明显不可读时判硬伤,轻微超出给提醒
        ar = w_in / h_in
        wide = ar >= 1.8 or len(axes) > 2
        # 分档必须与 md2word._image_role_width_cm 一致,否则算出来的缩放比是假的
        place_cm = (_PLACE_ROW_CM if ar >= 2.0 else
                    _PLACE_FULL_CM if wide else _PLACE_NARROW_CM)
        # 竖图与高个子图在排版侧还要再收一道:md2word 对宽高比 ≤0.85 的图直接收窄,
        # 并给所有图的高度封顶。漏掉这两条,竖着堆的多面板算出来的缩放比是假的,
        # 「排版后字太小」这条闸门就放它过去了——实测三格竖排真实缩放只有 0.63。
        if ar <= 0.85:
            place_cm = min(place_cm, _PLACE_TALL_CM)
        # md2word 按图里写着的 dpi 反推物理宽度,画得比档位宽就照画的宽度放
        # (只放大不缩小),上限版心 16cm。这条漏了,2×2 面板算出来的缩放比是假的。
        place_cm = max(place_cm, min(w_in * 2.54, _PLACE_ROW_CM))
        if place_cm / ar > _PLACE_MAX_H_CM:
            place_cm = _PLACE_MAX_H_CM * ar
        scale = place_cm / (w_in * 2.54)

        # ③ 图占着一段版面却不把宽度吃满:版心 16cm,窄图右侧白掉近 5cm,
        # 那块空白既讲不出结论也退不回给正文。有第二类证据就并成横排组图,
        # 只有一格证据也该用 wide 档——这是「多画一点」而不是「画大一点」。
        if place_cm < _PLACE_MIN_FILL_CM:
            out.append({
                "level": "warn", "code": "narrow_figure", "panel": "",
                "msg": (f"这张图排进正文只有 {place_cm:.1f}cm 宽,版心 16cm 右侧"
                        f"白掉 {16.0 - place_cm:.1f}cm:版面本来就紧,别让一张图"
                        f"占着位置又不填满。有第二类证据(趋势/分布/残差/热图)就并成"
                        f'一行两列 plt.subplots(1, 2, figsize=plot_style.figsize("row2"));'
                        f'只有一格证据就把画布改成 plot_style.figsize("wide")')})
        pts = [float(mpl.rcParams.get(k) or 0) for k in
               ("xtick.labelsize", "ytick.labelsize", "axes.labelsize")]
        smallest = min([p for p in pts if p > 0] or [0])
        if scale < 1.0 and smallest:
            rendered = smallest * scale
            if rendered < _MIN_RENDER_PT:
                out.append({
                    "level": "error", "code": "text_too_small_after_layout",
                    "panel": "",
                    "msg": (f"画布宽 {w_in:.1f} 英寸,排版要缩到 {place_cm:.1f}cm"
                            f"(×{scale:.2f}),图内最小字 {smallest:.0f}pt 排出来只剩"
                            f"{rendered:.1f}pt,正文 12pt——小到看不清。"
                            f"宽度改用 plot_style.figsize() 的档位值")})
            elif rendered < 8.0:
                out.append({
                    "level": "warn", "code": "text_small_after_layout",
                    "panel": "",
                    "msg": (f"排版后图内最小字约 {rendered:.1f}pt(正文 12pt),"
                            f"偏小;宽度改用 plot_style.figsize() 的档位值更稳妥")})
    except Exception:  # noqa: BLE001  体检失败绝不能连累出图
        return out
    return out


# 数据指纹:最多留这么多个取值。等高线/热图动辄上万个数,全存会把记录撑爆,
# 取排序后的均匀抽样即可——判重看的是「画的是不是同一批数」,不需要逐点还原。
_SIG_MAX_VALUES = 240
_SIG_ROUND = 6


def _axes_values(ax) -> list:
    """把一个坐标区里【画进去的数值】收出来,不管它是用什么图型画的。

    判重必须看数据而不是看图型:实测 problem4.png(分组横柱)与
    problem4_comparison.png(误差点图)画的是同样五个 Sobol 指数,文件字节哈希
    完全不同、文件名也不同,只有把两边的数值都抠出来才认得出是同一张图。
    """
    from matplotlib.collections import PathCollection
    from matplotlib.patches import Rectangle

    vals = []
    box_ids = {id(box) for box in _boxplot_boxes(ax)}

    def index_like(seq) -> bool:
        try:
            clean = sorted({float(v) for v in seq if float(v) == float(v)})
        except (TypeError, ValueError):
            return False
        if len(clean) < 2 or clean[0] not in (0.0, 1.0):
            return False
        return all(abs(v - round(v)) < 1e-9 for v in clean) and all(
            abs((b - a) - 1.0) < 1e-9 for a, b in zip(clean, clean[1:]))

    def add_xy(xs, ys) -> None:
        try:
            xvals = [float(v) for v in xs]
            yvals = [float(v) for v in ys]
        except (TypeError, ValueError):
            return
        x_idx, y_idx = index_like(xvals), index_like(yvals)
        if x_idx and not y_idx:
            vals.extend(yvals)
        elif y_idx and not x_idx:
            vals.extend(xvals)
        else:
            vals.extend(xvals)
            vals.extend(yvals)

    for ln in ax.lines:
        if id(ln) in box_ids or _is_guide_line(ln):
            continue
        try:
            xy = ln.get_xydata()
        except Exception:  # noqa: BLE001
            continue
        if xy is not None and len(xy):
            add_xy(xy[:, 0], xy[:, 1])
    bars = [p for p in ax.patches if isinstance(p, Rectangle)]
    orientations = {
        str(getattr(container, "orientation", "")).lower()
        for container in (getattr(ax, "containers", None) or [])
        if getattr(container, "patches", None)}
    horizontal = ("horizontal" in orientations
                  or (not orientations and bars and _bars_are_horizontal(bars)))
    for p in bars:
        vals.append(float(p.get_width() if horizontal else p.get_height()))
    for coll in ax.collections:
        if isinstance(coll, PathCollection):
            try:
                off = coll.get_offsets()
            except Exception:  # noqa: BLE001
                off = None
            if off is not None and len(off):
                add_xy(off[:, 0], off[:, 1])
            continue
        try:
            arr = coll.get_array()
            if arr is not None:
                vals.extend(float(v) for v in arr.ravel()[:_SIG_MAX_VALUES])
        except Exception:  # noqa: BLE001
            continue
    for im in ax.images:
        try:
            arr = im.get_array()
            vals.extend(float(v) for v in arr.ravel()[:_SIG_MAX_VALUES])
        except Exception:  # noqa: BLE001
            continue
    return [v for v in vals if v == v and abs(v) != float("inf")]


def _chart_kinds(ax) -> set:
    """这个坐标区用了哪些图型(供按内容判角色,不再靠文件名猜)。"""
    from matplotlib.collections import PathCollection, PolyCollection, QuadMesh
    from matplotlib.patches import Rectangle

    kinds = set()
    if _is_3d_ax(ax):
        kinds.add("surface")
        return kinds
    box_ids = {id(box) for box in _boxplot_boxes(ax)}
    if box_ids:
        kinds.add("box")
    if any(_npoints(ln) >= 2 and id(ln) not in box_ids
           and not _is_guide_line(ln) for ln in ax.lines):
        kinds.add("line")
    if any(isinstance(p, Rectangle) for p in ax.patches):
        kinds.add("bar")
    if any(isinstance(c, PathCollection) for c in ax.collections):
        kinds.add("scatter")
    if (ax.images or any(isinstance(c, QuadMesh) for c in ax.collections)
            or any("ContourSet" in c.__class__.__name__ for c in ax.collections)):
        kinds.add("heatmap")
    if any(isinstance(c, PolyCollection) for c in ax.collections):
        kinds.add("band")
    if _has_errorbar(ax):
        kinds.add("errorbar")
    return kinds


def _distinctive(vals) -> list:
    """保留真实量值；分类轴位置与柱宽已在 `_axes_values` 按几何语义剔除。"""
    return [v for v in vals if v == v and abs(v) != float("inf")]


def _data_signature(fig) -> dict:
    """整张图的数据指纹 + 图型 + 有无不确定性。

    uncertainty 交给后端做跨源判定:results 里某个均值配了 std/CI,而画它的图上
    没有误差棒/区间带/箱体,就是漏画了不确定性。这里只报事实,不读 results——
    本文件会被复制进每个用户工作区,不能假设结果文件的路径与结构。
    """
    vals: list = []
    kinds: set = set()
    axes = [ax for ax in fig.get_axes() if ax.get_label() != "<colorbar>"]
    unc = False
    for ax in axes:
        vals.extend(_axes_values(ax))
        kinds |= _chart_kinds(ax)
        unc = unc or _has_uncertainty(ax)
    total = len(vals)
    rounded = sorted({round(v, _SIG_ROUND) for v in _distinctive(vals)})
    if len(rounded) > _SIG_MAX_VALUES:
        step = len(rounded) / _SIG_MAX_VALUES
        rounded = [rounded[int(i * step)] for i in range(_SIG_MAX_VALUES)]
    return {"n": total, "panels": len(_panel_groups(axes)), "kinds": sorted(kinds),
            "uncertainty": unc, "values": rounded}


def data_overlap(a: dict, b: dict) -> float:
    """两张图数据取值的重合度,1.0 表示其中一张的数据全在另一张里。

    用包含率(交集 / 较小那一方)而不是 Jaccard:同一批数换个图型画,两边带进的
    附加量(误差棒端点、拟合线采样点)个数不同,Jaccard 会被这些差异压下去,
    可「B 的数据全都在 A 里」本身就足以判定重复。
    """
    va = set((a or {}).get("values") or [])
    vb = set((b or {}).get("values") or [])
    if not va or not vb:
        return 0.0
    return len(va & vb) / min(len(va), len(vb))


def _figure_series_colors(fig) -> dict:
    """图里每个带名量用的颜色(量名 → #rrggbb)。

    落盘后由 check_figures 跨图比对:同一个量在两张图里颜色不一样,读者会以为是
    两回事。这件事**单张图怎么看都看不出来**,必须攒齐全套图才判得了。
    实测 md-709a9c 的「光伏出力」在 problem1_data 里是红色、在 problem3_data 里
    变成绿色——两张图都各自体检通过。
    """
    from matplotlib.colors import to_hex

    out: dict = {}
    for ax in fig.get_axes():
        if ax.get_label() == "<colorbar>":
            continue
        cands = list(ax.lines) + list(getattr(ax, "containers", []))
        cands += list(ax.collections)
        for art in cands:
            try:
                label = str(art.get_label() or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if not label or label.startswith("_") or label in out:
                continue
            color = None
            for getter in ("get_color", "get_facecolor"):
                try:
                    color = getattr(art, getter)()
                    break
                except Exception:  # noqa: BLE001
                    continue
            if color is None and len(getattr(art, "patches", []) or []):
                color = art.patches[0].get_facecolor()
            try:
                if color is not None and getattr(color, "ndim", 0) == 2:
                    color = color[0] if len(color) else None
                if color is not None:
                    out[label] = to_hex(color)
            except (ValueError, TypeError):
                continue
    return out


def _record_lint(path: str, issues: list, signature: dict | None = None,
                 series: dict | None = None) -> None:
    """把体检结果写进工程根 figures/_figure_lint.json,供 check_figures.py 汇总。"""
    import time

    root = os.path.dirname(os.path.abspath(__file__))
    fp = os.path.join(root, "figures", _LINT_FILE)
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        data = {}
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        if not isinstance(data, dict) or "figures" not in data:
            data = {"version": 1, "figures": {}}
        rec = {"checked_at": time.time(), "issues": issues}
        if signature:
            rec["data"] = signature
        if series:
            rec["series"] = series
        data["figures"][os.path.basename(path)] = rec
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except (OSError, ValueError):
        pass


def _lint_on_save(fig, fname) -> None:
    """存图时就地体检:打印到运行日志 + 落盘,智能体这才「看得见」自己的图。"""
    try:
        path = str(fname)
        if not path.lower().endswith((".png", ".pdf", ".svg")):
            return
        issues = lint_figure(fig)
        try:
            signature = _data_signature(fig)
        except Exception:  # noqa: BLE001  指纹是增强项,抠不出来不影响体检
            signature = None
        try:
            colors = _figure_series_colors(fig)
        except Exception:  # noqa: BLE001
            colors = None
        _record_lint(path, issues, signature, colors)
        stem = os.path.splitext(os.path.basename(path))[0]
        if not issues or stem in _LINTED_STEMS:
            return
        _LINTED_STEMS.add(stem)
        errs = [i for i in issues if i["level"] == "error"]
        head = f"[图面自检] {os.path.basename(path)}:{len(errs)} 处硬伤"
        # 只用 GBK 也能编码的字符:控制台不是 UTF-8 时,✗/⚠ 会抛 UnicodeEncodeError,
        # 整条自检结果被下面的 except 静默吞掉,等于白检。
        body = "\n".join(
            f"  [{'硬伤' if i['level'] == 'error' else '提醒'}] "
            f"{i['panel']}{i['msg']}" for i in issues)
        print(f"{head}\n{body}")
    except Exception as exc:  # noqa: BLE001  体检失败绝不能连累出图
        # 但绝不能【静默】失败。任何一条闸门抛异常,整张图的体检结果都会凭空消失,
        # 成图看着「全绿」其实一条都没检——这比漏检更坏,因为它伪装成通过。
        # 已经踩过两次:控制台非 UTF-8 时 ✗ 抛 UnicodeEncodeError(见上面那条注释)、
        # 多条等值线的 get_linewidths() 返回 ndarray 让 `arr or [0]` 抛 ValueError。
        # 两次都是体检早已死掉而无人知晓,所以这里必须留一句话出来。
        try:
            print(f"[图面自检] {os.path.basename(str(fname))}:体检没跑完"
                  f"({type(exc).__name__}: {str(exc)[:100]}),"
                  f"这张图等于没检,不要当成通过")
        except Exception:  # noqa: BLE001  连报错都印不出来就只能作罢
            pass


# 画布被撑到这个倍数以上,就说明还有元素飘在外面:此时宁可按原尺寸裁切保存,
# 也不要交出一张大半是空白的图。
_MAX_TIGHT_GROWTH = 1.6
_SAVEFIG_PATCHED = False


def _install_savefig_guard():
    """给 Figure.savefig 套一层收尾保护。

    脚本一般直接 `plt.savefig(...)`,不会记得调 tidy();把保护挂在 savefig 上,
    无论谁怎么写,存出来的图都不会有飘飞标注和整片空白。
    """
    global _SAVEFIG_PATCHED
    if _SAVEFIG_PATCHED:
        return
    from matplotlib.figure import Figure
    # 「原版」认准挂在 Figure 上的那一份,而不是当前的 Figure.savefig。
    # _SAVEFIG_PATCHED 是模块级的,同一进程里 plot_style 被重复 import
    # (测试用 importlib 每次新建模块实例)时它是 False,于是又包一层——
    # 上一层的闭包捕获的是**旧模块**的 _ACTIVE_PREFS,存图时按旧设置再改一遍
    # dpi,自检也会重复跑一次。认准原版就变成「替换」而非「层层套娃」。
    original = getattr(Figure, "_ms_pristine_savefig", None)
    if original is None:
        original = Figure.savefig
        Figure._ms_pristine_savefig = original

    def savefig(self, fname, **kwargs):
        try:
            tidy(self)
            # 显式实参压过 rcParams 是 matplotlib 规则,但脚本里那句 `dpi=300`
            # 是提示词教的习惯写法,不该压过用户设置。分两种情形:
            #   用户明确设过 → 按用户的数,设 150 就是要小文件,不能擅自调高;
            #   用户没设过   → 预设里的默认值当**下限**,脚本想要更高清就随它。
            # 少了后一条,默认档调到多少都白搭:每个脚本都写着 dpi=300。
            want = _ACTIVE_PREFS.get("dpi")
            if want:
                if "dpi" in (_ACTIVE_PREFS.get("_explicit") or ()):
                    kwargs["dpi"] = want
                else:
                    try:
                        kwargs["dpi"] = max(int(kwargs["dpi"]), int(want))
                    except (KeyError, TypeError, ValueError):
                        kwargs["dpi"] = want
            bbox = kwargs.get("bbox_inches", matplotlib.rcParams["savefig.bbox"])
            if bbox == "tight":
                renderer = _renderer(self)
                tb = self.get_tightbbox(renderer) if renderer else None
                if tb is not None and (
                        tb.width > self.get_figwidth() * _MAX_TIGHT_GROWTH
                        or tb.height > self.get_figheight() * _MAX_TIGHT_GROWTH):
                    kwargs["bbox_inches"] = None
                    warnings.warn(
                        "有元素飘到画布外很远,已按原尺寸保存以免整张图大半空白;"
                        "请检查 annotate/legend 的位置参数。",
                        RuntimeWarning, stacklevel=2)
        except Exception:  # noqa: BLE001  保护失败也必须能正常存图
            pass
        _lint_on_save(self, fname)
        return original(self, fname, **kwargs)

    Figure.savefig = savefig
    _SAVEFIG_PATCHED = True


def save_publication(fig, stem, *, dpi: int = 500, formats=("png", "pdf")):
    """同时保存光栅与矢量版;stem 不含扩展名(建议传绝对路径)。"""
    import os
    tidy(fig)
    out = []
    for ext in formats:
        path = f"{stem}.{ext}"
        # bbox_inches="tight":超出画布的图例/长标签一律完整保留,不做裁切
        fig.savefig(path, dpi=dpi if ext == "png" else None,
                    bbox_inches="tight", pad_inches=0.05)
        out.append(os.path.abspath(path))
    return out


def panel_labels(axes, labels=None):
    """给多面板加 (a)(b)(c) 标签(放在面板左上角外侧,不占数据区)。

    标号一度是画在数据区里的 (0.02, 0.98) 处。实测两个真实会话里,那个位置本来就
    被脚本自己的角标(「晴天 k=1.00」「缺电 8966 kWh」)占着,标号一加就和角标叠成
    一团,反被图面自检判成 7 处「标注重叠」硬伤。改用左对齐标题:约束布局会给它
    留出位置,既不压数据也不压别人的标注,也正是期刊多面板图的通行写法。
    """
    import string
    labels = labels or [f"({c})" for c in string.ascii_lowercase]
    flat = list(axes.flat) if hasattr(axes, "flat") else list(axes)
    for ax, lab in zip(flat, labels):
        ax.set_title(lab, loc="left", fontsize=11, fontweight="bold")


if __name__ == "__main__":
    chosen = apply()
    print(f"中文字体: {chosen or '未找到可用中文字体'}")
    print("字体自检:", font_report())
    print("版式设置:", resolve_prefs())
