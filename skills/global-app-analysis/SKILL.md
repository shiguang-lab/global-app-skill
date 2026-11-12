---
name: global-app-analysis
description: 调研海外 Android App 的业务流程、功能入口、字段权限，或为 UED 提取整款 App/指定范围的原始界面图册；也支持仅下载/导出 APK。
---

# 海外 App 分析

需要 Node.js >=22.12、`python3` >=3.9；设备/AVD 门槛由解析后的工作流检查。

按目标选择 `download`（仅取包）、`research`（业务调研，含同时需要图册）或 `ued`（仅界面图册），执行：

```sh
npx -y --prefer-online global-app-skill@latest context resolve --mode MODE
```

CLI 自动发现已安装的 skill 并同步入口，检查 `skillUpdate` 并报告失败；新入口在客户端重新加载后采用。依次读取全部 `mustRead`，以 `resourceRoot` 解析资源并按流程执行。新任务重新 resolve，同一任务沿用已读快照。资源更新或校验失败时停止依赖工作，不静默使用旧资源。

脚本通过 `npx -y --prefer-online global-app-skill@latest run SCRIPT --mode MODE --resource-root RESOURCE_ROOT -- 参数` 执行；参数见解析后的 CLI 文档。业务判断与页面操作由 agent 按文档编排，CLI 成功不代表调研完成；关键进度仍须输出到聊天正文。

## 必检入口

解析资源后，先读取当前 `resourceRoot` 下的 `references/rules.md`。读取失败时暂停依赖该规则的工作。
到达规则定义的检查点时执行对应校验并记录结果。通过后才可正式或阶段性交付，包括复用、重发已有报告或链接。校验未通过时按规则回退或说明阻塞与恢复条件。
