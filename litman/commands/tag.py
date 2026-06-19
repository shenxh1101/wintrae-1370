from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..database import PaperDatabase
from ..models import Paper, sanitize_filename, READ_STATUSES
from ..operation_log import OperationLog


def tag_command(
    directory: str,
    add_tags: Optional[List[str]] = None,
    remove_tags: Optional[List[str]] = None,
    set_status: Optional[str] = None,
    set_doi: Optional[str] = None,
    set_journal: Optional[str] = None,
    add_keywords: Optional[List[str]] = None,
    add_topic: Optional[str] = None,
    filter_tag: Optional[str] = None,
    filter_topic: Optional[str] = None,
    filter_status: Optional[str] = None,
    file_filter: Optional[str] = None,
    list_tags: bool = False,
    list_topics: bool = False,
    move_to_topic: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    result = {
        "success": True,
        "updated": 0,
        "tags": [],
        "topics": [],
        "papers": [],
        "errors": [],
        "active_filters": _build_filter_desc(filter_tag, filter_topic, filter_status, file_filter),
    }

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        result["success"] = False
        result["errors"].append(f"目录不存在: {directory}")
        return result

    db = PaperDatabase.for_directory(str(dir_path))
    db.load()

    if list_tags:
        result["tags"] = db.get_all_tags()
        return result

    if list_topics:
        result["topics"] = db.get_all_topics()
        return result

    if set_status and set_status not in READ_STATUSES:
        result["success"] = False
        result["errors"].append(f"无效的阅读状态: {set_status}，可选值: {', '.join(READ_STATUSES)}")
        return result

    papers = _filter_papers(db, filter_tag, filter_topic, filter_status, file_filter)

    if not papers:
        result["errors"].append(f"没有匹配的文献 (筛选条件: {result['active_filters']})")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    db_snapshot = db.snapshot() if not dry_run else None

    for paper in papers:
        updated = False
        changes = _apply_metadata_changes(
            paper, add_tags, remove_tags, set_status,
            set_doi, set_journal, add_keywords, add_topic,
        )
        if changes:
            updated = True
            for field, old_val, new_val in changes:
                if not dry_run:
                    op_log.log_metadata_update(
                        file_path=paper.file_path,
                        file_name=paper.file_name,
                        field=field,
                        old_value=old_val,
                        new_value=new_val,
                    )

        if move_to_topic and paper.topics:
            moved = _move_paper_to_topic(paper, paper.topics[0], dir_path, op_log, dry_run)
            if moved:
                updated = True

        if updated:
            result["updated"] += 1
            result["papers"].append({
                "file": paper.file_name,
                "title": paper.title,
            })

            if not dry_run:
                paper.touch()
                db.update_paper(paper)

    if not dry_run and op_log.has_pending_operations:
        op_log.commit(
            description=f"更新 {result['updated']} 个文献的标签/元数据",
            command="tag",
            db_snapshot=db_snapshot,
        )

    if not dry_run:
        db.save()

    return result


def _apply_metadata_changes(
    paper: Paper,
    add_tags: Optional[List[str]],
    remove_tags: Optional[List[str]],
    set_status: Optional[str],
    set_doi: Optional[str],
    set_journal: Optional[str],
    add_keywords: Optional[List[str]],
    add_topic: Optional[str],
) -> List[tuple]:
    changes = []

    if add_tags:
        for tag in add_tags:
            if tag not in paper.tags:
                old = list(paper.tags)
                paper.tags.append(tag)
                changes.append(("tags", old, list(paper.tags)))

    if remove_tags:
        old = list(paper.tags)
        new_tags = [t for t in paper.tags if t not in remove_tags]
        if len(new_tags) != len(old):
            paper.tags = new_tags
            changes.append(("tags", old, list(paper.tags)))

    if set_status and paper.read_status != set_status:
        old = paper.read_status
        paper.read_status = set_status
        changes.append(("read_status", old, set_status))

    if set_doi is not None and paper.doi != set_doi:
        old = paper.doi
        paper.doi = set_doi
        changes.append(("doi", old, set_doi))

    if set_journal is not None and paper.journal != set_journal:
        old = paper.journal
        paper.journal = set_journal
        changes.append(("journal", old, set_journal))

    if add_keywords:
        for kw in add_keywords:
            if kw not in paper.keywords:
                old = list(paper.keywords)
                paper.keywords.append(kw)
                changes.append(("keywords", old, list(paper.keywords)))

    if add_topic and add_topic not in paper.topics:
        old = list(paper.topics)
        paper.topics.append(add_topic)
        changes.append(("topics", old, list(paper.topics)))

    return changes


def _build_filter_desc(
    filter_tag: Optional[str],
    filter_topic: Optional[str],
    filter_status: Optional[str],
    file_filter: Optional[str],
) -> str:
    parts = []
    if filter_tag:
        parts.append(f"tag={filter_tag}")
    if filter_topic:
        parts.append(f"topic={filter_topic}")
    if filter_status:
        parts.append(f"status={filter_status}")
    if file_filter:
        parts.append(f"keyword={file_filter}")
    return ", ".join(parts) if parts else "无筛选"


def _filter_papers(
    db: PaperDatabase,
    filter_tag: Optional[str] = None,
    filter_topic: Optional[str] = None,
    filter_status: Optional[str] = None,
    file_filter: Optional[str] = None,
) -> List[Paper]:
    papers = db.all_papers()

    if filter_tag:
        papers = [p for p in papers if filter_tag in p.tags]

    if filter_topic:
        papers = [p for p in papers if filter_topic in p.topics]

    if filter_status:
        papers = [p for p in papers if p.read_status == filter_status]

    if file_filter:
        filter_lower = file_filter.lower()
        papers = [
            p for p in papers
            if filter_lower in p.file_name.lower()
            or (p.title and filter_lower in p.title.lower())
        ]

    return papers


def _move_paper_to_topic(
    paper: Paper,
    topic: str,
    base_dir: Path,
    op_log: OperationLog,
    dry_run: bool,
) -> bool:
    old_path = Path(paper.file_path)
    topic_dir = base_dir / sanitize_filename(topic)
    new_path = topic_dir / old_path.name

    if str(old_path.resolve()) == str(new_path.resolve()):
        return False

    if not dry_run:
        topic_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        op_log.log_file_move(str(old_path), str(new_path), file_name=old_path.name)
        paper.file_path = str(new_path.resolve())
        paper.file_name = new_path.name

    return True
