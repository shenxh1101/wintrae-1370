from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..database import PaperDatabase
from ..models import Paper, READ_STATUSES


def export_command(
    directory: str,
    output: str,
    format: str = "bibtex",
    filter_tag: Optional[str] = None,
    filter_topic: Optional[str] = None,
    filter_status: Optional[str] = None,
    group_by_topic: bool = False,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "output": output,
        "format": format,
        "exported": 0,
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
        result["errors"].append("没有匹配的文献可导出")
        return result

    if format == "bibtex":
        content = _export_bibtex(papers, group_by_topic)
    elif format == "csv":
        content = _export_csv(papers)
    elif format == "reading_list":
        content = _export_reading_list(papers, group_by_topic)
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


def _export_bibtex(papers: List[Paper], group_by_topic: bool = False) -> str:
    entries = []

    if group_by_topic:
        topic_groups: Dict[str, List[Paper]] = {}
        topic_groups["未分类"] = []

        for paper in papers:
            if paper.topics:
                topic = paper.topics[0]
            else:
                topic = "未分类"
            if topic not in topic_groups:
                topic_groups[topic] = []
            topic_groups[topic].append(paper)

        for topic, topic_papers in topic_groups.items():
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


def _export_csv(papers: List[Paper]) -> str:
    import io
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "文件名",
        "标题",
        "作者",
        "年份",
        "DOI",
        "期刊",
        "关键词",
        "标签",
        "课题",
        "阅读状态",
        "文件路径",
    ])

    for paper in papers:
        writer.writerow([
            paper.file_name,
            paper.title or "",
            "; ".join(paper.authors),
            paper.year or "",
            paper.doi or "",
            paper.journal or "",
            "; ".join(paper.keywords),
            "; ".join(paper.tags),
            "; ".join(paper.topics),
            paper.read_status,
            paper.file_path,
        ])

    return output.getvalue()


def _export_reading_list(papers: List[Paper], group_by_topic: bool = False) -> str:
    lines = []
    lines.append("# 阅读书单")
    lines.append("")

    if group_by_topic:
        topic_groups: Dict[str, List[Paper]] = {}
        topic_groups["未分类"] = []

        for paper in papers:
            if paper.topics:
                topic = paper.topics[0]
            else:
                topic = "未分类"
            if topic not in topic_groups:
                topic_groups[topic] = []
            topic_groups[topic].append(paper)

        for topic, topic_papers in topic_groups.items():
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
        "unread": "⬜",
        "reading": "📖",
        "read": "✅",
    }.get(paper.read_status, "⬜")

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

    return "\n".join(parts)
