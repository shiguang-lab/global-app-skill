# 审查与交付记录

业务调研和 UED 在任务目录维护一个 `review.json`。记录只索引已有材料，详细发现、运行结果和审查结论保留在原有文件。相对路径以记录所在目录为基准。

| 字段 | 内容 |
|---|---|
| `targets` | 交付目标列表，取 `research`、`ued` 或两者 |
| `facts` | 定义当前事实的文件路径列表，覆盖原始问题与范围、样本和资源身份、业务/场景及页面矩阵、Mermaid 和事实草稿、证据索引。索引注明所引用证据的版本或哈希，替换验收证据时同步更新索引。排除本记录和第 10 步成品 |
| `scope` | 当前范围 JSON 的文件路径。文件含布尔值 `h5_in_scope` 和 `h5_evidence`，后者指向 H5 发现或排除依据。校验从交付目标与范围推导必审面，范围文件和 H5 依据自动纳入事实版本 |
| `issues` | 以稳定缺口 ID 索引。每项含 `status`（`open`、`closed` 或 `blocked`）及 `evidence`（原记录位置，关联下一动作或复审关闭依据）。真实阻塞额外填写 `kind`、`layer`、`paths` 和 `resume`，格式见下文 |
| `partial` | 阶段性交付时记录 `reason`（`blocked` 或 `user_request`）、`included`（当前复审确认可交付的范围记录）。用户明确要求时另记录 `evidence`（原请求位置） |
| `delivery` | 第 10 步填入 `revision`、布尔值 `partial` 及 `artifacts` 列表。每个成品填 `target`、`path`、`sha256` 与 `checks`。报告的检查键为 `10.1` 至 `10.4`，图册用 `album`。值是针对该文件的检查结果位置。图片包以归档文件验收 |

证据引用使用可读的本地文件路径，或用 `notes.md#L12` 指向 UTF-8 文本的具体行。用户授权等会话证据先摘录到任务记录并注明来源。校验检查文件和指定行是否存在，审查者核对内容是否支持结论。

在已解析的资源快照中直接运行记录校验脚本，参数使用任务记录路径：

```sh
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" revision "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" begin-review "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" finish-review "$TASK_DIR/review.json" --id ID --results review-ID.json
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" review "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" deliver "$TASK_DIR/review.json"
```

- 派发或开始复核前运行 `begin-review`，取得轮次 ID、事实版本和适用审查面。收齐后写本轮结果文件，再执行 `finish-review` 封存。结果文件按审查面 ID 索引，每面含 `method`（`isolated` 或 `in_session`）、`status`（`passed`、`needs_work` 或 `partial_passed`）和 `evidence`。证据文件必须在本轮开始后产生，每轮单独保存。上一轮封存后再开始下一轮。
- 事实变化时用新版本开始审查，旧轮次留在账本。若事实在一轮审查进行中改变，运行 `cancel-review --id ID --evidence FILE` 登记取消原因后重新开启。阶段性审查前写明已核实范围，保留原问题和未覆盖项；只有该面可交付部分通过才填 `partial_passed`。
- 放行和回退按[执行检查点](rules.md)。至少两轮覆盖当前范围的全部必审面。若后续发现 H5，保留之前轮次，并补齐两轮覆盖 H5 的审查。
- 报告或图册只改呈现时按第 10 步的重审起点执行。对确认不受影响的检查可沿用原记录，更新成品哈希前完成其余重审。改动改变事实时更新事实文件，先回第 9 步。
- 脚本检查审查轮次、缺口和版本一致性。审查者仍须核对引用证据、业务含义及成品质量。

登录后原生页面、App WebView 或 App 内交互受阻时，将 `kind` 设为 `app_host`，`paths` 至少包括 `original_host` 和 `isolated_host`。其他阻塞使用 `other` 并列出实际评估的路径。可运行的路径应实际尝试并保留结果。用 `reserve --path 路径ID` 领取技术卡点额度，并以 `finish` 写入失败结果。该路径在 `paths` 中填写 `status: attempted`、对应的 `key` 和领取的 `attempt` ID。路径无法执行时填写 `status: unavailable`、具体 `reason` 和指向已验证前置限制的 `evidence`。不同路径各自引用证据。原包没有调试入口只说明原包路径的限制，隔离宿主路径仍需实际验证或单独给出不能执行的依据。
