# 执行检查点

本表是检查点索引：命令、证据和通过条件的细节以链接的节点文档为准；执行入口（`SKILL.md`）的「强制门槛」是摘要。检查点按“时点”绑定到具体步骤，不另立一套流程。

| 检查点 | 时点 | 命令/动作 | 未通过时 |
|---|---|---|---|
| 资源快照 | 开始分析前 | 按[CLI 执行](cli.md)读完全部 `mustRead`，确认 `resourceRoot` 校验通过 | 停止依赖工作，报告错误；不静默使用旧资源 |
| 环境门槛 | 第 1 步，任何商店/搜索前 | 运行 `preflight`，按[环境硬门槛](guide.md#环境硬门槛)核对 | 中断调研，不转纯下载；报告最小修复动作 |
| 样本验收 | 第 4 步，进入分析前 | 运行 `verify`；纯下载另执行 `check-ledger` | 按[取包流程](download-workflow.md#4-校验归档)或[校验规则](verification.md)修正后重验 |
| 账本初始化 | 任务目录确定后（第 2 步） | 先 `mkdir -p` 任务目录，再 `check_delivery.py init`；取包账本在第 3 步用 `attempts.py init` | 补齐账本再继续；两个账本不要混用 |
| 第 5 步入口 | 第 5 步前 | 读[完成条件](completion.md)；按[共用页面提取](ui-extraction.md)确定范围 | 补齐再进入；不以“看起来没页面”缩小范围 |
| 重试/返工 | 每次动作前 | `check_delivery.py reserve`；搜索用 `attempts.py search-round` | 校验账本返回 3、搜索脚本返回 1 时暂停该回路和依赖交付，保存状态并询问用户 |
| 第 9 步出口 | 9.5 | 运行 `check_delivery.py review`；至少两轮覆盖当前范围 | 回[审查工作流](review-workflow.md) 9.3/9.1 补证 |
| 业务/UED 第 10 步交付前 | 成品检查后（业务 10.4 / UED album） | 按[报告审查](report-review-workflow.md)和/或[图册验收](ued-workflow.md#交付验收与进度)完成对应成品的 10.1–10.4/album，再运行 `check_delivery.py deliver`；阶段性交付的 `review`/`deliver` 都加 `--partial` | 补齐账本、证据或成品，按对应流程重验 |

复用旧报告、重发已有报告链接和提交阶段性结果都走第 9、10 步检查。把准备交付的实际文件纳入当前任务记录，核对原有证据与当前范围和版本，再运行检查。旧报告的存在、以前的验收结论和本次补测各自作为证据。

阶段性交付须满足[阶段性条件](completion.md#真实阻塞与结论边界)，`review` 和 `deliver` 都加 `--partial`，并在聊天说明剩余工作和恢复条件。校验未通过时只报告进度或阻塞，保留工作记录供恢复。
