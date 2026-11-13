---
name: global-app-analysis
description: 调研海外 Android App 的业务流程、功能入口、字段权限与原始界面：当用户给出 App 名称、Google Play 链接、包名或 APK，要求分析借款/开户/下单等业务链路、竞品功能与字段权限，或要导出全部/指定页面截图、制作 UED 界面图册，或仅下载/导出 APK 时使用；需要拆包、恢复代码或运行原包定位页面时也使用。执行需要 Node.js、python3，以及可用的 Android 设备或完整 AVD（仅下载也要求设备门槛）；本 skill 只做 Android，不适用于 iOS。
---

# 海外 App 分析

需要 Node.js >=22.12、`python3` >=3.9。第 1 步会强制检查 Android 真机/模拟器或完整 AVD；不满足时立即中断，不转成“只下载不运行”。

## 执行顺序

1. 选模式：`download`（仅取包/导出）、`research`（业务流程、入口、字段权限；同时要图册也用它）、`ued`（仅页面图册）。判断看用户要的答案，不看职位；“整款 App”是范围，不是分支。
2. 解析资源：

   ```sh
   npx -y --prefer-online global-app-skill@latest context resolve --mode MODE
   ```

3. 在开始任何分析前，按顺序读完返回的全部 `mustRead`：`cli → guide → orchestration → 模式文档 → rules`。`resourceRoot` 是只读快照，所有相对路径都以它为准；同一任务沿用它，新任务重新 resolve。资源更新或校验失败时停止依赖工作，不静默使用旧资源。
4. 按 `guide.md` 的十步主流程执行。第 5 步前读 `references/completion.md`；第 5–9 步读 `references/ui-extraction.md`，截图调用 `references/screenshot-workflow.md`；第 9 步按 `references/review-workflow.md` 的 9.1–9.5 执行。
5. 报告/图册始终使用同一路径。审查时用文件读取工具打开当前文件；修改后重新读取同一文件，从 9.1 重审。重审指再派一次独立审查看当前文件，不是重跑检查脚本。10.4/album 通过不是完成信号。
6. 7 个脚本优先用 `npx ... run SCRIPT` 执行；直接运行的条件见 `cli.md`。关键进度输出到聊天正文；CLI 成功不代表调研完成。

## 强制门槛

下表 `详见` 的文件都在 `references/` 下。

| 时点 | 必须通过 | 未过时 | 详见 |
|---|---|---|---|
| 开始分析前 | 快照校验通过；`mustRead` 全部读完 | 停止依赖工作，报告错误 | `cli.md` |
| 第 1 步，任何商店/搜索前 | `preflight` 返回 0、`status=passed`、`downstream_allowed=true` | 中断调研，不转纯下载 | `guide.md#环境硬门槛` |
| 第 4 步，进入分析前 | `verify` 通过 | 回第 3 步 | `verification.md` |
| 第 5 步前 | 已读 `completion.md`；页面范围按 `ui-extraction.md` 开始 | 补齐再进入 | `completion.md` |
| 每次重试/返工前 | 未超过 `loop-budget.md` 的轮次上限 | 超限暂停该回路并询问用户 | `loop-budget.md` |
| 第 9 步出口/第 10 步生成前 | 审查者逐个读当前文件；按 `rules.md#放行判据` 逐条回答，全部为“是” | 按判据对应行动作，回 9.1 派新一轮独立复审 | `review-workflow.md` |
| 交付前 | 按 `rules.md#放行判据` 逐条回答并为“是”；10.4/album 通过只说明可用 | 重新读取并派新一轮独立复审；不能只重跑 10.4 | `report-review-workflow.md` |

逐项检查见 `references/rules.md`；节点证据要求见各节点文档。

## 不可协商

- 环境门槛不过就停，即使本地已有 APK。
- 没读完 `mustRead` 不开始分析。
- 业务/UED 审查未通过不交付；纯下载样本未校验不交付；复用、重发、阶段性交付也一样。
- 10.4/album 通过只说明成品可用，不是完成信号；重新读取实际文件并确认审查通过后才交付。
- 放行判据见 `rules.md#放行判据`，交付前逐条回答；自读、自动检查、截图或 grep 都不算复审。
- 审查后再修改报告、图册、事实、流程图或验收证据，必须重新读取同一文件并回 9.1 重审，不能只重跑 10.4。
- 不为完成而缩小范围、删候选，或把未知/待确认写成肯定结论。
- 脚本成功、截图存在、日志退出码，都不等于事实或交互已验证。
- Mock、本地回调或隔离场景只证明客户端行为，不写成真实审批、放款、到账或生产启用。
- 长图只用原帧拼接，不重绘；无法完整就保留原帧并标记缺口。
- 真实生产借款/还款/身份/生物资料提交不执行，改用隔离 Mock。
