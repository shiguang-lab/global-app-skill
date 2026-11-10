---
name: overseas-app-research
description: 调研海外 Android App 的业务流程、功能入口、字段权限，或为 UED 提取整款 App/指定范围的原始界面图册；也支持仅下载/导出 APK。
---

# 海外 App 调研

需要 Node.js >=22.12、`python3` >=3.9；设备/AVD 门槛由解析后的工作流检查。

按目标选择 `download`（仅取包）、`research`（业务调研，含同时需要图册）或 `ued`（仅界面图册），执行：

```sh
npx -y --prefer-online global-app-skill@latest context resolve --mode MODE
```

依次读取返回的全部 `mustRead`，按其中流程执行；以返回的 `resourceRoot` 解析文档、模板和脚本。新任务重新 resolve，同一任务沿用已读快照。更新或校验失败时停止依赖工作并报告原因，不静默使用旧资源。

脚本通过 `npx -y --prefer-online global-app-skill@latest run SCRIPT --mode MODE --resource-root RESOURCE_ROOT -- 参数` 执行；可用脚本及参数见解析后的 CLI 文档。业务判断与页面操作由 agent 按文档编排，CLI 成功不代表调研完成；关键进度仍须输出到聊天正文。
