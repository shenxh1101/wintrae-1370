from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


READ_STATUS_UNREAD = "unread"
READ_STATUS_READING = "reading"
READ_STATUS_READ = "read"
READ_STATUSES = [READ_STATUS_UNREAD, READ_STATUS_READING, READ_STATUS_READ]


@dataclass
class Paper:
    file_path: str
    file_name: str
    file_size: int
    file_hash: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    read_status: str = READ_STATUS_UNREAD
    topics: List[str] = field(default_factory=list)
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""
    rating: Optional[int] = None
    due_date: Optional[str] = None

    @classmethod
    def from_file(cls, file_path: str) -> "Paper":
        path = Path(file_path)
        stat = path.stat()
        file_hash = compute_file_hash(file_path)
        return cls(
            file_path=str(path.resolve()),
            file_name=path.name,
            file_size=stat.st_size,
            file_hash=file_hash,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Paper":
        return cls(**data)

    def generate_filename(self, pattern: str = "{year}_{first_author}_{title}") -> str:
        first_author = self.authors[0] if self.authors else "Unknown"
        last_name = first_author.split()[-1] if first_author else "Unknown"
        year = str(self.year) if self.year else "n.d."
        title = self.title or "Untitled"
        short_title = sanitize_filename(title[:80])

        filename = pattern.format(
            year=year,
            author=last_name,
            first_author=last_name,
            title=short_title,
            doi=self.doi or "nodoi",
        )
        return f"{sanitize_filename(filename)}.pdf"

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()


def sanitize_filename(name: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    name = name.strip().strip(".")
    name = " ".join(name.split())
    return name or "untitled"


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def parse_filename(filename: str) -> Dict[str, Any]:
    name = Path(filename).stem
    result = {"title": None, "authors": [], "year": None}

    year_match = None
    import re
    year_patterns = [
        r"\b(19|20)\d{2}\b",
        r"_(19|20)\d{2}_",
        r"^(19|20)\d{2}_",
    ]
    for pattern in year_patterns:
        match = re.search(pattern, name)
        if match:
            year_match = match
            break

    if year_match:
        year_str = re.search(r"\d{4}", year_match.group()).group()
        result["year"] = int(year_str)
        name = name[:year_match.start()] + name[year_match.end():]

    parts = re.split(r"[_-]+", name.strip("_- "))
    parts = [p for p in parts if p]

    if len(parts) >= 2 and result["year"]:
        result["authors"] = [parts[0]]
        result["title"] = " ".join(parts[1:])
    elif parts:
        result["title"] = " ".join(parts)

    return result
