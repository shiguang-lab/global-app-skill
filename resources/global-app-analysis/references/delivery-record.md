# 审查与交付记录

业务调研和 UED 在任务目录维护一个 `review.json`。记录只索引已有材料，详细发现、运行结果和审查结论保留在原有文件。相对路径以记录所在目录为基准。

| 字段 | 内容 |
|---|---|
| `targets` | 交付目标列表，取 `research`、`ued` 或两者 |
| `facts` | 定义当前事实的文件路径列表，覆盖原始问题与范围、样本和资源身份、业务/场景及页面矩阵、Mermaid 和事实草稿、证据索引。索引注明所引用证据的版本或哈希，替换验收证据时同步更新索引。排除本记录和第 10 步成品 |
| `scope` | 当前范围 JSON 的文件路径。文件含布尔值 `h5_in_scope` 和 `h5_evidence`，后者指向 H5 发现或排除依据。校验从交付目标与范围推导必审面，范围文件和 H5 依据自动纳入事实版本 |
| `rounds` | 按完成顺序追加。每轮含唯一 `id`、开始审查时取得的 `revision`、该轮计划的 `surfaces` 和按审查面 ID 索引的 `results`。每面结果含 `method`（`isolated` 或 `in_session`）、`status`（`passed`、`needs_work` 或 `partial_passed`）及 `evidence`（完整比对结果的位置） |
| `issues` | 以稳定缺口 ID 索引。每项含 `status`（`open`、`closed` 或 `blocked`）及 `evidence`（原记录位置，关联下一动作或复审关闭依据）。真实阻塞额外填写 `layer`、`attempt`（实际尝试及结果的记录位置，无法执行时引用已验证的前置限制）、`resume` |
| `partial` | 阶段性交付时记录 `reason`（`blocked` 或 `user_request`）、`included`（当前复审确认可交付的范围记录）。用户明确要求时另记录 `evidence`（原请求位置） |
| `delivery` | 第 10 步填入 `revision`、布尔值 `partial` 及 `artifacts` 列表。每个成品填 `target`、`path`、`sha256` 与 `checks`。报告的检查键为 `10.1` 至 `10.4`，图册用 `album`。值是针对该文件的检查结果位置。图片包以归档文件验收 |

证据引用使用可读的本地文件路径，或用 `notes.md#L12` 指向 UTF-8 文本的具体行。用户授权等会话证据先摘录到任务记录并注明来源。校验检查文件和指定行是否存在，审查者核对内容是否支持结论。

在已解析的资源快照中直接运行记录校验脚本，参数使用任务记录路径：

```sh
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" revision "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" review "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" deliver "$TASK_DIR/review.json"
```

- 每轮开始取 `revision`，收齐结果后追加到 `rounds`。修改事实文件后取得新版本，旧轮次保留原版本，重新执行审查。先将已核实的范围写入原范围记录，再审查阶段性结果；保留原问题和未覆盖项。适用审查面只能在确认该面可交付部分通过时填 `partial_passed`。
- 放行和回退按[执行检查点](rules.md)。至少两轮覆盖当前范围的全部必审面。若后续发现 H5，保留之前轮次，并补齐两轮覆盖 H5 的审查。
- 报告或图册只改呈现时按第 10 步的重审起点执行。对确认不受影响的检查可沿用原记录，更新成品哈希前完成其余重审。改动改变事实时更新事实文件，先回第 9 步。
- 脚本检查审查轮次、缺口和版本一致性。审查者仍须核对引用证据、业务含义及成品质量。
