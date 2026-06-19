from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class OperationLog:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_operations: List[Dict[str, Any]] = []

    def log_file_move(self, source: str, destination: str, file_name: str = "") -> None:
        self._current_operations.append({
            "type": "move",
            "source": str(Path(source).resolve()),
            "destination": str(Path(destination).resolve()),
            "file_name": file_name or Path(source).name,
            "timestamp": datetime.now().isoformat(),
        })

    def log_file_rename(self, old_path: str, new_path: str, file_name: str = "") -> None:
        self._current_operations.append({
            "type": "rename",
            "old_path": str(Path(old_path).resolve()),
            "new_path": str(Path(new_path).resolve()),
            "file_name": file_name or Path(old_path).name,
            "timestamp": datetime.now().isoformat(),
        })

    def log_file_delete(self, file_path: str) -> None:
        self._current_operations.append({
            "type": "delete",
            "file_path": str(Path(file_path).resolve()),
            "file_name": Path(file_path).name,
            "timestamp": datetime.now().isoformat(),
        })

    def log_metadata_update(self, file_path: str, file_name: str, field: str, old_value: Any, new_value: Any) -> None:
        self._current_operations.append({
            "type": "metadata_update",
            "file_path": str(Path(file_path).resolve()),
            "file_name": file_name,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat(),
        })

    def log_scan(self, new_count: int, updated_count: int, skipped_count: int) -> None:
        self._current_operations.append({
            "type": "scan",
            "new_count": new_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "timestamp": datetime.now().isoformat(),
        })

    def log_export(self, format: str, output_path: str, exported_count: int) -> None:
        self._current_operations.append({
            "type": "export",
            "format": format,
            "output_path": str(output_path),
            "exported_count": exported_count,
            "timestamp": datetime.now().isoformat(),
        })

    def commit(self, description: str = "", command: str = "", db_snapshot: Optional[Dict[str, Any]] = None) -> str:
        if not self._current_operations:
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"op_{timestamp}.json"

        log_data = {
            "id": timestamp,
            "description": description,
            "command": command,
            "timestamp": datetime.now().isoformat(),
            "operations": self._current_operations,
        }

        if db_snapshot is not None:
            log_data["db_snapshot"] = db_snapshot

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        self._current_operations = []
        return timestamp

    def rollback(self, log_id: Optional[str] = None) -> Dict[str, Any]:
        result = {
            "success": True,
            "message": "",
            "actions": [],
            "db_snapshot": None,
            "failed_files": [],
            "file_ops_success": True,
        }

        log_file = self._get_latest_log() if log_id is None else self._get_log_by_id(log_id)
        if log_file is None:
            result["success"] = False
            result["message"] = "没有找到可回滚的操作记录"
            return result

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            result["success"] = False
            result["message"] = "操作日志文件损坏"
            return result

        operations = list(reversed(log_data.get("operations", [])))
        file_op_types = {"move", "rename", "delete"}

        for op in operations:
            action_result = self._rollback_operation(op)
            result["actions"].append(action_result)

            if op.get("type") in file_op_types and not action_result.get("success", True):
                result["file_ops_success"] = False
                result["failed_files"].append({
                    "type": op.get("type"),
                    "file": op.get("file_name", ""),
                    "error": action_result.get("message", ""),
                })

        if result["file_ops_success"]:
            if "db_snapshot" in log_data:
                result["db_snapshot"] = log_data["db_snapshot"]
            log_file.rename(log_file.with_suffix(".rolledback.json"))
            result["message"] = f"已回滚 {len(operations)} 个操作"
        else:
            result["success"] = False
            failed_count = len(result["failed_files"])
            result["message"] = (
                f"有 {failed_count} 个文件回滚失败，索引未恢复，"
                f"日志保留以方便排查。请先手动处理失败的文件后再次尝试回滚。"
            )

        return result

    def _rollback_operation(self, op: Dict[str, Any]) -> Dict[str, Any]:
        op_type = op.get("type")
        result = {"type": op_type, "success": True, "message": ""}

        try:
            if op_type == "move":
                src = Path(op["destination"])
                dst = Path(op["source"])
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    result["message"] = f"已移动回: {dst.name}"
                else:
                    result["success"] = False
                    result["message"] = f"源文件不存在: {src.name}"

            elif op_type == "rename":
                src = Path(op["new_path"])
                dst = Path(op["old_path"])
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    result["message"] = f"已重命名回: {dst.name}"
                else:
                    result["success"] = False
                    result["message"] = f"文件不存在: {src.name}"

            elif op_type == "delete":
                result["success"] = False
                result["message"] = "删除操作无法回滚"

            elif op_type == "metadata_update":
                result["message"] = f"元数据 [{op.get('field', '?')}]: {op.get('old_value', '')} <- {op.get('new_value', '')} (将随索引快照恢复)"

            elif op_type == "scan":
                result["message"] = f"扫描操作 (将随索引快照恢复)"

            elif op_type == "export":
                result["message"] = f"导出操作 ({op.get('format', '?')} -> {op.get('output_path', '?')}) 无需回滚"

        except Exception as e:
            result["success"] = False
            result["message"] = f"回滚失败: {str(e)}"

        return result

    def _get_latest_log(self) -> Optional[Path]:
        log_files = list(self.log_dir.glob("op_*.json"))
        if not log_files:
            return None
        log_files.sort(reverse=True)
        return log_files[0]

    def _get_log_by_id(self, log_id: str) -> Optional[Path]:
        log_file = self.log_dir / f"op_{log_id}.json"
        if log_file.exists():
            return log_file
        return None

    def list_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        log_files = list(self.log_dir.glob("op_*.json"))
        log_files.sort(reverse=True)
        logs = []

        for log_file in log_files[:limit]:
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                ops = data.get("operations", [])
                affected_files = set()
                affected_fields = set()
                op_types = set()

                for op in ops:
                    op_types.add(op.get("type", ""))
                    fn = op.get("file_name") or op.get("file_path", "")
                    if fn:
                        affected_files.add(Path(fn).name if len(fn) > 60 else fn)
                    if op.get("field"):
                        affected_fields.add(op["field"])

                logs.append({
                    "id": data.get("id", log_file.stem),
                    "description": data.get("description", ""),
                    "command": data.get("command", ""),
                    "timestamp": data.get("timestamp", ""),
                    "operations_count": len(ops),
                    "op_types": sorted(op_types),
                    "affected_files": sorted(affected_files),
                    "affected_fields": sorted(affected_fields),
                    "has_snapshot": "db_snapshot" in data,
                })
            except (json.JSONDecodeError, IOError):
                continue

        return logs

    def get_log_detail(self, log_id: str) -> Optional[Dict[str, Any]]:
        log_file = self._get_log_by_id(log_id)
        if log_file is None:
            return None

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        return data

    def clear_current(self) -> None:
        self._current_operations = []

    @property
    def has_pending_operations(self) -> bool:
        return len(self._current_operations) > 0

    @property
    def pending_count(self) -> int:
        return len(self._current_operations)
