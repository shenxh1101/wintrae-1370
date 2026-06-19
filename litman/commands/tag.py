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
        result["errors"].append("没有匹配的文献")
        return result

    log_dir = dir_path / ".litman" / "logs"
    op_log = OperationLog(str(log_dir))

    for paper in papers:
        updated = False
        paper_dict_before = paper.to_dict()

        if add_tags:
            for tag in add_tags:
                if tag not in paper.tags:
                    paper.tags.append(tag)
                    updated = True

        if remove_tags:
            original_len = len(paper.tags)
            paper.tags = [t for t in paper.tags if t not in remove_tags]
            if len(paper.tags) != original_len:
                updated = True

        if set_status and paper.read_status != set_status:
            paper.read_status = set_status
            updated = True

        if set_doi is not None and paper.doi != set_doi:
            paper.doi = set_doi
            updated = True

        if set_journal is not None and paper.journal != set_journal:
            paper.journal = set_journal
            updated = True

        if add_keywords:
            for kw in add_keywords:
                if kw not in paper.keywords:
                    paper.keywords.append(kw)
                    updated = True

        if add_topic and add_topic not in paper.topics:
            paper.topics.append(add_topic)
            updated = True

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
        op_log.commit(description=f"更新 {result['updated']} 个文献的标签/元数据")

    if not dry_run:
        db.save()

    return result


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
        op_log.log_file_move(str(old_path), str(new_path))
        paper.file_path = str(new_path.resolve())
        paper.file_name = new_path.name

    return True
