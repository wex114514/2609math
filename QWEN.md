<!-- ms:redlines:begin -->
# 数模工坊 · 项目红线(自动生成,勿手改)

## 产物落盘位置(必须照此写,不要凭习惯改)
- 工程根:`D:\微信\竞赛\数学建模\68ada4247a9e`(你的工作目录就是这里)
- 结果图一律存到 **<工程根>/figures/**:第 N 问主图 `figures/problemN.png`,角色图 `figures/problemN_data|_diagnostic|_comparison|_sensitivity|_layout.png`
- 数值结果存到 **<工程根>/results/**:`results/problemN.json` 或 `.csv`
- 求解脚本写在 **<工程根>/src/**,临时脚本、探查脚本同样放 src/,不要在工程根随手新建 .py
- 上传数据在 **<工程根>/data/**
- 脚本里定位目录的唯一正确写法(与当前工作目录无关):
  ```python
  from pathlib import Path
  ROOT = Path(__file__).resolve().parents[1]   # src/ 的上一级 = 工程根
  FIG, RES = ROOT / "figures", ROOT / "results"
  FIG.mkdir(parents=True, exist_ok=True); RES.mkdir(parents=True, exist_ok=True)
  plt.savefig(FIG / "problem1.png", dpi=300)
  ```
- **不要写 `../figures/`、`../results/` 这类相对路径**:只有当工作目录恰好是 src/ 时它才对;你从工程根执行 `python src/problemN.py` 时,它会把图存到工程根的上一级目录,等于丢到工程外面,随后 `ls figures/` 什么也看不到。
- 存完图后自己核一遍 `ls figures/`,确认文件真的在工程内。
- **跑命令时不要 `cd` 到工程根,也不要写绝对长路径**:你的工作目录本来就是工程根,直接 `python src/problemN.py`、`ls figures/` 即可。实测里每条命令都带上 `cd "C:\Users\…\workspace\xxx" && ` 前缀,既白费 token,又是 Bash 报 `unexpected EOF while looking for matching "` 的主要来源——Windows 路径里的反斜杠和中文目录名混进引号后极易把命令截断。命令尽量单行、少用嵌套引号;要判断目录是否存在直接 `ls figures/`,不必写 `ls "绝对路径" 2>/dev/null && echo "存在" || echo "不存在"` 这种拼装。
- **plot_style.py / run_all.py / check_figures.py / merge_parts.py 是系统托管文件(在工程根),禁止在 src/ 下创建同名文件、禁止自写简化版替代**:src/ 里的同名空壳会抢在真件前面被导入,用户设置的图表版式(字体/去标题/dpi)会整个失效。`import plot_style` 报错时,正确做法是从工程根跑、或把工程根加进 sys.path,而不是造一个假 plot_style。

## 写文件策略(代码完整优先,结构化数据分片写)
- **大的结构化数据文件(.json/.yaml)一律分片写,不要用 Edit 拼括号**:整份一次 Write 容易撞载荷上限报 InputValidationError;而先写空骨架再用 Edit 往数组里追加更糟——Edit 按字符串锚点做局部替换,JSON 的括号却是全局配对的,锚点每追加一条就变一次,凭记忆构造差一个空格就报「String to replace not found」,侥幸替换成功还可能把括号弄错位(实测出现过顶层键被塞进数组内部,文件仍可解析、结构却是错的)。正确做法:每条写一个独立小文件,再跑工程根的 `python merge_parts.py`(系统托管的合并工具,用 json 库合并)——括号由库保证,写不坏,缺哪条也一目了然。
- **JSON 字符串里不写半角双引号**:中文强调用全角“”或「」。写成 `而非简单地"越大越好"` 会让整份文件解析失败,而 json 的报错只给行列号(`Expecting ',' delimiter`),不说是哪个词,很容易改到别的地方去。
- 小的结构化文件(几 KB 以内)可以一次 Write 完整落盘,不必分片。
- **论文这类长 Markdown(chapters/*.md、report.md)按小节分段写**:整章上万字连同公式表格一次 Write,超出载荷就被截断在半句上,后面的小节等于从没写过,而文件看着「写成功了」。正确做法是先 Write 落下章标题与第一个小节,后续每个 `###` 小节用 Edit 追加(锚点取上一节末尾那一整行,Markdown 的标题行唯一且不随追加而变,不像 JSON 括号那样全局配对),每次追加后 `ls`/Read 确认这一节真的进去了再写下一节。
- 代码文件可一次 Write 完整落盘;不要为了迁就写入方式删减实现或人为缩短代码。当内容接近工具载荷上限、一次 Write 已被截断/拒绝,或文件适合按职责增量编辑时,同样改用**先建后写**:先用 Write 建出模块 docstring、import 与函数骨架,随后用 Edit 按完整逻辑块补齐,每次补一个内聚函数或章节。
- 是否分段按文件类型与实际载荷决定,不按固定行数决定,也**不要靠估算字节数决定**——实测里 20KB 的方案 JSON 常被估成「大概 4-5KB,一次就能写完」,结果一次就撞上 InputValidationError。最终文件必须完整,不能把分段写入误当成代码规模上限。
- Write 必须在同一次调用里同时给出 file_path 与 content,缺一会报 InputValidationError;
- 一旦报「file_path/content 缺失」或内容像被截断,立刻改用先建后写重试,**不要原样重复同一次大写入**——重复几次只会连着失败几次。
- 每次写完顺手确认文件真的落盘(Read 或 `ls`),再继续下一步。

## 结果文件的形状(results/)
- `results/problemN.json` **只放标量与摘要统计**:最优解、极值点、误差、claim 的判定值,以及数组的 min/max/mean/argmax 这类概括量。整份控制在 30 KB 内。
- 扫描网格、Pareto 前沿、采样轨迹、时程序列这类**大矩阵改存 `results/problemN_<名字>.csv`**(或 .npz),在 JSON 里用一个字段记下文件名。写论文时每题只会读这个 JSON 的前 700 字,矩阵留在里面等于把真正的结论挤出去,正文那一节就会因为「拿不到数」而写不出结果。
- **不要复读整份结果文件**:不要 `cat`/`type` 整个 json,也不要 `python -c "print(open(...).read())"` 或 `print(json.load(...))` 整份打印——这类输出会原样进上下文,几次就把窗口顶爆。
- 要查数值,按这个顺序来:
  1. 先读 `results/_digest.md`(自动生成的规范指标摘要,≤6KB,已有结论都在里面);
  2. 摘要里没有的,只取需要的字段,例如 `python -c "import json;d=json.load(open('results/problem3.json',encoding='utf-8'));print(list(d));print(d['pareto_summary'])"`;
  3. 明细矩阵用 pandas/numpy 读对应的 csv/npz,并且**只打印统计量或前几行**,不要把整个矩阵 print 出来。

【全项目一致性·硬规则】已存在 src/config.py,但尚未冻结参数快照。公共量(基础种子与派生规则/负载档/权重等)一律 `from config import ...` 复用同名常量,禁止在各题脚本里另设不同取值。
<!-- ms:redlines:end -->
