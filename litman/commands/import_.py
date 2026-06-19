from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..database import PaperDatabase
from ..models import Paper, READ_STATUSES
from ..operation_log import OperationLog


IMPORTABLE_FIELDS = ["doi", "journal", "keywords", "topic", "read_status", "title", "authors", "year"]


def import_command(
    directory: str,
    input_file: str,
    fmt: str = "bibtex",
    match_by: str = "filename",
    overwrite: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "matched": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "entries": [],
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    input_path = Path(input_file)
    if not input_path.is_absolute():
        input_path = dir_path / input_path
    if not input_path.exists():
        result["success"] = False
        result["errors"].append(f"导入文件不存在: {input_file}")
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    papers = db.all_papers()
    if not papers:
        result["errors"].append("索引为空，请先执行 scan 命令")
        return result

    try:
        if fmt == "bibtex":
            entries = _parse_bibtex(input_path)
        elif fmt == "csv":
            entries = _parse_csv(input_path)
        else:
            result["success"] = False
            result["errors"].append(f"不支持的导入格式: {fmt}")
            return result
    except Exception as e:
        result["success"] = False
        result["errors"].append(f"解析导入文件失败: {str(e)}")
        return result

    if not entries:
        result["errors"].append("导入文件中没有找到有效条目")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    db_snapshot = db.snapshot() if not dry_run else None

    for entry in entries:
        match_result = _match_paper(entry, papers, match_by)
        paper = match_result["paper"]
        match_reason = match_result["reason"]

        entry_info = {
            "entry_key": entry.get("key", entry.get("filename", "")),
            "matched": paper is not None,
            "match_reason": match_reason,
            "file_name": paper.file_name if paper else None,
            "changes": [],
            "skipped_reason": None,
        }

        if paper is None:
            entry_info["skipped_reason"] = "未找到匹配的文献"
            result["skipped"] += 1
            result["entries"].append(entry_info)
            continue

        result["matched"] += 1

        changes = _apply_import(paper, entry, overwrite)

        if not changes:
            entry_info["skipped_reason"] = "没有需要更新的字段"
            result["skipped"] += 1
            result["entries"].append(entry_info)
            continue

        entry_info["changes"] = changes

        if not dry_run:
            for field, old_val, new_val in changes:
                op_log.log_metadata_update(
                    file_path=paper.file_path,
                    file_name=paper.file_name,
                    field=field,
                    old_value=old_val,
                    new_value=new_val,
                )
            paper.touch()
            db.update_paper(paper)
            result["updated"] += 1

        result["entries"].append(entry_info)

    if not dry_run and op_log.has_pending_operations:
        op_log.commit(
            description=f"从 {fmt} 导入更新 {result['updated']} 篇文献元数据",
            command="import",
            db_snapshot=db_snapshot,
        )
        db.save()

    return result


def _parse_bibtex(file_path: Path) -> List[Dict[str, Any]]:
    content = file_path.read_text(encoding="utf-8-sig")
    entries = []

    i = 0
    while i < len(content):
        if content[i] == "@":
            j = content.find("{", i)
            if j == -1:
                break

            entry_type = content[i+1:j].strip().lower()

            brace_depth = 1
            k = j + 1
            while k < len(content) and brace_depth > 0:
                if content[k] == "{":
                    brace_depth += 1
                elif content[k] == "}":
                    brace_depth -= 1
                k += 1

            full_body = content[j+1:k-1]

            comma_pos = full_body.find(",")
            if comma_pos == -1:
                key = full_body.strip()
                fields_body = ""
            else:
                key = full_body[:comma_pos].strip()
                fields_body = full_body[comma_pos+1:]

            entry = {"key": key, "type": entry_type}

            fields = _parse_bibtex_fields(fields_body)
            for field, value in fields.items():
                field = field.lower()
                if field == "author":
                    entry["authors"] = [a.strip() for a in re.split(r"\s+and\s+", value)]
                elif field == "keywords":
                    entry["keywords"] = [kw.strip() for kw in re.split(r"[,;]", value) if kw.strip()]
                elif field == "year":
                    try:
                        entry["year"] = int(value)
                    except (ValueError, TypeError):
                        entry["year"] = None
                elif field == "file":
                    entry["filename"] = value
                elif field == "read_status":
                    status_map = {
                        "unread": "unread",
                        "reading": "reading",
                        "read": "read",
                    }
                    entry["read_status"] = status_map.get(value.lower(), value)
                else:
                    entry[field] = value

            entries.append(entry)
            i = k
        else:
            i += 1

    return entries


def _parse_bibtex_fields(body: str) -> Dict[str, str]:
    fields = {}
    i = 0

    while i < len(body):
        while i < len(body) and body[i] in " \t\n\r":
            i += 1
        if i >= len(body):
            break

        eq_pos = body.find("=", i)
        if eq_pos == -1:
            break

        field_name = body[i:eq_pos].strip()
        i = eq_pos + 1

        while i < len(body) and body[i] in " \t\n\r":
            i += 1
        if i >= len(body):
            break

        if body[i] == "{":
            brace_depth = 1
            j = i + 1
            while j < len(body) and brace_depth > 0:
                if body[j] == "{":
                    brace_depth += 1
                elif body[j] == "}":
                    brace_depth -= 1
                j += 1
            value = body[i+1:j-1].strip()
            i = j
            while i < len(body) and body[i] in ", \t\n\r":
                i += 1
        else:
            comma_pos = body.find(",", i)
            if comma_pos == -1:
                value = body[i:].strip()
                i = len(body)
            else:
                value = body[i:comma_pos].strip()
                i = comma_pos + 1

        fields[field_name] = value

    return fields


def _parse_csv(file_path: Path) -> List[Dict[str, Any]]:
    entries = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {}
            for k, v in row.items():
                if not v:
                    continue
                k = k.strip().lower()
                v = v.strip()

                if k in ["作者", "authors", "author"]:
                    entry["authors"] = [a.strip() for a in re.split(r"[;,]", v) if a.strip()]
                elif k in ["关键词", "keywords", "keyword"]:
                    entry["keywords"] = [kw.strip() for kw in re.split(r"[;,]", v) if kw.strip()]
                elif k in ["年份", "year"]:
                    try:
                        entry["year"] = int(v)
                    except (ValueError, TypeError):
                        pass
                elif k in ["文件名", "file", "filename"]:
                    entry["filename"] = v
                elif k in ["doi"]:
                    entry["doi"] = v
                elif k in ["期刊", "journal"]:
                    entry["journal"] = v
                elif k in ["课题", "topic", "topics"]:
                    entry["topic"] = v
                elif k in ["阅读状态", "read_status", "status"]:
                    status_map = {
                        "未读": "unread",
                        "阅读中": "reading",
                        "已读": "read",
                        "unread": "unread",
                        "reading": "reading",
                        "read": "read",
                    }
                    entry["read_status"] = status_map.get(v.lower(), v)
                elif k in ["标题", "title"]:
                    entry["title"] = v

            if entry:
                entries.append(entry)

    return entries


def _match_paper(
    entry: Dict[str, Any],
    papers: List[Paper],
    match_by: str,
) -> Dict[str, Any]:
    result = {"paper": None, "reason": ""}

    if match_by in ["filename", "both"]:
        filename = entry.get("filename") or entry.get("key") or entry.get("file")
        if filename:
            filename_lower = Path(filename).stem.lower()
            exact_match = None
            fuzzy_match = None
            for paper in papers:
                paper_stem = Path(paper.file_name).stem.lower()
                if filename_lower == paper_stem:
                    exact_match = paper
                    break
                elif filename_lower in paper_stem or paper_stem in filename_lower:
                    if fuzzy_match is None:
                        fuzzy_match = paper
            if exact_match:
                result["paper"] = exact_match
                result["reason"] = f"文件名精确匹配: {filename} <-> {exact_match.file_name}"
                return result
            elif fuzzy_match:
                result["paper"] = fuzzy_match
                result["reason"] = f"文件名模糊匹配: {filename} <-> {fuzzy_match.file_name}"
                return result

    if match_by in ["doi", "both"]:
        doi = entry.get("doi")
        if doi:
            doi_lower = doi.lower()
            for paper in papers:
                if paper.doi and paper.doi.lower() == doi_lower:
                    result["paper"] = paper
                    result["reason"] = f"DOI 匹配: {doi}"
                    return result

    title = entry.get("title")
    if title:
        title_lower = title.lower().strip()
        for paper in papers:
            if paper.title and paper.title.lower().strip() == title_lower:
                result["paper"] = paper
                result["reason"] = f"标题匹配: {title}"
                return result

    return result


def _apply_import(
    paper: Paper,
    entry: Dict[str, Any],
    overwrite: bool,
) -> List[Tuple[str, Any, Any]]:
    changes = []

    field_mappings = [
        ("doi", "doi"),
        ("journal", "journal"),
        ("title", "title"),
        ("year", "year"),
    ]

    for entry_field, paper_field in field_mappings:
        if entry_field in entry:
            new_val = entry[entry_field]
            old_val = getattr(paper, paper_field)
            if overwrite or old_val is None or old_val == "" or old_val == []:
                if old_val != new_val:
                    setattr(paper, paper_field, new_val)
                    changes.append((paper_field, old_val, new_val))

    if "authors" in entry:
        new_val = entry["authors"]
        old_val = paper.authors
        if overwrite or not old_val:
            if old_val != new_val:
                paper.authors = new_val
                changes.append(("authors", list(old_val), list(new_val)))

    if "keywords" in entry:
        new_kws = entry["keywords"]
        old_val = list(paper.keywords)
        added = False
        for kw in new_kws:
            if kw not in paper.keywords:
                paper.keywords.append(kw)
                added = True
        if added:
            changes.append(("keywords", old_val, list(paper.keywords)))

    if "topic" in entry:
        topic = entry["topic"]
        if topic and topic not in paper.topics:
            old_val = list(paper.topics)
            paper.topics.append(topic)
            changes.append(("topics", old_val, list(paper.topics)))

    if "read_status" in entry:
        new_status = entry["read_status"]
        if new_status in READ_STATUSES and paper.read_status != new_status:
            if overwrite or paper.read_status == "unread":
                old_val = paper.read_status
                paper.read_status = new_status
                changes.append(("read_status", old_val, new_status))

    return changes


def format_import_result(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"匹配: {result['matched']} 条 | 更新: {result['updated']} 条 | 跳过: {result['skipped']} 条")
    lines.append("")

    for i, entry in enumerate(result["entries"], 1):
        key = entry["entry_key"]
        matched = entry["matched"]
        status = "[匹配]" if matched else "[跳过]"
        reason = entry["match_reason"]

        lines.append(f"{i}. {status} {key}")
        if reason:
            lines.append(f"   {reason}")

        if entry["skipped_reason"]:
            lines.append(f"   [跳过] {entry['skipped_reason']}")

        if entry["changes"]:
            for field, old, new in entry["changes"]:
                old_str = str(old) if old not in (None, "", []) else "(空)"
                new_str = str(new) if new not in (None, "", []) else "(空)"
                if len(old_str) > 30:
                    old_str = old_str[:27] + "..."
                if len(new_str) > 30:
                    new_str = new_str[:27] + "..."
                lines.append(f"   [更新] {field}: {old_str} -> {new_str}")

        lines.append("")

    return "\n".join(lines)
