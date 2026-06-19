from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List

from ..operation_log import OperationLog


def rollback_command(
    directory: str,
    log_id: str = None,
    list_logs: bool = False,
    limit: int = 10,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "actions": [],
        "logs": [],
        "message": "",
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["message"] = f"目录不存在: {directory}"
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    if list_logs:
        result["logs"] = op_log.list_logs(limit)
        return result

    rollback_result = op_log.rollback(log_id)
    result["success"] = rollback_result["success"]
    result["message"] = rollback_result["message"]
    result["actions"] = rollback_result["actions"]

    return result


def format_rollback_result(result: Dict[str, Any]) -> str:
    lines = []

    if result.get("logs"):
        lines.append("最近操作记录:")
        lines.append("")
        for log in result["logs"]:
            desc = log.get("description", "无描述")
            ts = log.get("timestamp", "")
            count = log.get("operations_count", 0)
            lines.append(f"  [{log['id']}] {desc}")
            lines.append(f"      {ts} · {count} 个操作")
            lines.append("")
        return "\n".join(lines)

    lines.append(result.get("message", ""))

    if result.get("actions"):
        lines.append("")
        lines.append("回滚操作详情:")
        for action in result["actions"]:
            status = "[OK]" if action.get("success") else "[FAIL]"
            lines.append(f"  {status} [{action['type']}] {action.get('message', '')}")

    return "\n".join(lines)
