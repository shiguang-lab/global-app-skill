"""CLI progress events. The agent must also publish meaningful events in chat."""
import os
import sys


LABELS = {"running": "进行中", "succeeded": "完成", "waiting_user": "等待用户",
          "failed": "失败", "skipped": "跳过"}
STAGES = {"环境检查": 1, "目标识别与信息补齐": 2, "获取安装包": 3, "校验归档": 4,
          "拆包与代码恢复": 5, "原包运行与入口定位": 6, "按需 Mock 与场景准备": 7,
          "页面提取与场景走查": 8, "证据交叉复核": 9, "报告与交付": 10}


def emit(stage, state, message):
    name = stage.split(" · ", 1)[0]
    step = STAGES.get(name)
    total = int(os.environ.get("APP_RESEARCH_TOTAL_STAGES", "10" if step and step > 4 else "4"))
    if total not in (4, 10) or step and step > total:
        raise ValueError("Progress scope must be 4 download stages or 10 research stages")
    if stage == "调研执行":
        label = f"2–{total}/{total} {stage}"
    elif step:
        label = f"{step}/{total} {stage}"
    else:
        raise ValueError("Unknown workflow stage: " + stage)
    print(f"【{label}｜{LABELS[state]}】{message}", file=sys.stderr, flush=True)
