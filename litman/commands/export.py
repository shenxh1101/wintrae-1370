from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..database import PaperDatabase
from ..models import Paper, READ_STATUSES
from ..operation_log import OperationLog


def export_command(
    directory: str,
    output: str,
    format: str = "bibtex",
    filter_tag: Optional[str] = None,
    filter_topic: Optional[str] = None,
    filter_status: Optional[str] = None,
    group_by_topic: bool = False,
) -> Dict[str, Any]:
    active_filters = _build_filter_desc(filter_tag, filter_topic, filter_status)

    result = {
        "success": True,
        "output": output,
        "format": format,
        "exported": 0,
        "active_filters": active_filters,
        "errors": [],
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    papers = _filter_papers(db, filter_tag, filter_topic, filter_status)

    if not papers:
        result["errors"].append(
            f"没有匹配的文献可导出 (筛选条件: {active_filters})"
        )
        return result

    if format == "bibtex":
        content = _export_bibtex(papers, group_by_topic)
    elif format == "csv":
        content = _export_csv(papers, db, group_by_topic)
    elif format == "reading_list":
        content = _export_reading_list(papers, db, group_by_topic)
    else:
        result["success"] = False
        result["errors"].append(f"不支持的导出格式: {format}")
        return result

    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = dir_path / output

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        result["exported"] = len(papers)
    except IOError as e:
        result["success"] = False
        result["errors"].append(f"写入文件失败: {str(e)}")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))
    op_log.log_export(format=format, output_path=str(output_path), exported_count=len(papers))
    op_log.commit(description=f"导出 {len(papers)} 篇文献 ({format})", command="export")

    return result


def _build_filter_desc(
    filter_tag: Optional[str],
    filter_topic: Optional[str],
    filter_status: Optional[str],
) -> str:
    parts = []
    if filter_tag:
        parts.append(f"tag={filter_tag}")
    if filter_topic:
        parts.append(f"topic={filter_topic}")
    if filter_status:
        parts.append(f"status={filter_status}")
    return ", ".join(parts) if parts else "无筛选"


def _filter_papers(
    db: PaperDatabase,
    filter_tag: Optional[str] = None,
    filter_topic: Optional[str] = None,
    filter_status: Optional[str] = None,
) -> List[Paper]:
    papers = db.all_papers()

    if filter_tag:
        papers = [p for p in papers if filter_tag in p.tags]

    if filter_topic:
        papers = [p for p in papers if filter_topic in p.topics]

    if filter_status:
        papers = [p for p in papers if p.read_status == filter_status]

    return sorted(papers, key=lambda p: (p.year or 0, p.title or ""))


def _group_by_topic(papers: List[Paper]) -> Dict[str, List[Paper]]:
    topic_groups: Dict[str, List[Paper]] = {}
    for paper in papers:
        if paper.topics:
            topic = paper.topics[0]
        else:
            topic = "未分类"
        if topic not in topic_groups:
            topic_groups[topic] = []
        topic_groups[topic].append(paper)
    return topic_groups


def _get_missing_fields(paper: Paper) -> List[str]:
    fields = ["title", "authors", "year", "doi", "journal", "keywords"]
    missing = []
    for field in fields:
        value = getattr(paper, field, None)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def _export_bibtex(papers: List[Paper], group_by_topic: bool = False) -> str:
    entries = []

    if group_by_topic:
        for topic, topic_papers in _group_by_topic(papers).items():
            entries.append(f"% ===== {topic} =====\n")
            for paper in topic_papers:
                entries.append(_paper_to_bibtex(paper))
                entries.append("")
    else:
        for paper in papers:
            entries.append(_paper_to_bibtex(paper))
            entries.append("")

    return "\n".join(entries)


def _paper_to_bibtex(paper: Paper) -> str:
    key = _generate_bibtex_key(paper)
    entry_type = "article" if paper.journal else "misc"

    lines = [f"@{entry_type}{{{key},"]

    if paper.title:
        lines.append(f"  title = {{{paper.title}}},")

    if paper.authors:
        authors_str = " and ".join(paper.authors)
        lines.append(f"  author = {{{authors_str}}},")

    if paper.year:
        lines.append(f"  year = {{{paper.year}}},")

    if paper.journal:
        lines.append(f"  journal = {{{paper.journal}}},")

    if paper.doi:
        lines.append(f"  doi = {{{paper.doi}}},")

    if paper.keywords:
        kw_str = ", ".join(paper.keywords)
        lines.append(f"  keywords = {{{kw_str}}},")

    lines.append(f"  file = {{{paper.file_name}}},")

    lines.append("}")
    return "\n".join(lines)


def _generate_bibtex_key(paper: Paper) -> str:
    first_author = paper.authors[0] if paper.authors else "unknown"
    last_name = first_author.split()[-1] if first_author else "unknown"
    last_name = re.sub(r"[^a-zA-Z]", "", last_name) or "unknown"
    year = str(paper.year) if paper.year else "n.d."

    title = paper.title or "untitled"
    first_word = re.sub(r"[^a-zA-Z]", "", title.split()[0]) if title.split() else ""
    first_word = first_word.lower() if first_word else "paper"

    return f"{last_name}{year}_{first_word}"


def _export_csv(papers: List[Paper], db: PaperDatabase, group_by_topic: bool = False) -> str:
    import io
    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        "课题", "文件名", "标题", "作者", "年份",
        "DOI", "期刊", "关键词", "标签", "阅读状态",
        "缺失元数据", "文件路径",
    ]
    writer.writerow(header)

    if group_by_topic:
        for topic, topic_papers in _group_by_topic(papers).items():
            for paper in topic_papers:
                missing = _get_missing_fields(paper)
                writer.writerow([
                    topic,
                    paper.file_name,
                    paper.title or "",
                    "; ".join(paper.authors),
                    paper.year or "",
                    paper.doi or "",
                    paper.journal or "",
                    "; ".join(paper.keywords),
                    "; ".join(paper.tags),
                    paper.read_status,
                    "; ".join(missing) if missing else "",
                    paper.file_path,
                ])
    else:
        for paper in papers:
            topic = paper.topics[0] if paper.topics else ""
            missing = _get_missing_fields(paper)
            writer.writerow([
                topic,
                paper.file_name,
                paper.title or "",
                "; ".join(paper.authors),
                paper.year or "",
                paper.doi or "",
                paper.journal or "",
                "; ".join(paper.keywords),
                "; ".join(paper.tags),
                paper.read_status,
                "; ".join(missing) if missing else "",
                paper.file_path,
            ])

    return output.getvalue()


def _export_reading_list(papers: List[Paper], db: PaperDatabase, group_by_topic: bool = False) -> str:
    lines = []
    lines.append("# 阅读书单")
    lines.append("")

    if group_by_topic:
        for topic, topic_papers in _group_by_topic(papers).items():
            lines.append(f"## {topic}")
            lines.append("")
            for i, paper in enumerate(topic_papers, 1):
                lines.append(f"{i}. {_format_reading_entry(paper)}")
                lines.append("")
    else:
        for i, paper in enumerate(papers, 1):
            lines.append(f"{i}. {_format_reading_entry(paper)}")
            lines.append("")

    return "\n".join(lines)


def _format_reading_entry(paper: Paper) -> str:
    parts = []

    status_icon = {
        "unread": "[ ]",
        "reading": "[~]",
        "read": "[x]",
    }.get(paper.read_status, "[ ]")

    title = paper.title or paper.file_name
    authors = ", ".join(paper.authors[:3]) if paper.authors else "Unknown"
    year = f"({paper.year})" if paper.year else ""

    parts.append(f"{status_icon} **{title}**")
    parts.append(f"   {authors} {year}")

    if paper.journal:
        parts.append(f"   *{paper.journal}*")

    if paper.doi:
        parts.append(f"   DOI: {paper.doi}")

    if paper.tags:
        tags = " ".join(f"#{tag}" for tag in paper.tags)
        parts.append(f"   {tags}")

    missing = _get_missing_fields(paper)
    if missing:
        parts.append(f"   [缺失: {', '.join(missing)}]")

    return "\n".join(parts)
