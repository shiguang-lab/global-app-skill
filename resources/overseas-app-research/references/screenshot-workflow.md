# 截图与长图操作

由 [共用页面提取模块](ui-extraction.md) 调用，服务业务调研与 UED 的第 8 步采集、第 9 步复核和第 10 步图册检查。待采集页面、状态、路由覆盖及来源使用该模块的唯一清单，本文件只负责成像、拼接和图片验证。可滚动页面/弹层必须交付从顶部到底部的完整长图；单屏页面保留未经裁切、缩放的原始 PNG。拼接结果只能使用原帧像素，不重绘、拉伸、填充或补造内容。

## 1. 确定页面状态和实际滚动容器

沿用共用清单的页面/状态 ID，记录 App/版本、serial、前台 Activity、WebView URL（如适用）、数据模式与原帧路径。普通内容页确认已加载且键盘/非目标弹窗未遮挡。若加载态、错误态、键盘或弹层本身就是目标，按原实现和实际 fixture 确认该状态已渲染后截图，不要求先变成加载完成的内容页；仍不能把该图当作内容页截图。

通过 UI hierarchy、实际手势和当前可调试 WebView 的 DOM 定位真正滚动的区域，包括内部表单和弹层。记录像素边界、固定标题栏/底栏、顶部和末尾的可辨认控件。WebView 应读取实际元素的 `scrollTop`、`clientHeight`、`scrollHeight`，不能只检查 `window`。原生则结合实际内容移动、首尾控件和可用的滚动事件/层级信息确认。

回到容器顶部再拍第一帧。单屏判定必须有内容范围或对正确容器执行有效滚动的证据；一次手势无效不证明单屏。多个独立滚动容器分别采集，不能把不同容器或不同业务状态拼成一张连续页面。固定在内容区中部的控件、横向滚动、多列独立滚动等不符合下述单一纵向平移模型时，另按实际结构取证；未完成完整长图须明确标记受限。

## 2. 逐帧采集并确认到底

下面命令在 skill 目录运行。先将 `RESEARCH_SERIAL`、`RESEARCH_CAPTURE_DIR` 设置为已选 serial 和本页面/状态的**新建绝对目录**；`RESEARCH_X`、`RESEARCH_Y_FROM`、`RESEARCH_Y_TO` 依据当前实际容器设置，全部落在容器内部。上滑的起点 Y 大于终点 Y。不复用历史坐标。

先检查当前 Python 有 Pillow：`python3 -c 'from PIL import Image; print(Image.__version__)'`。缺失时按本任务工具授权在用户目录/任务虚拟环境补齐，记录实际使用的 Python；不把依赖缺失记为已完成采集或拼接。

```sh
: "${RESEARCH_SERIAL:?设置实际设备 serial}"
: "${RESEARCH_CAPTURE_DIR:?设置本页面的新绝对采集目录}"
mkdir -p "$RESEARCH_CAPTURE_DIR"

# 保存 adb 原始 PNG 字节；原帧存在则拒绝覆盖。
capture_frame() {
  python3 - "$RESEARCH_SERIAL" "$1" <<'PY'
import io
from pathlib import Path
import subprocess
import sys
from PIL import Image
data = subprocess.run(["adb", "-s", sys.argv[1], "exec-out", "screencap", "-p"],
                      check=True, stdout=subprocess.PIPE).stdout
with Image.open(io.BytesIO(data)) as image:
    if image.format != "PNG":
        raise ValueError("设备未返回 PNG")
    image.verify()
with Path(sys.argv[2]).open("xb") as output:
    output.write(data)
PY
}

# 在确认顶部且页面稳定后执行。
capture_frame "$RESEARCH_CAPTURE_DIR/frame-000.png"

: "${RESEARCH_X:?设置容器内横坐标}"
: "${RESEARCH_Y_FROM:?设置上滑起点}"
: "${RESEARCH_Y_TO:?设置上滑终点}"
adb -s "$RESEARCH_SERIAL" shell input swipe \
  "$RESEARCH_X" "$RESEARCH_Y_FROM" "$RESEARCH_X" "$RESEARCH_Y_TO" 350
# 重新观察前台、页面状态、加载和回弹是否稳定，再执行下一行。
capture_frame "$RESEARCH_CAPTURE_DIR/frame-001.png"
```

按“上滑 → 观察稳定 → 截下一帧”重复，每帧使用新编号。每次实际内容位移控制在容器可视高度的约 50%–60%，相邻原帧至少保留约 30% 的可辨认重叠内容；手势位移不等于实际滚动位移，以原帧为准。记录手势、帧顺序、容器边界和可用滚动位置；不能按固定 sleep 后就假定加载完成。

到底时，在同一正确容器内再做两次上滑并分别保存 `bottom-probe-01.png`、`bottom-probe-02.png`，确认内容位置不再变化、末尾控件完整可见、没有继续加载。WebView 可补充 `scrollTop + clientHeight >= scrollHeight - 1` 的当前元素记录。重复帧本身不证明到底，还须排除手势失效、嵌套容器、回弹和待加载。保存这些探测帧用于完整性复核，**不要把无新内容的探测帧加入拼接列表**。无限列表或无法证明终点的页面标记范围/完整性受限，不声称完整长图已完成。

## 3. 拼接

脚本需要 Pillow，不需要 NumPy/OpenCV。坐标均使用原图像素：`top` 含该行、`bottom` 不含该行，二者包围实际发生纵向平移的内容；顶部固定栏仅取首帧、底部固定栏仅取末帧。`match-left/right` 只限定重叠匹配范围，最终仍保留原始全宽；范围应覆盖可辨认的主体内容，仅排除已核实的侧边滚动条等非内容变化，不能只选空白小块以求匹配成功。

先用原帧确定 `RESEARCH_TOP`、`RESEARCH_BOTTOM`、`RESEARCH_MATCH_LEFT`、`RESEARCH_MATCH_RIGHT`、`RESEARCH_MIN_OVERLAP`；最小重叠行数至少为内容区高度的 30%。`RESEARCH_STITCH_DIR` 是新的拼接尝试目录，不能与原帧目录相同，也不能已存在。下面两帧仅示范参数写法，实际必须按顺序显式列出本页面**全部有效滚动原帧**，不能用包含探测帧/其他状态的通配符。

```sh
: "${RESEARCH_TOP:?设置滚动内容起始行}"
: "${RESEARCH_BOTTOM:?设置滚动内容结束行}"
: "${RESEARCH_MATCH_LEFT:?设置主体匹配区左边界}"
: "${RESEARCH_MATCH_RIGHT:?设置主体匹配区右边界}"
: "${RESEARCH_MIN_OVERLAP:?设置至少30%内容高度的重叠行数}"
: "${RESEARCH_STITCH_DIR:?设置新拼接尝试目录}"
python3 scripts/long_screenshot.py stitch \
  --frames "$RESEARCH_CAPTURE_DIR/frame-000.png" "$RESEARCH_CAPTURE_DIR/frame-001.png" \
  --top "$RESEARCH_TOP" --bottom "$RESEARCH_BOTTOM" \
  --match-left "$RESEARCH_MATCH_LEFT" --match-right "$RESEARCH_MATCH_RIGHT" \
  --min-overlap "$RESEARCH_MIN_OVERLAP" --out "$RESEARCH_STITCH_DIR"
```

成功输出 `long.png`、`stitch.json`、最新 `verification.json` 及 `verification-history/` 中的逐次复核记录。脚本按 RGB 原像素逐行匹配；只有唯一的连续重叠位移才拼接，不采用近似匹配或缩放。记录每对原帧位移、重叠行数、匹配误差（成功时为 0）、每个输出段的源帧/源行/输出位置、原帧和长图 SHA-256。输出高度应为首帧高度加所有有效位移之和。

## 4. 校验与完整性复核

```sh
python3 scripts/long_screenshot.py verify --manifest "$RESEARCH_STITCH_DIR/stitch.json"
```

退出码 0、`status=passed` 只证明源文件/输出哈希一致、重叠位移唯一、输出每段逐像素来自所记录的原帧。脚本明确保留 `coverage=requires_top_bottom_and_container_review`，不能据此声称页面已经采全。

每次 `verify` 成功或失败都会更新最新 `verification.json` 并追加历史，记录时间、Manifest 哈希及实际观察到的原帧/长图哈希（缺失时为空）。验收和续跑使用当前文件对应的最新结果；`stitch.json.status=stitched` 只表示曾生成拼接图，不能覆盖之后的失败复核。历史 `passed` 只证明当时的输入，不能用来放行已变化的文件。

另外打开实际长图，过长时分段放大查看原始分辨率，逐接缝核对文字、输入框、段落和控件没有缺失/重复；核对顶部、末尾、固定栏只保留一次，且所有帧属于同一版本/业务状态/容器。对照首帧和末帧及到底探测、DOM/原生滚动证据确认覆盖范围；在现有第 9 步复核记录中登记像素校验和完整性复核各自结论。两者均通过才标记“完整长图完成”。单屏页直接关联原始截图及其 SHA-256，不拉长、不拼接。

## 5. 失败处理

脚本失败返回非零；新建拼接目录后发生的错误写入 `stitch.json` 的 `status=failed` 与具体 `error`，原帧只读。依赖缺失、输出目录已存在等启动错误直接见 stderr；也要记录到本页面复核记录。失败后的 `long.png`（如有）不能作为通过校验的交付图。

| 错误/现象 | 下一步 |
|---|---|
| `NO_EXACT_OVERLAP` | 检查帧对、固定栏边界、动态内容和状态变化；用较小滚动重新补拍。不能降低可靠性标准来制造通过 |
| `AMBIGUOUS_OVERLAP` | 空白或重复内容无法唯一定位；补有可辨认锚点且保持重叠的原帧，仍无法唯一定位则保留原帧并说明限制 |
| `NO_SCROLL_MOVEMENT` | 检查是否混入到底探测帧、手势失效或重复内容；只有已证明无新内容的探测帧才能从拼接列表排除，文件仍保留 |
| `SIZE_CHANGED` / `INVALID_REGION` / `INSUFFICIENT_OVERLAP_REQUIREMENT` | 核对旋转、分辨率、实际滚动区域和至少 30% 的重叠要求；重新采集或基于证据修正参数，不缩放原帧 |
| 哈希/像素校验失败 | 检查源文件或长图是否被改动，保留失败记录并从未修改原帧生成新的尝试目录 |
| 动态控件、悬浮遮挡、无法确认到底 | 等待稳定或重新采集；工具无法可靠恢复时明确说明遮挡/动态/终点限制，不修图填缺口 |

在正文进度和最终交付的受限项中明确页面/状态、失败帧对、原因、已做修正与未覆盖范围。始终保留全部原帧（含探测帧和失败尝试）、采集操作及匹配日志；报告可按顺序展示原帧，但必须标记“长图未完成”，不计入已完成长图。
