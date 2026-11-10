# 校验与交付

## 成功条件

“已获取”要求：文件实际落盘、不是 HTML/安装器、归档 CRC 通过、APK 包名与要求一致、所取分包版本一致、APK 签名有效且分包签名者集合一致。指定版本还要比对实际 versionCode。工具缺失时状态为 `incomplete_verification`，不能标“已校验成功”。

用户目标版本保存为取包记录的 `requested_version_code`，与渠道声明的 `source_version_code` 分开。所有下载渠道和设备导出支持 `--version-code`，校验目录时自动承接记录；显式校验版本与记录冲突则失败。没有关联取包记录的本地样本必须显式传目标版本，不能由文件名或渠道声明推断。

签名有效仅证明签名与文件一致；镜像提供的证书一致也不是独立官方认证。只有与独立 Google Play 安装样本、开发者发布证书或用户提供的可信基准比较后，才声称“签名与该官方基准一致”。证书轮换引起差异时保留证据、核查 lineage，不自动接受差异或重签。

## 校验顺序

1. **来源与传输**：记录查询/下载时间、包名、渠道、实际版本、文件名、大小、SHA-256、来源摘要是否提供及比对结果。下载脚本核对来源 MD5/SHA-256、精确大小（有提供时）与 ZIP CRC；不关闭 TLS 证书校验。
2. **保留与解包**：保存原始 APK/APKS/XAPK/ZIP。只提取 APK 成员，拒绝路径穿越/同名覆盖；对每个 APK 再查 ZIP CRC 和 AndroidManifest.xml。XAPK 的 OBB/资源包留在原始归档，不能据“APK 已取出”声称所有运行资源齐全。
3. **Android 身份**：通过 `aapt dump xmltree` 读取每个 APK 的 package、versionCode、versionName、split identity。恰好一个无 split 的主包；包名与要求一致、版本一致、split identity 不重复；Manifest 声明的 requiredSplitTypes 也需由当前分包满足。直接读取 Manifest，避免主包图标/标签引用分包资源导致 badging 报错。来源文件名不作身份依据。
4. **签名**：逐个 `apksigner verify --verbose --print-certs`，保存输出并比对 SHA-256 证书集合。命令报错或 Java 缺失不能跳过后仍标成功。
5. **分包清单**：API 已声明文件和设备 `pm path` 返回文件均须完整取回；对照下载清单再次算哈希。只取 base.apk 不算完成 split 应用取包。不在不同版本、不同来源之间补拼 ABI/资源包。
6. **安装/启动（需要时）**：根据 ABI/minSdk/密度选设备；分包使用 `adb -s SERIAL install-multiple ...`，单包用 `install`。先检查已装版本，禁止通过卸载、降级、重签或清数据来掩盖安装失败。个人真机修改须符合已获授权。
7. 安装后用 `dumpsys package`/`pm path` 核实版本。只有实际启动并观察到界面/进程后才写启动成功；Play 商店安装成功不代表登录或核心业务可运行。

```sh
python3 scripts/verify.py --input /absolute/sample-dir --package com.example.app --version-code 123
```

可直接传 APK/APKS/XAPK/ZIP，脚本用临时目录解出 APK，并将报告与工具证据保存在输入文件旁边。单文件只有被其父目录或上一级目录的取包记录实际列为产物时，才承接其中的目标版本及来源清单检查；直接传 `apks/` 时同样检查父目录记录是否列出了其中 APK。不会套用无关的相邻记录。split 应用优先传完整样本目录，单独验证 base 不满足已声明分包集合。`--reference-cert` 只接受已独立获得的签名证书 SHA-256。

退出码：0 为文件身份/签名等已执行检查通过；1 为检查失败；2 为工具缺失导致检查未完成。`verified` 不证明最新版、官方来源、安装可用或所有按需模块齐全；报告的这些维度必须分别读取。

## 产物约定

每个下载渠道/版本单独目录：

```text
<package>/<version-or-attempt>/
  raw/                         下载的原始 APK/APKS/XAPK/ZIP（设备导出可无此目录）
  apks/                        可分析/安装的主包及全部已获取 split
  download.json                渠道、版本、来源清单、哈希与真实完成状态
  verification.json            包名、版本、CRC、签名、分包一致性及未完成项
  verification-details/        aapt 与 apksigner 实际输出
```

以上文件由脚本生成；浏览器/手工取包时按相同含义记录来源清单再校验。不同来源重复包可在比对哈希后复用，保留各自来源记录。记录完整来源页面和不含凭证的 API 参数；带签名的短效下载 URL 只保存域名/路径去查询参数，匿名 token、Cookie、controller secret 不入交付。

任务级 `attempts.json` 用于所有渠道的去重和最多 3 轮 Web Search 预算；使用 `scripts/attempts.py` 登记，继续同一目标时保留原文件。脚本状态与具体原因分开：例如 status=failed，reason=no_candidate/http_403/tls_error/region_restricted；登录/验证码等待用 waiting_user。校验失败将原 downloaded 尝试更新为 verification_failed，不能清空记录重新从头下载/搜索。记录观察到的事实，不猜 403 的原因。未完成条目列出下一步，不伪造运行结果。

设备 profile 变化的重新获取按 [关联取包](download-workflow.md#任务级尝试记录与去重) 建新记录并保留父尝试；目标版本和搜索预算不因此改变。

用户报告至少区分：

- **文件**：实际包名/版本、渠道、完整分包数和保存位置。
- **校验**：来源哈希、Android 身份、APK 签名、分包一致性、官方基准对比各自的结果。
- **运行**：未安装／已安装／已启动及设备；下载任务不强制进行额外启动。
- **限制**：旧版、无法独立比对官方证书、来源清单未提供、缺工具或运行资源等实际未解决项。
