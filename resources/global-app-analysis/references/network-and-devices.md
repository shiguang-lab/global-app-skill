# 网络、账号、工具与设备

## 设备选择顺序

第 1 步只读盘点设备并判断环境门槛，不按 ADB 返回顺序自动选机。第 2 步明确目标包与版本要求后，在实际导出、安装或运行前按以下顺序选择：

1. **用户指定优先**：遵从用户对当前动作指定的真机、模拟器或 serial，已有指定不重复询问。指定设备不可用或不能满足目标时，说明具体阻塞；已有备用设备授权则按授权继续，否则只询问必要的修复或换机选择，不静默换机。
2. **未指定，只读导出 APK**：在已连接、已授权且可响应的设备中，优先复用已安装目标 App 且满足版本要求的设备，真机和模拟器不另排先后。不为导出启动 App、重新安装或清除数据；没有合适已安装样本则继续下载子流程。此规则只决定设备导出路径内的选机，不改变本地归档等取包渠道顺序。
3. **未指定，安装运行、Mock 与 UI 走查**：默认使用任务专用模拟器。先复用匹配 SDK/ABI、满足所需服务且不占用其他任务的在线实例，再按需启动已有完整、适合本任务的 AVD，并核实 ADB shell 可响应。真机已连接或已安装目标 App，不会因此越过模拟器成为默认运行设备。
4. **模拟器受限时再用真机**：有证据表明模拟器存在 ABI/SDK、应用或 SDK 的兼容性限制，或本次验证需要其无法提供的真实相机、传感器、SIM 等能力时，记录依据并选择能满足要求的真机。仅有登录、网络或空白页面不足以判定反模拟器，先按 [运行故障分类](runtime-and-mock.md) 定位原因。没有可用任务专用模拟器且没有可启动的合适完整 AVD 时，记录环境可用性限制后也可使用已授权真机；不为满足默认偏好自动安装新模拟器。

取包设备和运行设备分别记录。第 3 步设备相关渠道先记录实际取包 profile（ABI、SDK、密度），与预期运行条件分别核对。跨设备运行不适配时，按 [关联取包规则](download-workflow.md#任务级尝试记录与去重) 以新 profile、原尝试 id 和证据理由重新获取；保留历史/搜索预算，不因样本来自真机就直接改用真机运行。多个候选满足当前规则时复用本任务已选设备；只有差异影响结果且无法从请求确定时才询问。

首次选机或换机时，在正文说明用途、设备类型、serial 和选择依据，证据记录关联实际设备。设备选择不扩大操作授权；个人/共享真机的新安装、升级、覆盖及数据处置仍遵循现有授权规则，已有授权不重复请求。

### 启动已配置的 AVD

设备门槛通过只表示“有完整 AVD 可准备启动”，不等于它一定能启动。启动前先看 `preflight` 给出的 `directory`、`directory_writable` 和 `snapshot_state`：

1. `directory_writable=false` 时不要启动。模拟器启动会更新或删除 `bootcompleted.ini` 等快照标记；当前会话写不进 AVD 目录时，日志会先是 `WARNING | Deleting .../bootcompleted.ini failed`，随后 `FATAL | A snapshot operation for '<名字>' is pending and timeout has expired.`。这是权限问题，不是镜像损坏、也不是 AVD 锁坏了。按 `AVD_NOT_WRITABLE` 报出的路径交用户处理：在其自己的终端启动该 AVD，或授予写权限后重跑第 1 步。
2. 需要自己启动且确实有写权限时，用已有 AVD、保留原快照，并让输出可回收：

   ```sh
   emulator -avd <已有AVD名> -no-snapshot-load -no-boot-anim
   adb -s emulator-5554 shell getprop sys.boot_completed
   ```

   `sys.boot_completed=1` 后才能在正文说该 AVD 已在线，并把 `boot_verified` 记为 true；`emulator-5554` 只是示例，以实际 serial 为准。命令要作为后台任务运行并保留日志，不要阻塞主流程；启动失败保留原始 `FATAL`/`WARNING` 行作为证据。

3. 用户已在自己终端启动的 AVD 只通过 `adb -s SERIAL` 交互：不要从受限会话 `kill`、重启或替换它，杀进程后本会话起不回来，只能再请用户启动。收尾时保持它在运行并明确说明交还，不主动关闭。
4. 快照可疑（`snapshot_state.artifacts` 含 `bootcompleted.ini`/`snapshots` 且上次未正常退出）时，加 `-no-snapshot-load` 冷启动一次即可；不要删除快照目录，也不要 `-wipe-data`。
5. 不要为了绕过权限去新建 AVD：新 AVD 用同一镜像但没有快照，冷启动更慢、更占磁盘，原有设备状态也不在。已有合适 AVD 存在时，换 AVD 只能由用户决定或在 AVD 确实不满足 ABI/SDK/服务要求时按第 3 条规则换。

## 网络盘点与 VPN

主流程第 1 步先运行 `python3 scripts/preflight.py --country PH --report <任务目录>/environment.json`（国家按已知目标替换，未知可省略）。先检测 SDK、ADB 设备和 AVD 配置/镜像，并对每个 AVD 目录做一次创建即删除的写探测，判断当前会话是否真能启动它；没有可响应的已授权设备、也没有当前会话可写的完整 AVD 则返回 4 并立即中断，VPN/代理等后续检查跳过。除这个探测文件外不写 AVD 目录，也不切换网络或启动模拟器。通过设备硬门槛后才只读盘点环境代理、macOS 系统代理、VPN 客户端与已知 controller。Python 要求 3.9+。

正文分别报告工具检测、设备门槛、VPN/代理盘点结果。设备/AVD 不存在、目录不可写（`AVD_NOT_WRITABLE`）与权限未就绪应保留明确错误；不能为了继续下载临时忽略这个失败。完整 AVD 的 `boot_verified=false` 意味着尚未实际启动验证，不能说它已在线；`directory_writable=false` 则连启动都不应尝试。

节点发现按以下顺序：

1. 已知客户端优先。历史“鹿语云”通过 Clash Verge Rev 客户端使用，bundle ID 曾为 `io.github.clash-verge-rev.clash-verge-rev`；先确认本机实际客户端，不把“鹿语云”当固定进程名。
2. 有连接器/已授权客户端工具则读取节点。否则通过客户端 UI 读取当前策略组、选中节点及目标国家候选。
3. 已从客户端设置/现有配置确认本地 Clash/Mihomo controller 时，可执行：

   ```sh
   python3 scripts/preflight.py --country PH --controller http://127.0.0.1:9090
   ```

   `9090` 只是示例，不能盲猜本机端口。需要 secret 时使用 `--secret-env <已有私密环境变量名>`；不要把 secret 放命令行、聊天或归档。脚本仅对 loopback 发出 `GET /proxies`，不调用变更接口。
4. 区分“节点名字匹配国家”与“当前请求出口确在该国家”。节点名、全局组选中值都不能证明请求已经过它。

有候选时，先记录当前组/节点、系统代理或 TUN 状态、脚本代理、模拟器代理；向用户提出具体变更，例如：

> 当前策略组为 A、节点为 B；发现“菲律宾 X”节点。下载请求需要菲律宾出口，是否临时切换该组到此节点？这会影响使用该组的网络请求，完成后恢复 B。

已有用户授权涵盖这一切换则无需再次询问。用户拒绝或无可用节点，继续不依赖切换的渠道。不要替用户改订阅、账号国家或购买 VPN。

执行获准变更后，用同一请求路径核查 HTTPS 连通性与出口国家。可用用户已接受的 IP 地理服务或目标服务证据；调用外部 IP 服务会向该服务暴露当前出口，避免发送其他身份数据。不能只测宿主机浏览器，就声称模拟器或 Python 也走了同一出口。

脚本 `--proxy http://127.0.0.1:<实际端口>` 仅影响该脚本；省略时 urllib 使用环境/系统代理，`--proxy direct` 强制直连。HTTP 代理端口、SOCKS 端口、controller 端口不同。stdlib 下载器不提供 SOCKS 支持，有 SOCKS-only 线路时使用客户端现成 HTTP 入口或其他已安装且支持 SOCKS 的工具，不把 SOCKS URL 当 HTTP 代理传入。

模拟器的 `127.0.0.1` 指模拟器自己；Android 官方 Emulator 访问宿主机常用 `10.0.2.2`，其他虚拟化环境要先确认。设置设备全局代理前读出原值；它也是设备网络变更，须在用户批准范围内。不要为可用的脚本代理额外修改设备代理。

无论成功/失败均在本次临时网络变更结束时恢复原状态。若用户在执行中自行改变了设置，不覆盖其新选择，应说明差异并协调恢复。恢复失败应报告当前残留状态。敏感会话、匿名令牌和带签名直链不写入共享报告。

## 工具依赖

| 能力 | 必需依赖 | 缺失时 |
|---|---|---|
| APKPure/Aptoide/已知直链 | Python 3.9+ 标准库、可用 HTTPS 路径 | 先处理连接；不为此安装大型第三方包 |
| APK 身份与签名校验 | Android SDK Build Tools 中的 aapt、apksigner；可运行的 Java | 优先现有 SDK 与 Android Studio JBR；缺工具时输出未完成校验，不降级成成功 |
| 真机/模拟器导出 | adb、已授权 device 状态 | 复用现有 platform-tools；unauthorized 交用户确认调试 |
| Google Play 模拟器取包 | ABI/SDK 匹配的 AVD、带 Google Play 的镜像、商店登录和应用可用性 | Google APIs 镜像不等于带 Play Store。优先已有合适 AVD，禁止 wipe-data 或修改无关 AVD |
| 匿名 Play getItems/delivery | 当前协议支持的设备 profile、已注册匿名 device ID；versionCode 可由 getItems 自动查询 | 先复用任务已有私密会话/工具生成记录；缺少时使用官方 Aurora 客户端或维护中的 GPlayAPI 工具完成注册，不伪造 device ID |

工具安装先查现有路径（PATH、ANDROID_HOME、ANDROID_SDK_ROOT、常见 SDK 目录）。第 1 步设备/ADB 硬门槛失败时，本次调研直接中断，环境修复须另按用户请求执行。门槛已经通过而某渠道缺小型用户目录工具时，可按任务授权补齐；涉及 sudo、系统级配置、大型系统镜像、新服务条款或显著下载时，先把具体组件、位置、大小/代价说明给用户。不要通过安装另一整套 SDK 解决 PATH 问题。

## 匿名下载的实际边界

匿名下载来源仍是 Google Play。`download.py play` 使用已有配套 profile 和已注册 device ID，以 `X-PS-RH` 请求 Google 的 `/fdfe/getItems` 自动取得匹配包名的 versionCode，再请求 `/fdfe/delivery` 并下载全部返回文件、核对提供的摘要；不需要个人 Google 账号或 Aurora dispenser token。`/fdfe/details` 是账号路径，其 401 不能判定匿名链路失败；dispenser 403 也不应阻止已有注册设备的 getItems/delivery。

脚本不会创建账号、注册设备或接受条款。输入：

- `--device-profile`：实际工具生成的 JSON，包含 Build.VERSION.SDK_INT、Build.ID、Build.VERSION.RELEASE、Build.DEVICE、Build.HARDWARE、Build.MODEL、Build.BRAND、Build.PRODUCT、Build.FINGERPRINT、Vending.versionString。
- `--device-id-file`：与 profile 配套的已注册匿名设备 ID（十进制整数）。从已有资料或注册工具生成，不随机伪造；私密输入仅当前用户可读。
- `--version-code`：可选，只有需要确切版本时提供；省略时脚本实际调用 getItems 查询，不猜测、不将 versionName 转数字。
- `--country`、`--language`：目标地区；仅改参数不保证绕过发行限制。

已有输入先执行完整匿名链路。缺注册设备时按当前上游协议/官方 Aurora 客户端补齐，不要求用户手写 token；确实无法补齐时记为 dependency_missing，而非下载失败。getItems 成功仅证明详情可取，必须继续 delivery 与文件落盘才算取包成功。匿名请求异常时分别记录端点、HTTP/业务结果和未完成步骤；基于新协议证据做有界纠错，不重复错误接口。

历史本机成功输入在 `~/Downloads/philippines-lending-apps/tools/`，仅作为本机可选复用线索；skill 不依赖该目录，不打包其中的 ID/会话文件。新机器缺输入且当前工具不能注册时，这条路径记为“依赖未就绪”，继续其他渠道，不停在要求用户提供 token。

## 模拟器 Google Play 与真机导出

1. 列出设备：`adb devices -l`；按 [设备选择顺序](#设备选择顺序) 选定本次取包设备，每次命令明确 `adb -s SERIAL`。可只读检查目标包 `shell pm path PACKAGE`。
2. 已安装则直接导出，不必先启动目标 App，不访问其私有数据。用户要求导出 APK 不等于授权导出账号、数据库或业务缓存。
3. 未安装且准备使用任务模拟器时，检查 `ro.product.cpu.abilist`、`ro.build.version.sdk`、Play Store 是否存在及剩余空间；打开已确认包名的商店页：

   ```sh
   adb -s SERIAL shell am start -a android.intent.action.VIEW -d 'market://details?id=PACKAGE' -p com.android.vending
   ```

   上面 SERIAL/PACKAGE 是参数占位；实际执行前替换，不能把占位串当命令运行。
4. 真实账号登录、二次验证等所需输入由用户完成；任务专用环境的常规同意按 [主工作流](guide.md) 连续执行规则处理。用户登录后重新观察实际状态，不以回复“好了”推断安装完成。不收集密码，不自动迁移 Play 账号地区。
5. 免费 App 在已选任务专用模拟器中安装属于取包必要步骤；个人/共享真机的新安装、升级、覆盖需要明确设备修改授权。用户已有相同授权则继续。
6. 商店提示国家不可用时分别检查账号地区与请求出口。菲律宾 VPN 不能自动改变中国区 Play 账号；不要清除 Play/目标 App 数据试错。用户可选择已有合适账号，或改走匿名/镜像。
7. 安装结束后重新查询 `pm path`，运行导出脚本；安装画面完成不等于本机已取得 APK。所有 `base.apk`、ABI、密度、语言及功能 split 都应保存。

   ```sh
   python3 scripts/export_device.py --serial SERIAL --package PACKAGE --out /absolute/sample-dir
   python3 scripts/verify.py --input /absolute/sample-dir --package PACKAGE
   ```

导出脚本只执行设备读取与 `adb pull`，逐文件比较设备和电脑 SHA-256，并复查安装路径集是否改变。它不安装、不启动、不卸载 App。脚本失败时保留不完整目录和明确失败状态，重新导出使用新目录，避免混合样本。
