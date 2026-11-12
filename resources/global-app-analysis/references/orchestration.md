# Skill 整体编排说明

本文件用于执行前理解整体流程：一套十步主流程，下载、业务调研、UED 界面提取三个任务分支。第 2 步正式确定分支和范围，后续判断沿用该记录；同时要求业务和 UED 时，共用页面清单与图片，执行两个交付目标。

下图是现有工作流的导航图。取包、页面范围、截图和验收的具体规则以对应模块为准；调整主流程或分支规则时同步更新此图。

## 整体流程图

```mermaid
flowchart TD
    request(["用户请求：识别任务意图"]) --> gate{"1 环境硬门槛通过？"}
    gate -->|"失败"| stopped["中断并报告原因"]
    gate -->|"通过"| choose{"2 确认任务类型、目标与范围"}

    choose -->|"下载或导出 APK"| downloadMode["下载分支：仅前四步"]
    choose -->|"业务流程、规则、字段权限"| businessMode["业务调研：可兼有 UED 目标"]
    choose -->|"仅提取界面、截图、设计图册"| uedMode["UED 界面提取"]

    subgraph packageFlow["共用模块：取包与校验"]
        fetch["3 记录目标版本与取包 profile，按渠道获取原包"]
        packageCheck{"4 承接目标版本，核对身份、签名及分包"}
        fetch --> packageCheck
        packageCheck -->|"不通过：保留记录，尝试剩余来源"| fetch
    end

    downloadMode --> fetch
    businessMode --> fetch
    uedMode --> fetch
    fetch -->|"所有可行路径受阻"| stopped

    packageCheck -->|"通过"| continueMode{"按第 2 步记录继续"}
    continueMode -->|"仅下载"| apkDelivery["交付：原始安装包、来源及校验结果"]
    continueMode -->|"业务或 UED"| recover

    subgraph sharedPages["共用页面提取主干与业务附加步骤：第 5–9 步"]
        recover["5 拆包与代码恢复：原生、RN、Flutter、H5"]
        copyCheck{"5 分析副本条目比对结论？"}
        semanticReview["Manifest 改变：逐项语义复核并保留证据"]
        semanticReady{"仅计划中的调试差异且证据齐全？"}
        profileCheck{"6 原包与预期运行 profile 匹配？"}
        profileChange["记录新 profile 与证据，关联原取包尝试，保留搜索预算"]
        baseline["6 原包运行：确认设备、宿主及资源版本"]
        pageScope["共用页面与状态清单：按本次请求确定入口种子"]

        h5Policy{"关联 H5 项目的页面地址来源？"}
        allRoutes["动态下发：枚举当前项目快照全部路由"]
        usedRoutes["确认固定：从本次入口求页面导航闭包"]
        unknownRoutes["尚未查清：枚举已知候选，保留未知范围"]

        prepare["7 按需 Mock：在原实现的数据层准备状态"]
        capture[["8 截图模块：滚动页完整长图，单屏原始截图"]]
        captureRecord["保留原帧及哈希；复核成败均更新最新结果并追加历史"]

        needsBusiness{"本次是否包含业务调研？"}
        businessWalk["8 业务走查：入口、条件、字段权限、成功失败及返回续办"]
        reviewStart["9.1 准备证据并清点缺口"]
        reviewRun{"9.2 分工审查：本轮结果？"}
        reviewFix["9.3 回相关步骤继续分析"]
        reviewRestart["9.4 从 9.1 重新审查"]
        reviewGate["9.5 确认完成门槛并记录结论"]

        recover --> copyCheck
        copyCheck -->|"未使用副本或 passed"| profileCheck
        copyCheck -->|"requires_manifest_review"| semanticReview --> semanticReady
        copyCheck -->|"不允许的载荷差异"| recover
        semanticReady -->|"是"| profileCheck
        semanticReady -->|"需修正或补证"| recover
        profileCheck -->|"匹配"| baseline --> pageScope
        profileCheck -->|"不匹配且取包 profile 需变化"| profileChange

        pageScope -->|"原生、RN、Flutter"| prepare
        pageScope -->|"H5 按项目判断"| h5Policy
        h5Policy -->|"后端或配置可选择页面"| allRoutes
        h5Policy -->|"已有固定入口证据"| usedRoutes
        h5Policy -->|"来源或路由全集未知"| unknownRoutes

        allRoutes --> prepare
        usedRoutes --> prepare
        unknownRoutes --> prepare

        prepare -->|"状态就绪；已有完整 App 实测才免 Mock"| capture
        capture --> captureRecord --> needsBusiness

        needsBusiness -->|"包含业务"| businessWalk --> reviewStart
        needsBusiness -->|"仅 UED"| reviewStart
        reviewStart --> reviewRun
        reviewRun -->|"发现缺口"| reviewFix
        reviewFix -->|"回第 5–8 步补证"| recover
        reviewFix -->|"仅需修正草稿"| reviewRestart
        reviewRun -->|"首审无缺口"| reviewRestart
        reviewRestart --> reviewStart
        reviewRun -->|"复审通过"| reviewGate
        reviewRun -->|"真实阻塞或用户要求部分结果"| checkpoint
    end

    profileChange -->|"同来源同方法的关联尝试，不领取新搜索轮次"| fetch

    reviewGate --> deliveryMode{"10 生成正式或获准阶段性交付物"}
    checkpoint["先提供已核实结果；阻塞与恢复动作留在聊天和内部"]
    checkpoint --> deliveryMode

    deliveryMode -->|"业务目标"| businessOutput["业务报告、Mermaid、对应 UI 及扩展图册"]
    deliveryMode -->|"UED 目标"| uedOutput["页面目录、原图、长图、可浏览图册及图片包"]

    businessOutput --> businessCheck["10.1–10.4 报告审查：格式、结构、结论与正文、最终 UI"]
    uedOutput --> uedCheck["UED 交付验收：索引与清单一致、原尺寸可读、来源准确"]

    businessCheck -->|"事实变化：回第 9 步"| reviewStart
    businessCheck -->|"修改成品后从对应环节重审"| businessCheck
    uedCheck -->|"页面或范围变化：回第 9 步"| reviewStart

    businessCheck -->|"呈现通过；离线版另做断网检查"| cleanup
    uedCheck -->|"呈现通过；离线版另做断网检查"| cleanup
    apkDelivery --> cleanup
    stopped --> cleanup

    cleanup(["所有退出路径收尾：恢复本次设备与网络变更，清理调试会话，保留证据"])

    classDef business fill:#FFE0C2,stroke:#FF9E42
    classDef ued fill:#DCCCFF,stroke:#874FFF
    classDef limited fill:#FFECBD,stroke:#FFC943

    class businessMode,businessWalk,businessOutput,businessCheck business
    class uedMode,uedOutput,uedCheck ued
    class unknownRoutes,stopped,checkpoint limited

    style packageFlow fill:#F5F5F5,stroke:#B3B3B3
    style sharedPages fill:#EAF4FF,stroke:#3DADFF
```

## 执行时如何读图

- **分支与复用**：灰色区域是三个分支共用的取包与校验；蓝色区域是业务/UED 的页面提取主干，其中橙色节点是业务附加步骤，纯 UED 跳过。混合技术栈分别处理各层，再汇入同一页面清单，不是整款 App 只能选一种技术栈。
- **H5 范围**：按每个纳入项目判断后端/配置值是否真正能选择页面。动态项目覆盖当前快照全部路由；固定项目从本次入口求使用闭包；未知项目继续补证，范围未查清不能判完整。原生/RN/Flutter 的页面发现及状态范围也必须执行。
- **验收与交付**：第 9 步按 [证据审查工作流](review-workflow.md) 清点、分工、补证、重审和放行，具体查证要求见 [审查清单](review-checklist.md)。第 5–8 步补证完成后从 9.1 重新进入。第 10 步按 [报告审查工作流](report-review-workflow.md) 或 UED 图册验收检查实际交付物。真实阻塞或用户要求先看结果时只呈现已核实内容，阻塞与恢复动作留在聊天和内部。
- **版本与设备**：第 3 步保存用户目标 versionCode，第四步自动承接；没有关联取包记录时显式传目标版本，显式值与记录冲突须失败。设备相关尝试预先记录实际取包 profile；换 profile 用父 id、新 profile 和证据理由建立关联尝试，相同 profile 不重复，三轮搜索预算不变。
- **副本一致性**：条目比对发现 Manifest 改变时返回 `requires_manifest_review`，须逐项核对实际语义差异；未经复核不能把副本截图认作原实现证据。无法补齐证据时继续可用的原包页面并记录缺口，不无限修改副本。
- **回路与停止**：图中的取包搜索、技术卡点、第 9 步补证和第 10 步成品返工均适用[回路预算](loop-budget.md)。到上限仍需继续时暂停受影响的回路，用户确认后开一批。回到第 5 步的箭头代表返回第 5–8 步中的相关节点。第 10 步的事实问题回 9.1，沿用证据返工计数。
- **校验记录**：长图每次复核均更新最新 `verification.json`，成功和失败历史均保留；验收使用与当前文件哈希一致的最新结果。`stitched` 或旧 `passed` 不能覆盖后续失败。
- **执行性质**：由 agent 根据证据编排这些步骤，脚本执行具体任务；所有退出路径都收尾。图中第 1 步之前只识别请求意图，商店、渠道等后续查询仍须通过环境门槛。

## 操作文档入口

任务分支见 [下载子工作流](download-workflow.md)、[业务调研工作流](research-workflow.md) 和 [UED 工作流](ued-workflow.md)。第 4 步必读 [校验与交付](verification.md)，两个完整分支第 5 步前必读 [调研闭环与完成条件](completion.md)。共用操作见 [包体与代码恢复](package-analysis.md)、[运行与 Mock](runtime-and-mock.md)、[页面发现与图片提取](ui-extraction.md) 和 [截图与长图操作](screenshot-workflow.md)。业务报告成品按 [报告审查工作流](report-review-workflow.md) 验收。
