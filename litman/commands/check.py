from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional

from ..database import PaperDatabase
from ..metadata import verify_pdf_integrity
from ..models import Paper


def check_command(
    directory: str,
    check_duplicates: bool = True,
    check_missing: bool = True,
    check_integrity: bool = True,
    missing_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "duplicates": [],
        "missing_metadata": [],
        "corrupted_files": [],
        "total_checked": 0,
        "issues_found": 0,
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["issues_found"] = -1
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    papers = db.all_papers()
    result["total_checked"] = len(papers)

    if check_duplicates:
        dup_groups = db.find_duplicates()
        result["duplicates"] = [
            {
                "reason": group["reason"],
                "papers": [
                    {
                        "file": p.file_name,
                        "path": p.file_path,
                        "title": p.title,
                        "doi": p.doi,
                        "hash": p.file_hash[:12],
                    }
                    for p in group["papers"]
                ],
            }
            for group in dup_groups
        ]
        result["issues_found"] += len(result["duplicates"])

    if check_missing:
        missing_items = db.get_missing_metadata(missing_fields)
        result["missing_metadata"] = [
            {
                "file": item["paper"].file_name,
                "title": item["paper"].title,
                "path": item["paper"].file_path,
                "missing_fields": item["missing_fields"],
            }
            for item in missing_items
        ]
        result["issues_found"] += len(result["missing_metadata"])

    if check_integrity:
        for paper in papers:
            file_path = Path(paper.file_path)
            if not file_path.exists():
                result["corrupted_files"].append({
                    "file": paper.file_name,
                    "path": paper.file_path,
                    "issue": "文件不存在",
                })
                result["issues_found"] += 1
                continue

            is_valid, message = verify_pdf_integrity(str(file_path))
            if not is_valid:
                result["corrupted_files"].append({
                    "file": paper.file_name,
                    "path": paper.file_path,
                    "issue": message,
                })
                result["issues_found"] += 1

    return result


def format_check_report(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"共检查 {result['total_checked']} 篇文献")
    lines.append(f"发现 {result['issues_found']} 个问题")
    lines.append("")

    if result["duplicates"]:
        lines.append(f"[重复文献] {len(result['duplicates'])} 组")
        for i, dup in enumerate(result["duplicates"], 1):
            lines.append(f"  第 {i} 组 ({dup['reason']}):")
            for p in dup["papers"]:
                doi_info = f"  DOI: {p['doi']}" if p.get("doi") else ""
                hash_info = f"  hash: {p['hash']}..." if p.get("hash") else ""
                lines.append(f"    - {p['file']}{doi_info}{hash_info}")
        lines.append("")

    if result["missing_metadata"]:
        lines.append(f"[缺失元数据] {len(result['missing_metadata'])} 篇")
        for p in result["missing_metadata"][:10]:
            missing = ", ".join(p["missing_fields"])
            title = p["title"] or "(无标题)"
            lines.append(f"  - {p['file']}: 缺少 {missing}")
        if len(result["missing_metadata"]) > 10:
            lines.append(f"  ... 还有 {len(result['missing_metadata']) - 10} 篇")
        lines.append("")

    if result["corrupted_files"]:
        lines.append(f"[文件损坏] {len(result['corrupted_files'])} 个")
        for p in result["corrupted_files"]:
            lines.append(f"  - {p['file']}: {p['issue']}")
        lines.append("")

    if result["issues_found"] == 0:
        lines.append("所有检查通过!")

    return "\n".join(lines)
