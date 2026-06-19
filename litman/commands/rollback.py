from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional

from ..database import PaperDatabase
from ..models import Paper
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
        "index_restored": False,
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
    result["failed_files"] = rollback_result.get("failed_files", [])
    result["file_ops_success"] = rollback_result.get("file_ops_success", True)

    if rollback_result.get("db_snapshot") and rollback_result["file_ops_success"]:
        db = PaperDatabase.for_directory(str(dir_path))
        db.load()
        db.restore_snapshot(rollback_result["db_snapshot"])
        db.save()
        result["index_restored"] = True
        if result["success"]:
            result["message"] += " (索引已从快照恢复)"

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
            snapshot = " [有快照]" if log.get("has_snapshot") else ""
            lines.append(f"  [{log['id']}] {desc}{snapshot}")
            lines.append(f"      {ts} | {count} 个操作")
            lines.append("")
        return "\n".join(lines)

    lines.append(result.get("message", ""))

    if result.get("index_restored"):
        lines.append("[索引已恢复] 数据库已从快照还原到操作前的状态")

    if result.get("actions"):
        lines.append("")
        lines.append("回滚操作详情:")
        for action in result["actions"]:
            status = "[OK]" if action.get("success") else "[FAIL]"
            lines.append(f"  {status} [{action['type']}] {action.get('message', '')}")

    if result.get("failed_files"):
        lines.append("")
        lines.append("[警告] 以下文件回滚失败，索引未恢复:")
        for fail in result["failed_files"]:
            lines.append(f"  - [{fail['type']}] {fail['file']}: {fail['error']}")
        lines.append("")
        lines.append("请手动处理这些文件后，再次执行回滚命令。")

    return "\n".join(lines)
