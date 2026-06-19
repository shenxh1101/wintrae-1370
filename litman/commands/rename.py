from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..database import PaperDatabase
from ..models import Paper, sanitize_filename
from ..operation_log import OperationLog


DEFAULT_PATTERN = "{year}_{first_author}_{title}"


def rename_command(
    directory: str,
    pattern: str = DEFAULT_PATTERN,
    dry_run: bool = False,
    resolve_conflicts: str = "prompt",
    move_by_topic: bool = False,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "directory": directory,
        "renamed": 0,
        "conflicts": [],
        "skipped": 0,
        "operations": [],
        "errors": [],
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    papers = db.all_papers()
    if not papers:
        result["errors"].append("数据库中没有文献记录，请先运行 scan 命令")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    planned = _plan_renames(papers, dir_path, pattern, move_by_topic)
    result["conflicts"] = planned["conflicts"]
    result["operations"] = planned["operations"]

    if dry_run:
        result["skipped"] = len(papers) - len(planned["operations"])
        return result

    db_snapshot = db.snapshot()

    confirmed_ops = _resolve_conflicts(planned["operations"], planned["conflicts"], resolve_conflicts)

    for op in confirmed_ops:
        try:
            _execute_rename(op, op_log, db)
            result["renamed"] += 1
        except Exception as e:
            result["errors"].append(f"重命名失败 {op['old_path']}: {str(e)}")

    if op_log.has_pending_operations:
        op_log.commit(
            description=f"重命名 {result['renamed']} 个文件",
            command="rename",
            db_snapshot=db_snapshot,
        )

    db.save()
    return result


def _plan_renames(
    papers: List[Paper],
    base_dir: Path,
    pattern: str,
    move_by_topic: bool,
) -> Dict[str, Any]:
    operations = []
    conflicts = []
    target_paths: Dict[str, List[Paper]] = {}

    for paper in papers:
        old_path = Path(paper.file_path)
        new_name = paper.generate_filename(pattern)

        if move_by_topic and paper.topics:
            topic_dir = base_dir / sanitize_filename(paper.topics[0])
        else:
            topic_dir = old_path.parent

        new_path = topic_dir / new_name

        if str(new_path.resolve()) == str(old_path.resolve()):
            continue

        target_key = str(new_path.resolve())
        if target_key not in target_paths:
            target_paths[target_key] = []
        target_paths[target_key].append(paper)

        operations.append({
            "paper": paper,
            "old_path": str(old_path),
            "new_path": str(new_path),
            "action": "rename" if old_path.parent == new_path.parent else "move",
        })

    for target_path, paper_list in target_paths.items():
        if len(paper_list) > 1:
            conflicts.append({
                "target_path": target_path,
                "papers": paper_list,
            })

    existing_conflicts = _check_disk_conflicts(target_paths)
    for conflict in existing_conflicts:
        if not any(c["target_path"] == conflict["target_path"] for c in conflicts):
            conflicts.append(conflict)

    return {
        "operations": operations,
        "conflicts": conflicts,
    }


def _check_disk_conflicts(target_paths: Dict[str, List[Paper]]) -> List[Dict[str, Any]]:
    conflicts = []
    for target_path, paper_list in target_paths.items():
        path = Path(target_path)
        if path.exists():
            is_own_file = any(
                str(Path(p.file_path).resolve()) == str(path.resolve())
                for p in paper_list
            )
            if not is_own_file:
                conflicts.append({
                    "target_path": target_path,
                    "papers": paper_list,
                    "existing_file": True,
                })
    return conflicts


def _resolve_conflicts(
    operations: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    strategy: str,
) -> List[Dict[str, Any]]:
    if strategy == "skip" or strategy == "prompt":
        conflict_targets = {c["target_path"] for c in conflicts}
        return [op for op in operations if op["new_path"] not in conflict_targets]

    if strategy == "overwrite":
        return operations

    if strategy == "rename":
        conflict_targets = {c["target_path"] for c in conflicts}
        result = []
        name_counters: Dict[str, int] = {}

        for op in operations:
            new_path = op["new_path"]
            if new_path in conflict_targets:
                base = Path(new_path).stem
                ext = Path(new_path).suffix
                counter = name_counters.get(new_path, 1)
                new_name = f"{base}_{counter}{ext}"
                new_path_obj = Path(new_path).with_name(new_name)
                op = dict(op)
                op["new_path"] = str(new_path_obj)
                op["note"] = f"自动加后缀 _{counter}"
                name_counters[new_path] = counter + 1
            result.append(op)
        return result

    return [op for op in operations]


def _execute_rename(
    op: Dict[str, Any],
    op_log: OperationLog,
    db: PaperDatabase,
) -> None:
    old_path = Path(op["old_path"])
    new_path = Path(op["new_path"])

    new_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(old_path), str(new_path))
    action = op.get("action", "rename")
    if action == "move":
        op_log.log_file_move(str(old_path), str(new_path), file_name=old_path.name)
    else:
        op_log.log_file_rename(str(old_path), str(new_path), file_name=old_path.name)

    db.update_paper_path(str(old_path), str(new_path))
