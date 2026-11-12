# 审查与交付记录示例

`review.json`、`scope.json`、`results.json` 的最小模板。复制到任务目录后，先替换 `facts`、`scope`、`delivery` 中的路径和 `REPLACE_...` 占位符，再用 `revision` 取值；模板原样运行会被校验拒绝，这是预期的。

## 脚本的硬性要求

- `targets` 含 `research` 时（含同时要 UED 的情况），`scope.review_items` 必须且只能包含 `business`、`pages`；仅 `ued` 时包含 `pages`；仅当 `h5_in_scope=true` 时才加 `h5`。键集合必须与推导出的适用面完全一致。
- 应审项 ID 只能使用字母、数字、下划线、点和连字符（含中文）；`business:login`、`post-login/submit` 这类写法会被拒绝。
- 每个审查面的 `status` 必须与逐项结果一致：所有项 `passed` 才能写 `passed`；否则写 `needs_work`，阶段性审查可写 `partial_passed`。
- `facts` 只列事实源和证据索引，不能包含 `review.json`、`results.json`、审查报告、运行日志或第 10 步成品；否则 `finish-review` 会报 `facts changed during review`。
- 每个证据引用相对任务目录，文本文件用 `notes.md#L12` 指向具体行；文件必须存在且非空。
- 每个审查面必须有本轮新产生的 `evidence` 文件；不能复用上一轮的审查面证据（逐项证据可以引用本轮前的原始材料）。至少完成两轮覆盖当前范围全部应审项的审查。
- `delivery.revision` 必须是最后一次修改事实后 `revision` 命令的输出；`sha256` 必须是最终成品文件的哈希。

混合目标（业务 + UED）：`targets` 写 `["research", "ued"]`，`delivery.artifacts` 分别加报告和图册条目（报告用 `10.1`–`10.4`，图册用 `album`）；`review_items` 按含 `research` 的规则仍要包含 `business` 和 `pages`。完整示意见 [review-mixed.json](review-mixed.json)（scope/results 与单目标示例相同）。

## 推荐顺序

```sh
mkdir -p "$TASK_DIR"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" init "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" revision "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" begin-review "$TASK_DIR/review.json"
# 按 begin-review 返回的应审项写 results.json
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" finish-review "$TASK_DIR/review.json" --id ID --results "$TASK_DIR/results.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" review "$TASK_DIR/review.json"
python3 "$RESOURCE_ROOT/scripts/check_delivery.py" deliver "$TASK_DIR/review.json"
```
