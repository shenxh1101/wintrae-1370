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

    def log_file_move(self, source: str, destination: str) -> None:
        self._current_operations.append({
            "type": "move",
            "source": str(Path(source).resolve()),
            "destination": str(Path(destination).resolve()),
            "timestamp": datetime.now().isoformat(),
        })

    def log_file_rename(self, old_path: str, new_path: str) -> None:
        self._current_operations.append({
            "type": "rename",
            "old_path": str(Path(old_path).resolve()),
            "new_path": str(Path(new_path).resolve()),
            "timestamp": datetime.now().isoformat(),
        })

    def log_file_delete(self, file_path: str) -> None:
        self._current_operations.append({
            "type": "delete",
            "file_path": str(Path(file_path).resolve()),
            "timestamp": datetime.now().isoformat(),
        })

    def log_metadata_update(self, file_hash: str, field: str, old_value: Any, new_value: Any) -> None:
        self._current_operations.append({
            "type": "metadata_update",
            "file_hash": file_hash,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat(),
        })

    def commit(self, description: str = "") -> str:
        if not self._current_operations:
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"op_{timestamp}.json"

        log_data = {
            "id": timestamp,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "operations": self._current_operations,
        }

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        self._current_operations = []
        return timestamp

    def rollback(self, log_id: Optional[str] = None) -> Dict[str, Any]:
        result = {"success": True, "message": "", "actions": []}

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

        for op in operations:
            action_result = self._rollback_operation(op)
            result["actions"].append(action_result)

        log_file.rename(log_file.with_suffix(".rolledback.json"))
        result["message"] = f"已回滚 {len(operations)} 个操作"
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
                    result["message"] = f"已移动回: {dst}"
                else:
                    result["success"] = False
                    result["message"] = f"源文件不存在: {src}"

            elif op_type == "rename":
                src = Path(op["new_path"])
                dst = Path(op["old_path"])
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    result["message"] = f"已重命名回: {dst.name}"
                else:
                    result["success"] = False
                    result["message"] = f"文件不存在: {src}"

            elif op_type == "delete":
                result["success"] = False
                result["message"] = "删除操作无法回滚"

            elif op_type == "metadata_update":
                result["message"] = f"元数据更新需手动回滚: {op['field']}"

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

    def list_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        log_files = list(self.log_dir.glob("op_*.json"))
        log_files.sort(reverse=True)
        logs = []

        for log_file in log_files[:limit]:
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logs.append({
                    "id": data.get("id", log_file.stem),
                    "description": data.get("description", ""),
                    "timestamp": data.get("timestamp", ""),
                    "operations_count": len(data.get("operations", [])),
                })
            except (json.JSONDecodeError, IOError):
                continue

        return logs

    def clear_current(self) -> None:
        self._current_operations = []

    @property
    def has_pending_operations(self) -> bool:
        return len(self._current_operations) > 0

    @property
    def pending_count(self) -> int:
        return len(self._current_operations)
