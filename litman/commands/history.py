from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional

from ..operation_log import OperationLog


def history_command(
    directory: str,
    limit: int = 20,
    detail_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "logs": [],
        "detail": None,
        "errors": [],
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    if detail_id:
        detail = op_log.get_log_detail(detail_id)
        if detail is None:
            result["success"] = False
            result["errors"].append(f"找不到操作记录: {detail_id}")
            return result
        result["detail"] = _format_detail(detail)
        return result

    result["logs"] = op_log.list_logs(limit)
    return result


def _format_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    ops = data.get("operations", [])

    file_ops = []
    meta_ops = []
    other_ops = []

    for op in ops:
        op_type = op.get("type", "")
        if op_type in ("rename", "move", "delete"):
            file_ops.append(op)
        elif op_type == "metadata_update":
            meta_ops.append(op)
        else:
            other_ops.append(op)

    affected_files = set()
    for op in file_ops:
        fn = op.get("file_name", "")
        if fn:
            affected_files.add(fn)
        else:
            p = op.get("old_path") or op.get("source") or op.get("file_path", "")
            if p:
                affected_files.add(Path(p).name)

    affected_fields = set()
    field_changes: Dict[str, List[Dict[str, Any]]] = {}
    for op in meta_ops:
        f = op.get("field", "")
        if f:
            affected_fields.add(f)
            if f not in field_changes:
                field_changes[f] = []
            field_changes[f].append({
                "file": op.get("file_name", ""),
                "old": op.get("old_value", ""),
                "new": op.get("new_value", ""),
            })

    return {
        "id": data.get("id", ""),
        "description": data.get("description", ""),
        "command": data.get("command", ""),
        "timestamp": data.get("timestamp", ""),
        "has_snapshot": "db_snapshot" in data,
        "total_operations": len(ops),
        "file_operations": len(file_ops),
        "metadata_operations": len(meta_ops),
        "affected_files": sorted(affected_files),
        "affected_fields": sorted(affected_fields),
        "field_changes": field_changes,
        "file_ops_summary": [
            {
                "type": op.get("type"),
                "file": op.get("file_name", ""),
                "from": op.get("old_path") or op.get("source", ""),
                "to": op.get("new_path") or op.get("destination", ""),
            }
            for op in file_ops
        ],
    }


def format_history_list(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "暂无操作记录"

    lines = []
    for log in logs:
        cmd = log.get("command", "")
        desc = log.get("description", "无描述")
        ts = log.get("timestamp", "")
        count = log.get("operations_count", 0)
        op_types = ", ".join(log.get("op_types", []))
        files = log.get("affected_files", [])
        fields = log.get("affected_fields", [])
        snapshot = " [有快照]" if log.get("has_snapshot") else ""

        lines.append(f"[{log['id']}] {desc}")
        lines.append(f"    {ts} | {count} 个操作 | 类型: {op_types}{snapshot}")
        if files:
            file_display = files[:5]
            lines.append(f"    文件: {', '.join(file_display)}{'...' if len(files) > 5 else ''}")
        if fields:
            lines.append(f"    字段: {', '.join(fields)}")
        lines.append("")

    return "\n".join(lines)


def format_history_detail(detail: Dict[str, Any]) -> str:
    lines = []

    lines.append(f"操作 ID: {detail['id']}")
    lines.append(f"命令: {detail.get('command', '?')}")
    lines.append(f"描述: {detail.get('description', '')}")
    lines.append(f"时间: {detail.get('timestamp', '')}")
    lines.append(f"总计操作: {detail.get('total_operations', 0)}")
    lines.append(f"  文件操作: {detail.get('file_operations', 0)}")
    lines.append(f"  元数据操作: {detail.get('metadata_operations', 0)}")
    snapshot_tag = "有索引快照" if detail.get("has_snapshot") else "无索引快照"
    lines.append(f"  {snapshot_tag}")
    lines.append("")

    affected_files = detail.get("affected_files", [])
    if affected_files:
        lines.append(f"涉及文件 ({len(affected_files)} 个):")
        for fn in affected_files[:10]:
            lines.append(f"  - {fn}")
        if len(affected_files) > 10:
            lines.append(f"  ... 还有 {len(affected_files) - 10} 个")
        lines.append("")

    affected_fields = detail.get("affected_fields", [])
    if affected_fields:
        lines.append(f"涉及字段: {', '.join(affected_fields)}")
        lines.append("")

    file_ops = detail.get("file_ops_summary", [])
    if file_ops:
        lines.append("文件操作详情:")
        for op in file_ops:
            op_type = op.get("type", "?")
            fn = op.get("file", "?")
            if op_type == "rename":
                old_name = Path(op.get("from", "?")).name
                new_name = Path(op.get("to", "?")).name
                lines.append(f"  rename: {old_name} -> {new_name}")
            elif op_type == "move":
                old_dir = Path(op.get("from", "?")).parent.name
                new_dir = Path(op.get("to", "?")).parent.name
                lines.append(f"  move: {fn} ({old_dir} -> {new_dir})")
            else:
                lines.append(f"  {op_type}: {fn}")
        lines.append("")

    field_changes = detail.get("field_changes", {})
    if field_changes:
        lines.append("元数据变更详情:")
        for field, changes in field_changes.items():
            lines.append(f"  [{field}]")
            for ch in changes[:5]:
                fn = ch.get("file", "?")
                old = ch.get("old", "")
                new = ch.get("new", "")
                old_disp = str(old) if len(str(old)) < 40 else str(old)[:37] + "..."
                new_disp = str(new) if len(str(new)) < 40 else str(new)[:37] + "..."
                lines.append(f"    {fn}: {old_disp} -> {new_disp}")
            if len(changes) > 5:
                lines.append(f"    ... 还有 {len(changes) - 5} 条")
        lines.append("")

    return "\n".join(lines)
