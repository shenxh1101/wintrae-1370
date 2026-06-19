from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any

from ..database import PaperDatabase
from ..metadata import scan_pdfs, enrich_paper
from ..models import Paper
from ..operation_log import OperationLog


def scan_command(
    directory: str,
    recursive: bool = True,
    no_extract: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "directory": directory,
        "scanned": 0,
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "papers": [],
        "errors": [],
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    if not dir_path.is_dir():
        result["success"] = False
        result["errors"].append(f"不是目录: {directory}")
        return result

    pdf_files = scan_pdfs(str(dir_path), recursive=recursive)
    result["scanned"] = len(pdf_files)

    if not pdf_files:
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))
    db_snapshot = db.snapshot() if not dry_run else None

    for pdf_path in pdf_files:
        try:
            paper_info = _process_pdf(pdf_path, db, no_extract)
            status = paper_info["status"]

            if status == "new":
                result["new"] += 1
            elif status == "updated":
                result["updated"] += 1
            else:
                result["skipped"] += 1

            result["papers"].append(paper_info)

            if not dry_run and status in ("new", "updated"):
                paper = paper_info["paper"]
                db.add_paper(paper)
                if status == "new":
                    op_log.log_metadata_update(
                        file_path=paper.file_path,
                        file_name=paper.file_name,
                        field="index",
                        old_value=None,
                        new_value="added",
                    )
                else:
                    op_log.log_metadata_update(
                        file_path=paper.file_path,
                        file_name=paper.file_name,
                        field="index",
                        old_value="existing",
                        new_value="updated",
                    )

        except Exception as e:
            result["errors"].append(f"处理失败 {pdf_path}: {str(e)}")

    if not dry_run:
        op_log.log_scan(
            new_count=result["new"],
            updated_count=result["updated"],
            skipped_count=result["skipped"],
        )
        if result["new"] > 0 or result["updated"] > 0:
            op_log.commit(
                description=f"扫描目录，新增 {result['new']} 篇，更新 {result['updated']} 篇",
                command="scan",
                db_snapshot=db_snapshot,
            )
        db.save()

    return result


def _process_pdf(
    file_path: str,
    db: PaperDatabase,
    no_extract: bool = False,
) -> Dict[str, Any]:
    paper = Paper.from_file(file_path)
    existing = db.find_by_path(file_path)

    if existing:
        if existing.file_path == paper.file_path and existing.file_hash == paper.file_hash:
            return {
                "paper": existing,
                "status": "skipped",
                "reason": "已存在且内容未变",
            }
        if existing.file_hash != paper.file_hash:
            if not no_extract:
                paper = enrich_paper(paper, use_filename=True)
            return {
                "paper": paper,
                "status": "updated",
                "reason": "文件内容已变化",
            }

    if not no_extract:
        paper = enrich_paper(paper, use_filename=True)

    if existing:
        return {
            "paper": paper,
            "status": "updated",
            "reason": "路径已更新",
        }

    return {
        "paper": paper,
        "status": "new",
        "reason": "新文件",
    }


def get_scan_summary(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"扫描目录: {result['directory']}")
    lines.append(f"发现 PDF: {result['scanned']} 个")
    lines.append(f"  新增: {result['new']}")
    lines.append(f"  更新: {result['updated']}")
    lines.append(f"  跳过: {result['skipped']}")

    if result["errors"]:
        lines.append(f"错误: {len(result['errors'])} 个")
        for err in result["errors"][:5]:
            lines.append(f"  - {err}")
        if len(result["errors"]) > 5:
            lines.append(f"  ... 还有 {len(result['errors']) - 5} 个错误")

    return "\n".join(lines)
