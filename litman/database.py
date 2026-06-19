from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable

from .models import Paper


DEFAULT_DB_FILENAME = ".litman_index.json"
DEFAULT_DB_DIRNAME = ".litman"


def _path_key(file_path: str) -> str:
    return str(Path(file_path).resolve())


class PaperDatabase:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.papers: Dict[str, Paper] = {}
        self._loaded = False

    @classmethod
    def for_directory(cls, directory: str) -> "PaperDatabase":
        dir_path = Path(directory).resolve()
        db_dir = dir_path / DEFAULT_DB_DIRNAME
        db_path = db_dir / DEFAULT_DB_FILENAME
        return cls(str(db_path))

    def load(self) -> None:
        if self._loaded:
            return

        if not self.db_path.exists():
            self.papers = {}
            self._loaded = True
            return

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("version", "1.0")
            papers_data = data.get("papers", {})

            if version == "1.0":
                self.papers = {}
                for k, v in papers_data.items():
                    paper = Paper.from_dict(v)
                    key = _path_key(paper.file_path)
                    self.papers[key] = paper
            else:
                self.papers = {k: Paper.from_dict(v) for k, v in papers_data.items()}

        except (json.JSONDecodeError, IOError):
            self.papers = {}

        self._loaded = True

    def save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "2.0",
            "papers": {k: v.to_dict() for k, v in self.papers.items()},
        }
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def snapshot(self) -> Dict[str, dict]:
        self.load()
        return {k: v.to_dict() for k, v in self.papers.items()}

    def restore_snapshot(self, snap: Dict[str, dict]) -> None:
        self.papers = {k: Paper.from_dict(v) for k, v in snap.items()}
        self._loaded = True

    def add_paper(self, paper: Paper) -> None:
        self.load()
        key = _path_key(paper.file_path)
        self.papers[key] = paper

    def remove_paper(self, file_path: str) -> Optional[Paper]:
        self.load()
        key = _path_key(file_path)
        return self.papers.pop(key, None)

    def get_paper(self, file_path: str) -> Optional[Paper]:
        self.load()
        key = _path_key(file_path)
        return self.papers.get(key)

    def find_by_path(self, file_path: str) -> Optional[Paper]:
        return self.get_paper(file_path)

    def find_by_hash(self, file_hash: str) -> List[Paper]:
        self.load()
        return [p for p in self.papers.values() if p.file_hash == file_hash]

    def find_by_doi(self, doi: str) -> List[Paper]:
        self.load()
        if not doi:
            return []
        doi_lower = doi.lower()
        return [p for p in self.papers.values() if p.doi and p.doi.lower() == doi_lower]

    def find_by_title(self, title: str) -> List[Paper]:
        self.load()
        if not title:
            return []
        title_lower = title.lower().strip()
        return [p for p in self.papers.values() if p.title and p.title.lower().strip() == title_lower]

    def find_by_tag(self, tag: str) -> List[Paper]:
        self.load()
        return [p for p in self.papers.values() if tag in p.tags]

    def find_by_topic(self, topic: str) -> List[Paper]:
        self.load()
        return [p for p in self.papers.values() if topic in p.topics]

    def find_duplicates(self) -> List[Dict[str, Any]]:
        from typing import Any
        self.load()

        hash_groups: Dict[str, List[Paper]] = {}
        doi_groups: Dict[str, List[Paper]] = {}
        title_groups: Dict[str, List[Paper]] = {}

        for paper in self.papers.values():
            h = paper.file_hash
            if h not in hash_groups:
                hash_groups[h] = []
            hash_groups[h].append(paper)

            if paper.doi:
                dk = paper.doi.lower()
                if dk not in doi_groups:
                    doi_groups[dk] = []
                doi_groups[dk].append(paper)

            if paper.title:
                tk = paper.title.lower().strip()
                if tk not in title_groups:
                    title_groups[tk] = []
                title_groups[tk].append(paper)

        result_groups: List[Dict[str, Any]] = []
        seen_member_sets: Dict[frozenset, int] = {}

        for group in hash_groups.values():
            if len(group) >= 2:
                member_set = frozenset(_path_key(p.file_path) for p in group)
                if member_set not in seen_member_sets:
                    seen_member_sets[member_set] = len(result_groups)
                    result_groups.append({
                        "reason": "内容完全相同",
                        "papers": group,
                    })

        for group in doi_groups.values():
            if len(group) >= 2:
                member_set = frozenset(_path_key(p.file_path) for p in group)
                if member_set not in seen_member_sets:
                    seen_member_sets[member_set] = len(result_groups)
                    result_groups.append({
                        "reason": "DOI 相同",
                        "papers": group,
                    })
                else:
                    idx = seen_member_sets[member_set]
                    existing_reasons = result_groups[idx]["reason"]
                    if "DOI 相同" not in existing_reasons:
                        result_groups[idx]["reason"] = f"{existing_reasons}; DOI 相同"

        for group in title_groups.values():
            if len(group) >= 2:
                member_set = frozenset(_path_key(p.file_path) for p in group)
                if member_set not in seen_member_sets:
                    seen_member_sets[member_set] = len(result_groups)
                    result_groups.append({
                        "reason": "标题相同",
                        "papers": group,
                    })
                else:
                    idx = seen_member_sets[member_set]
                    existing_reasons = result_groups[idx]["reason"]
                    if "标题相同" not in existing_reasons:
                        result_groups[idx]["reason"] = f"{existing_reasons}; 标题相同"

        return result_groups

    def all_papers(self) -> List[Paper]:
        self.load()
        return list(self.papers.values())

    def count(self) -> int:
        self.load()
        return len(self.papers)

    def get_all_tags(self) -> List[str]:
        self.load()
        tags = set()
        for paper in self.papers.values():
            tags.update(paper.tags)
        return sorted(tags)

    def get_all_topics(self) -> List[str]:
        self.load()
        topics = set()
        for paper in self.papers.values():
            topics.update(paper.topics)
        return sorted(topics)

    def get_missing_metadata(self, fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        self.load()
        if fields is None:
            fields = ["title", "authors", "year", "doi", "journal", "keywords"]

        missing = []
        for paper in self.papers.values():
            miss_fields = []
            for field in fields:
                value = getattr(paper, field, None)
                if value is None or value == "" or value == []:
                    miss_fields.append(field)
            if miss_fields:
                missing.append({"paper": paper, "missing_fields": miss_fields})
        return missing

    def update_paper_path(self, old_path: str, new_path: str) -> Optional[Paper]:
        self.load()
        old_key = _path_key(old_path)
        paper = self.papers.pop(old_key, None)
        if paper is None:
            return None
        paper.file_path = str(Path(new_path).resolve())
        paper.file_name = Path(new_path).name
        paper.touch()
        new_key = _path_key(new_path)
        self.papers[new_key] = paper
        return paper

    def update_paper(self, paper: Paper) -> None:
        self.load()
        paper.touch()
        key = _path_key(paper.file_path)
        self.papers[key] = paper
