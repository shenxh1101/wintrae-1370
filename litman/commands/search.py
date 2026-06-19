from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..database import PaperDatabase
from ..models import Paper, READ_STATUSES


def search_command(
    directory: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    doi: Optional[str] = None,
    journal: Optional[str] = None,
    keyword: Optional[List[str]] = None,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    file_filter: Optional[str] = None,
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "matched": 0,
        "papers": [],
        "errors": [],
        "active_filters": _build_filter_desc(
            title, author, year_min, year_max, doi, journal,
            keyword, topic, status, file_filter, tag,
        ),
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
        result["errors"].append(f"索引为空，请先执行 scan 命令 (筛选条件: {result['active_filters']})")
        return result

    matched = []
    for paper in papers:
        match_result = _check_match(
            paper, title, author, year_min, year_max,
            doi, journal, keyword, topic, status, file_filter, tag,
        )
        if match_result["matched"]:
            matched.append({
                "paper": paper,
                "reasons": match_result["reasons"],
            })

    if not matched:
        result["errors"].append(
            f"没有匹配的文献 (筛选条件: {result['active_filters']})"
        )
        return result

    matched.sort(key=lambda m: (len(m["reasons"]), m["paper"].year or 0), reverse=True)
    result["matched"] = len(matched)
    result["papers"] = matched

    return result


def _check_match(
    paper: Paper,
    title: Optional[str],
    author: Optional[str],
    year_min: Optional[int],
    year_max: Optional[int],
    doi: Optional[str],
    journal: Optional[str],
    keyword: Optional[List[str]],
    topic: Optional[str],
    status: Optional[str],
    file_filter: Optional[str],
    tag: Optional[str],
) -> Dict[str, Any]:
    reasons: List[str] = []
    all_conditions_met = True

    if title:
        title_lower = title.lower()
        if paper.title and title_lower in paper.title.lower():
            reasons.append(f"标题匹配: '{title}'")
        else:
            all_conditions_met = False

    if author:
        author_lower = author.lower()
        author_match = any(author_lower in a.lower() for a in paper.authors)
        if author_match:
            reasons.append(f"作者匹配: '{author}'")
        else:
            all_conditions_met = False

    if year_min is not None or year_max is not None:
        if paper.year:
            y = paper.year
            min_ok = (year_min is None) or (y >= year_min)
            max_ok = (year_max is None) or (y <= year_max)
            if min_ok and max_ok:
                range_desc = []
                if year_min is not None:
                    range_desc.append(f">={year_min}")
                if year_max is not None:
                    range_desc.append(f"<={year_max}")
                reasons.append(f"年份匹配: {y} ({', '.join(range_desc)})")
            else:
                all_conditions_met = False
        else:
            all_conditions_met = False

    if doi:
        doi_lower = doi.lower()
        if paper.doi and doi_lower in paper.doi.lower():
            reasons.append(f"DOI 匹配: '{doi}'")
        else:
            all_conditions_met = False

    if journal:
        journal_lower = journal.lower()
        if paper.journal and journal_lower in paper.journal.lower():
            reasons.append(f"期刊匹配: '{journal}'")
        else:
            all_conditions_met = False

    if keyword:
        kw_matched = []
        for kw in keyword:
            kw_lower = kw.lower()
            if kw_lower in [k.lower() for k in paper.keywords]:
                kw_matched.append(kw)
            elif paper.title and kw_lower in paper.title.lower():
                kw_matched.append(kw)
        if kw_matched:
            reasons.append(f"关键词匹配: {', '.join(repr(k) for k in kw_matched)}")
        else:
            all_conditions_met = False

    if topic:
        if topic in paper.topics:
            reasons.append(f"课题匹配: '{topic}'")
        else:
            all_conditions_met = False

    if status:
        if paper.read_status == status:
            status_desc = {"unread": "未读", "reading": "阅读中", "read": "已读"}.get(status, status)
            reasons.append(f"阅读状态匹配: {status_desc}")
        else:
            all_conditions_met = False

    if tag:
        if tag in paper.tags:
            reasons.append(f"标签匹配: '{tag}'")
        else:
            all_conditions_met = False

    if file_filter:
        filter_lower = file_filter.lower()
        if filter_lower in paper.file_name.lower():
            reasons.append(f"文件名匹配: '{file_filter}'")
        elif paper.title and filter_lower in paper.title.lower():
            reasons.append(f"标题匹配: '{file_filter}'")
        else:
            all_conditions_met = False

    return {"matched": all_conditions_met, "reasons": reasons}


def _build_filter_desc(
    title: Optional[str],
    author: Optional[str],
    year_min: Optional[int],
    year_max: Optional[int],
    doi: Optional[str],
    journal: Optional[str],
    keyword: Optional[List[str]],
    topic: Optional[str],
    status: Optional[str],
    file_filter: Optional[str],
    tag: Optional[str],
) -> str:
    parts = []
    if title:
        parts.append(f"title={title}")
    if author:
        parts.append(f"author={author}")
    if year_min is not None or year_max is not None:
        yr = []
        if year_min is not None:
            yr.append(f">={year_min}")
        if year_max is not None:
            yr.append(f"<={year_max}")
        parts.append(f"year={''.join(yr)}")
    if doi:
        parts.append(f"doi={doi}")
    if journal:
        parts.append(f"journal={journal}")
    if keyword:
        parts.append(f"keyword={','.join(keyword)}")
    if topic:
        parts.append(f"topic={topic}")
    if status:
        parts.append(f"status={status}")
    if tag:
        parts.append(f"tag={tag}")
    if file_filter:
        parts.append(f"fuzzy={file_filter}")
    return ", ".join(parts) if parts else "无筛选（列出所有文献）"


def format_search_results(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"筛选条件: {result['active_filters']}")
    lines.append(f"找到 {result['matched']} 篇匹配文献")
    lines.append("")

    for i, item in enumerate(result["papers"], 1):
        paper = item["paper"]
        reasons = item["reasons"]

        title = paper.title or paper.file_name
        authors = ", ".join(paper.authors[:2]) if paper.authors else "Unknown"
        year = f"({paper.year})" if paper.year else ""
        topics = f" [课题: {', '.join(paper.topics)}]" if paper.topics else ""
        rating = f" {'★' * paper.rating}" if paper.rating else ""
        due = f" [截止: {paper.due_date}]" if paper.due_date else ""

        lines.append(f"{i}. {title}{rating}")
        lines.append(f"   {authors} {year}{topics}{due}")

        if paper.journal:
            lines.append(f"   *{paper.journal}*")

        if reasons:
            reason_str = ", ".join(reasons)
            lines.append(f"   [匹配] {reason_str}")

        missing = _get_missing_fields(paper)
        if missing:
            lines.append(f"   [缺失: {', '.join(missing)}]")

        lines.append("")

    return "\n".join(lines)


def _get_missing_fields(paper: Paper) -> List[str]:
    fields = ["title", "authors", "year", "doi", "journal", "keywords"]
    missing = []
    for field in fields:
        value = getattr(paper, field, None)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing
