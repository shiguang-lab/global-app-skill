# 来源与复用脚本

以下网站与接口来自 2026-08 至 2026-11-06 的本机取包记录，不保证下一次仍收录同一包或保持协议。优先按包名定位，实际验证响应类型、版本和分包。客户端 API 与网页入口分别记录结果。

这些渠道都是主流程第 3 步“获取安装包”的有序子流程。须先通过环境硬门槛；`download.py` 每次开始前也重新检查设备/完整 AVD，无可用环境时返回 4，不创建下载目录、不请求外部 API。`--sdk` 可指定现有 SDK 根目录。脚本日志应由 agent 概括到正文进度，不能只显示最后的文件路径。

按下载工作流中的顺序实际尝试并登记任务级 attempts.json。已知渠道均不可用后，每批最多执行 3 轮 Web Search。每轮排除所有已尝试来源及别名、重定向来源。续开条件和记录命令见 [下载子工作流](download-workflow.md#web-search-三轮循环)。

## 主要入口

| 来源 | 历史实证 | 本模块入口与限制 |
|---|---|---|
| Google Play / Aurora | FT Lending 1.2.8（4 APK）、MocaMoca 2.1.8（1 APK）；Google delivery 哈希和签名校验通过，并安装启动 | `download.py play`；先读 network-and-devices 中的匿名注册要求；常规模拟器商店安装后也能导出 |
| 开发者官网 | FT Lending、MocaMoca、Cresia 官网当时主要跳 Play；29 个越南站点探测记录没有找到直接 APK | 找到真实官方 APK 则 `download.py url`；不把官网按钮当文件 |
| Aptoide | Cash Max 1.5.4、OKDinero 2.0.0、Rápikrédito 2.5.4 历史版；HolaFina 1.5.1 完整分包 | `download.py aptoide`；使用 app/get + aab=1 + 设备 profile，取 file.path 与 aab.splits；校验来源 MD5 |
| APKPure | docs 批量取包，最终一轮日志 22 次成功；其他包也曾 403/404/无候选 | `download.py apkpure`；客户端 `api.pureapk.com/m/v3/cms/app_version` 返回 protobuf 中提取 `download.pureapk.com/b/APK` 或 `XAPK`，不完整解析整个协议 |
| APKCube | Cresia 1.5.0 APKS（33 APK）；本地另有 F88、Home Credit 来源样本 | 浏览器读取详情/下载页；包未缓存时等待抓取，人机验证由用户完成；保存实际文件 |
| LDPlayer APK | MocaMoca 1.1.5 可下载但很旧；其他条目也可能仅引导模拟器或 Play | 真实 APK 直链用 `download.py url`；exe/dmg/PC launcher 不是目标 APK |

### Aptoide

网页站点 `*.en.aptoide.com/app`，元数据 `https://ws75.aptoide.com/api/7/app/get`，下载通常为 `pool.apk.aptoide.com`，也可能经过 `url-provider.aptoide.com/download/...`。普通 getMeta 查不到时可试 app/get 与 AAB 参数一次，不要立即认定未收录。

```sh
python3 scripts/download.py aptoide --package com.holaglobal.cash.loan.mx --locale es_MX --abi arm64-v8a --sdk-level 35 --density 480 --out /absolute/app-research/holafina-aptoide
```

上面是历史样本的调用示例；ABI/SDK/density 应依据目标设备选择。默认参数是历史可用 profile，不代表本机自动检测结果。脚本下载所有返回 split；其“完整”仅相对该 profile 的来源清单，不代表收集了全世界所有 ABI/语言/按需功能。

### APKPure

```sh
python3 scripts/download.py apkpure --package com.bplus.vtpay --out /absolute/app-research/vtpay-apkpure
```

脚本保留原始 APK/XAPK，并解出所有 APK。protobuf 链接提取是历史协议实现；返回顺序第一项只是候选，下载后必须核对实际 Android 版本。短效直链失效时可在同一个尚未结束的 ledger 尝试中，重新查询并写入新传输目录一次，刷新后按新的文件身份下载；重试耗尽才结束该尝试。不硬猜地址、改方法名重复登记或无限改客户端头。

### Google Play anonymous delivery

```sh
python3 scripts/download.py play --package com.ftlending.fast.cash.loan --country PH --language en-PH --device-profile /private/profile.json --device-id-file /private/device-id.txt --out /absolute/app-research/ft-play
```

省略 `--version-code` 时先请求匿名 getItems 获取该 profile/地区当前返回的版本；需指定版本时显式传入真实 versionCode。需要代理时追加 `--proxy http://127.0.0.1:<实际端口>`；所有参数和私密输入必须来自实际环境。下载器不会选择或切换 VPN。

### 浏览器与已知直链

```sh
python3 scripts/download.py url --package com.example.app --url 'https://actual-observed-host/path/app.apk' --filename app.apk --sha256 ACTUAL_SOURCE_SHA256 --out /absolute/app-research/direct-attempt
```

上面是格式示例，须替换为实际观测 URL、包名和摘要；来源不提供摘要则省略该参数并在报告中记录未提供。不要把登录 Cookie、验证码 token、私密链接复制到公开命令或聊天。需浏览器会话的下载用该浏览器保存文件，保留原始文件后调用 verify，无需强行转成裸 HTTP。

APKCube 历史观察到 `/api/apps/{package}/apks?token=...`、FETCHING 和下载请求 captchaToken 校验；这些是故障定位线索，不是可跳过浏览器验证的公共免认证 API。Evozi 当时会转交 APKCube，换入口不算切换了独立源。

## 补漏网站

| 网站 | 历史结果与使用条件 |
|---|---|
| https://apkcombo.com / https://apkcombo.app | Downloader、checkin、AJAX 都曾探测；遇到 403/Cloudflare/TLS，无新增成功样本。当前页面可正常使用时再跟下载入口 |
| https://www.apkmirror.com | 曾找到 Kredivo 印尼包 `com.finaccel.android`；不能替代越南包 `vn.kredivo.android` |
| https://www.pgyer.com/apk | VietCredit APKHUB 页因出口 CN 受限/403；不要把地区受限当页面不存在 |
| https://apk.ldplayer.net | 部分条目有 APK，部分无 APK；核对真实下载结果及版本 |
| https://apkfab.com | Cresia 页面曾 403 |
| https://apk.support | Cresia 详情/下载入口曾 TLS EOF |
| https://apksos.com | Cresia 条目曾 404 |
| https://www.apkbe.com | FT Lending 条目曾 404 |
| https://apkspure.com | 搜索页可访问，未取得 Cresia 文件；与 APKPure 不是同一站 |
| https://www.uptodown.com | 尝试的 Cresia 地址曾 404；不代表平台完全无可用应用 |
| https://es.apkpac.com | Cresia 当时只引导 Play |
| https://apps.evozi.com/apk-downloader | 页面当时把包名交给 APKCube，非独立下载源 |
| https://m.memuplay.com | MocaMoca 页面最终指向 Play，版本标注与文件可得性分开核验 |
| https://www.updatestar.com | FT Lending 下载按钮当时跳 Play |
| https://www.appbrain.com / https://apptopia.com | 当时用于版本/包名核对，相关页面没有 APK 产物 |
| APK-DL / APKPremier | 旧记录分别出现疑似停放页、跳转后无目标包；缺真实入口时不投入重复尝试 |

## 提炼依据

本模块已移除原脚本的固定包名、输出目录、代理 7897、菲律宾地区与版本值，以及仅“文件够大/是 ZIP 就算成功”的判断。每次尝试独立目录，不覆盖已有样本；已写入来源哈希的文件才允许断点续传。无来源摘要时重试从头下载，避免短效链接刷新后拼接不同文件。

原实现只作可选溯源，不是运行依赖：

- `~/docs/research/tools/pureapk.py`：APKPure 客户端头、protobuf 直链提取、流式下载/短效链接经验。
- `~/docs/research/tools/collect_apks.py`：Aptoide 包名查询与元数据结构。
- `~/overseas/PHO/.scratch/sms-analysis-2026-10-29/download_apks.py`：AAB 主包/全部 split 下载和来源 MD5。
- `~/Downloads/philippines-lending-apps/tools/anonymous-download.py`：Aurora 匿名 delivery 协议与服务器 SHA-256；派生代码保留 GPL-3.0-or-later 标记及上游链接。
- `~/overseas/get_money/docs/modules/device-collection/apks/README.md`：14 款真机导出、1 款网络下载的归档事实。

不会把匿名令牌、device ID、个人账号资料、订阅配置或真实设备数据打包进 skill。
