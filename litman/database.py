from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable

from .models import Paper


DEFAULT_DB_FILENAME = ".litman_index.json"
DEFAULT_DB_DIRNAME = ".litman"


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
            self.papers = {
                k: Paper.from_dict(v) for k, v in data.get("papers", {}).items()
            }
        except (json.JSONDecodeError, IOError):
            self.papers = {}

        self._loaded = True

    def save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "papers": {k: v.to_dict() for k, v in self.papers.items()},
        }
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_paper(self, paper: Paper) -> None:
        self.load()
        self.papers[paper.file_hash] = paper

    def remove_paper(self, file_hash: str) -> Optional[Paper]:
        self.load()
        return self.papers.pop(file_hash, None)

    def get_paper(self, file_hash: str) -> Optional[Paper]:
        self.load()
        return self.papers.get(file_hash)

    def find_by_path(self, file_path: str) -> Optional[Paper]:
        self.load()
        resolved = str(Path(file_path).resolve())
        for paper in self.papers.values():
            if str(Path(paper.file_path).resolve()) == resolved:
                return paper
        return None

    def find_by_doi(self, doi: str) -> List[Paper]:
        self.load()
        if not doi:
            return []
        return [p for p in self.papers.values() if p.doi and p.doi.lower() == doi.lower()]

    def find_by_title(self, title: str) -> List[Paper]:
        self.load()
        if not title:
            return []
        title_lower = title.lower()
        return [p for p in self.papers.values() if p.title and p.title.lower() == title_lower]

    def find_by_tag(self, tag: str) -> List[Paper]:
        self.load()
        return [p for p in self.papers.values() if tag in p.tags]

    def find_by_topic(self, topic: str) -> List[Paper]:
        self.load()
        return [p for p in self.papers.values() if topic in p.topics]

    def find_duplicates(self) -> List[List[Paper]]:
        self.load()
        hash_groups: Dict[str, List[Paper]] = {}
        doi_groups: Dict[str, List[Paper]] = {}
        title_groups: Dict[str, List[Paper]] = {}

        for paper in self.papers.values():
            if paper.file_hash not in hash_groups:
                hash_groups[paper.file_hash] = []
            hash_groups[paper.file_hash].append(paper)

            if paper.doi:
                doi_key = paper.doi.lower()
                if doi_key not in doi_groups:
                    doi_groups[doi_key] = []
                doi_groups[doi_key].append(paper)

            if paper.title:
                title_key = paper.title.lower().strip()
                if title_key not in title_groups:
                    title_groups[title_key] = []
                title_groups[title_key].append(paper)

        duplicates = []
        seen_pairs = set()

        for group in hash_groups.values():
            if len(group) > 1:
                dup_set = frozenset(p.file_hash for p in group)
                if dup_set not in seen_pairs:
                    seen_pairs.add(dup_set)
                    duplicates.append(group)

        for group in doi_groups.values():
            if len(group) > 1:
                dup_set = frozenset(p.file_hash for p in group)
                if dup_set not in seen_pairs:
                    seen_pairs.add(dup_set)
                    duplicates.append(group)

        for group in title_groups.values():
            if len(group) > 1:
                dup_set = frozenset(p.file_hash for p in group)
                if dup_set not in seen_pairs:
                    seen_pairs.add(dup_set)
                    duplicates.append(group)

        return duplicates

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

    def get_missing_metadata(self, fields: Optional[List[str]] = None) -> List[Paper]:
        self.load()
        if fields is None:
            fields = ["title", "authors", "year", "doi", "journal", "keywords"]

        missing = []
        for paper in self.papers.values():
            is_missing = False
            for field in fields:
                value = getattr(paper, field, None)
                if value is None or value == "" or value == []:
                    is_missing = True
                    break
            if is_missing:
                missing.append(paper)
        return missing

    def update_paper_path(self, old_path: str, new_path: str) -> Optional[Paper]:
        paper = self.find_by_path(old_path)
        if paper is None:
            return None
        paper.file_path = str(Path(new_path).resolve())
        paper.file_name = Path(new_path).name
        paper.touch()
        return paper

    def update_paper(self, paper: Paper) -> None:
        self.load()
        paper.touch()
        self.papers[paper.file_hash] = paper
