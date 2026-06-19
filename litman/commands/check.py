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
        duplicates = db.find_duplicates()
        result["duplicates"] = [
            {
                "reason": _deduce_duplicate_reason(group),
                "papers": [
                    {
                        "file": p.file_name,
                        "path": p.file_path,
                        "title": p.title,
                        "doi": p.doi,
                    }
                    for p in group
                ],
            }
            for group in duplicates
        ]
        result["issues_found"] += len(result["duplicates"])

    if check_missing:
        missing = db.get_missing_metadata(missing_fields)
        result["missing_metadata"] = [
            {
                "file": p.file_name,
                "title": p.title,
                "missing_fields": _get_missing_fields(p, missing_fields),
            }
            for p in missing
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


def _deduce_duplicate_reason(group: List[Paper]) -> str:
    if len(group) < 2:
        return "unknown"

    hashes = {p.file_hash for p in group}
    if len(hashes) == 1:
        return "内容完全相同"

    dois = {p.doi for p in group if p.doi}
    if len(dois) == 1 and len(group) > 1:
        return "DOI 相同"

    titles = {p.title.lower() for p in group if p.title}
    if len(titles) == 1 and len(group) > 1:
        return "标题相同"

    return "疑似重复"


def _get_missing_fields(paper: Paper, fields: Optional[List[str]] = None) -> List[str]:
    if fields is None:
        fields = ["title", "authors", "year", "doi", "journal", "keywords"]

    missing = []
    for field in fields:
        value = getattr(paper, field, None)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def format_check_report(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"共检查 {result['total_checked']} 篇文献")
    lines.append(f"发现 {result['issues_found']} 个问题")
    lines.append("")

    if result["duplicates"]:
        lines.append(f"【重复文献】{len(result['duplicates'])} 组")
        for i, dup in enumerate(result["duplicates"], 1):
            lines.append(f"  第 {i} 组 ({dup['reason']}):")
            for p in dup["papers"]:
                lines.append(f"    - {p['file']}")
        lines.append("")

    if result["missing_metadata"]:
        lines.append(f"【缺失元数据】{len(result['missing_metadata'])} 篇")
        for p in result["missing_metadata"][:10]:
            missing = ", ".join(p["missing_fields"])
            title = p["title"] or "(无标题)"
            lines.append(f"  - {p['file']}: 缺少 {missing}")
        if len(result["missing_metadata"]) > 10:
            lines.append(f"  ... 还有 {len(result['missing_metadata']) - 10} 篇")
        lines.append("")

    if result["corrupted_files"]:
        lines.append(f"【文件损坏】{len(result['corrupted_files'])} 个")
        for p in result["corrupted_files"]:
            lines.append(f"  - {p['file']}: {p['issue']}")
        lines.append("")

    if result["issues_found"] == 0:
        lines.append("所有检查通过！")

    return "\n".join(lines)
