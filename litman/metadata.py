from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from .models import Paper, parse_filename


def extract_pdf_metadata(file_path: str) -> Dict[str, Any]:
    result = {
        "title": None,
        "authors": [],
        "year": None,
        "doi": None,
        "subject": None,
        "keywords": [],
    }

    if PdfReader is None:
        return result

    try:
        reader = PdfReader(file_path)
    except Exception:
        return result

    if reader.metadata:
        meta = reader.metadata
        title = getattr(meta, "title", None)
        if title:
            result["title"] = str(title).strip()
        author = getattr(meta, "author", None)
        if author:
            authors_str = str(author)
            result["authors"] = _parse_authors(authors_str)
        subject = getattr(meta, "subject", None)
        if subject:
            result["subject"] = str(subject).strip()
        keywords = getattr(meta, "keywords", None)
        if keywords:
            keywords_str = str(keywords)
            result["keywords"] = _parse_keywords(keywords_str)

    first_page_text = ""
    try:
        if len(reader.pages) > 0:
            first_page_text = reader.pages[0].extract_text() or ""
    except Exception:
        pass

    if first_page_text:
        first_page_meta = _extract_from_first_page(first_page_text)
        for key, value in first_page_meta.items():
            if not result.get(key) and value:
                result[key] = value

    return result


def _parse_authors(authors_str: str) -> List[str]:
    if not authors_str:
        return []
    separators = [" and ", ";", ",", "&"]
    authors = [authors_str]
    for sep in separators:
        new_authors = []
        for a in authors:
            new_authors.extend(a.split(sep))
        authors = new_authors
    return [a.strip() for a in authors if a.strip()]


def _parse_keywords(keywords_str: str) -> List[str]:
    if not keywords_str:
        return []
    separators = [";", ",", " and "]
    keywords = [keywords_str]
    for sep in separators:
        new_keywords = []
        for kw in keywords:
            new_keywords.extend(kw.split(sep))
        keywords = new_keywords
    return [kw.strip() for kw in keywords if kw.strip()]


def _extract_from_first_page(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    if len(lines) >= 2:
        potential_title = lines[0]
        if 5 < len(potential_title) < 200:
            result["title"] = potential_title

    doi_match = re.search(
        r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b",
        text,
        re.IGNORECASE,
    )
    if doi_match:
        result["doi"] = doi_match.group(1).rstrip(".,;")

    year_match = re.search(r"\b(19|20)\d{2}\b", text[:500])
    if year_match:
        result["year"] = int(year_match.group())

    keywords_match = re.search(
        r"(?:Keywords|Key words|关键词)[:：]\s*(.+?)(?:\n\n|\n[A-Z][a-z]+[:：]|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if keywords_match:
        kw_text = keywords_match.group(1).strip()
        result["keywords"] = _parse_keywords(kw_text)

    return result


def enrich_paper(paper: Paper, use_filename: bool = True) -> Paper:
    if paper.file_path.endswith(".pdf"):
        meta = extract_pdf_metadata(paper.file_path)
        if meta["title"]:
            paper.title = meta["title"]
        if meta["authors"]:
            paper.authors = meta["authors"]
        if meta["year"]:
            paper.year = meta["year"]
        if meta["doi"]:
            paper.doi = meta["doi"]
        if meta["keywords"]:
            paper.keywords = meta["keywords"]
        if meta["subject"]:
            paper.journal = meta["subject"]

    if use_filename:
        parsed = parse_filename(paper.file_name)
        if not paper.title and parsed["title"]:
            paper.title = parsed["title"]
        if not paper.authors and parsed["authors"]:
            paper.authors = parsed["authors"]
        if not paper.year and parsed["year"]:
            paper.year = parsed["year"]

    paper.touch()
    return paper


def verify_pdf_integrity(file_path: str) -> Tuple[bool, str]:
    path = Path(file_path)
    if not path.exists():
        return False, "文件不存在"
    if path.stat().st_size == 0:
        return False, "文件为空"

    if not file_path.lower().endswith(".pdf"):
        return True, "非 PDF 文件，跳过内容验证"

    if PdfReader is None:
        return True, "pypdf 未安装，无法验证 PDF 内容"

    try:
        reader = PdfReader(file_path)
        if len(reader.pages) == 0:
            return False, "PDF 无有效页面"
        _ = reader.pages[0]
        return True, f"PDF 有效，共 {len(reader.pages)} 页"
    except Exception as e:
        return False, f"PDF 损坏或无法读取: {str(e)}"


def scan_pdfs(directory: str, recursive: bool = True) -> List[str]:
    dir_path = Path(directory)
    if not dir_path.exists():
        return []

    pdf_files = []
    pattern = "**/*.pdf" if recursive else "*.pdf"
    for pdf_file in dir_path.glob(pattern):
        if pdf_file.is_file():
            pdf_files.append(str(pdf_file.resolve()))
    return sorted(pdf_files)
