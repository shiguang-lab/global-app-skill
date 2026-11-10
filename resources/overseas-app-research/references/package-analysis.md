# 拆包、加固识别与代码恢复

## 保全与盘点

原始 APK/APKS/XAPK 和第 4 步校验记录只读保存。分析输出、格式化代码、运行时恢复文件和临时调试副本分别存放，记录原包版本/哈希、工具版本和时间。

先运行 `scripts/inspect_package.py inventory --input <样本目录或安装归档> --out <新目录>`。它检查全部 APK 的 DEX、SO、前端资源和框架指纹，仅生成清单，不自动脱壳或反编译。Native 库常在 ABI 分包，不能只解 base.apk。

识别结果是定位线索：发现 libflutter.so、libhermes.so、WebView 资源或加固库，不等于整个 App 只有这一技术栈，也不证明相关 SDK/分支当前启用。

## 恢复路径

| 类型/现象 | 优先动作 | 不能据此得出的结论 |
|---|---|---|
| 普通 DEX | 用现有 JADX 反编译；结合 Manifest、资源 XML 和调用点定位 Activity/Fragment、ViewModel、导航与 Bridge | 某类搜索不到不等于该业务不存在 |
| 主 DEX 很小、只见壳初始化/加载器 | 记录壳线索，运行原 App 观察业务加载；在任务环境恢复加载后的业务 DEX，再反编译和核对 | 初次 JADX 输出只有壳不等于完整业务已分析 |
| Hybrid/H5 | 从原生路由/Bridge/日志/实际 WebView 取得真实文档、JS/CSS、动态 chunk、字典和配置；保存 URL、时间、哈希 | APK 中没有 H5 或官网首页能打开，不等于 App 不使用远程 H5 |
| Flutter | 查 flutter_assets、NativeAssets/字体/配置、libapp.so 与 libflutter.so；AOT 需要匹配 SDK/架构的分析工具（本机曾使用 Blutter） | JADX 主要展示宿主/插件，不能当成 Dart 业务源码；工具不支持时如实标出 |
| React Native/Hermes | 找 JS bundle 和动态包，结合原生 Bridge 与 Hermes 库；按实际 bundle 格式选择工具，必要时在原运行时观察服务和状态模型 | 二进制 bundle 不是空业务；Native API 触发不等于外部 UI 已出现 |

JADX 可使用 `jadx -d <新目录> <APK或恢复DEX>`，以本机实际工具 `--help` 为准。查看反编译警告和关键函数的完整控制流；出现错误时结合原字节码/调用点复核，不把伪代码当无条件可信源。

运行时 DEX 提取与分析副本属于有证据的条件路径，不对所有 App 盲试一套“通用脱壳”。workspace 中曾用 Java JDI/JDWP 观察已加载类与 ClassLoader 的 DexFile，并恢复运行时 DEX。具体对象布局、mCookie/指针偏移依 Android/ART 版本变化，不能复制历史偏移作为新设备事实。先检查当前运行时和工具匹配；遇到崩溃保留日志，换有依据的方法，而不是反复猜偏移。

## 调试副本与原始实现一致性

需要开启调试能力时只对分析副本操作，在任务专用、已授权模拟器使用。允许的本地副本差异应明确记录，例如 Manifest 的 debuggable 与本地签名；DEX、SO、JS/CSS、布局和图片保持原字节。

使用 `scripts/inspect_package.py compare --original <原APK> --copy <调试副本APK> --out <新目录>` 比较 ZIP 条目。对全部 split 分别比对；所有安装 split 必须使用同一套测试签名。返回 0 / `passed` 表示条目比对通过且 Manifest 原字节未改；返回 1 表示出现不允许的差异；Manifest 有变化而其他业务载荷一致时返回 2 / `requires_manifest_review`，不能据此直接认定副本一致。签名变化不证明原签名/服务端信任仍然成立。

### Manifest 语义验收

对返回 2 的每个 split，使用实际 SDK 的 `aapt dump xmltree <APK> AndroidManifest.xml` 分别保存原包与副本的输出，逐节点/属性核对；二进制偏移、字符串池顺序不当作语义变化。明确列出计划中的调试属性差异（如 `android:debuggable`），再检查 Activity/别名/导航入口、intent-filter、权限、组件导出、SDK 条件、网络安全配置与元数据等是否被意外改变。

在任务已有复核记录中关联两份 APK 哈希、条目比对报告、两份 Manifest 输出、实际语义差异及结论。只有差异均属于事先记录的调试能力变更、无关语义未改变时，agent 才可记录“副本一致性通过”并继续使用；语义一致但二进制重排也须记录依据。不符合计划的导航/权限等变化须修正副本再比对；工具或证据缺失则记录一致性未完成，不能用改状态或跳过检查放行。此复核由 agent 执行，不新增逐项用户审批。

历史 `debug_webview_apk.py` 使用针对当时二进制 Manifest 的字符串替换，带有编码/长度等假设；不能原样用于任意 APK。`start_ui_audit_session.py` 还固定了工具路径、设备、权限、卸载行为和测试密钥；只提炼方法，不直接当通用执行器。用户个人/共享设备的卸载、清数据、覆盖安装仍需相应授权。

## 初步页面、入口与状态索引

业务调研与 UED 均按 [共用页面发现与图片提取](ui-extraction.md) 建立候选与唯一页面事实源。下面是恢复阶段的输入线索，任务范围/入口种子与 H5 动态路由扩展统一由共用模块处理；纳入的动态项目不按业务主线过滤其路由截图。从恢复资源中列出：

- 启动 Activity、原生页面、WebView 宿主、Deep Link、Bridge 方法、H5 路由、菜单/按钮入口。
- 接口路径与方法、请求/返回合同、状态码、枚举、灰度开关、用户标签、草稿/缓存与跳步条件。
- 相应字段和校验、权限触发点、SDK 调用入口与返回处理。
- 页面当前入链证据：由用户入口引用、条件路由可达、仅保留资源，或暂未找到入口。
- 后端/配置页面地址的数据来源、导航消费点、路由表/动态注册与懒加载资源；动态 H5 的全部路由集合或固定入口使用闭包及范围未知项。

“有页面组件”“有路由”“当前默认用户可达”分别记录。按文件、函数、行号/符号及哈希引用证据；美化后的行号要指向美化文件，原始快照也要保留。

## 在线 H5 快照

原生和 H5 可能独立更新。保存本次实际加载资源及其版本哈希；格式化前先算 SHA-256。有 sourcemap 可利用，但先核对其对应当前脚本。动态加载的 chunk 与远程字典不能只抓首个 index.js。

workspace 的复核曾使用 WebView DevTools `Debugger.getScriptSource` 对照本地脚本哈希，防止拿另一版本代码审核当前页面。浏览器直接访问的资源应标为该浏览器快照，只有比对后才能声称与 App 当前加载版本一致。
