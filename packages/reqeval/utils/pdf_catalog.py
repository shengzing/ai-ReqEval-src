from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def iter_pdf_files(root_dir: str | Path, *, recursive: bool = True) -> Iterable[Path]:
    root = Path(root_dir)
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix.lower() == ".pdf" else []
    if recursive:
        return (p for p in root.rglob("*.pdf") if p.is_file())
    return (p for p in root.glob("*.pdf") if p.is_file())


def _looks_like_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def normalize_source_file_to_abs(source_file: object, *, repo_root: Path) -> Path | None:
    """
    Convert a JSON `source_file` value to an absolute Path.

    - None/empty/URL -> None
    - relative path -> resolved under repo_root
    - absolute path -> resolved as-is
    """
    if source_file is None:
        return None
    if not isinstance(source_file, str):
        return None
    s = source_file.strip()
    if not s or _looks_like_url(s):
        return None

    # Handle Windows-style slashes in stored JSON.
    s = s.replace("\\", "/")
    p = Path(s)
    try:
        if p.is_absolute():
            return p.resolve()
        return (repo_root / p).resolve()
    except Exception:
        return None


@dataclass(frozen=True)
class PdfCatalogRow:
    file_name: str
    path: str
    analysis_count: int = 0


def build_pdf_catalog(
    pdf_root: str | Path,
    *,
    recursive: bool,
    repo_root: Path,
) -> list[PdfCatalogRow]:
    rows: list[PdfCatalogRow] = []
    for p in iter_pdf_files(pdf_root, recursive=recursive):
        try:
            rel = p.resolve().relative_to(repo_root.resolve())
            rel_str = rel.as_posix()
        except Exception:
            rel_str = str(p)
        rows.append(PdfCatalogRow(file_name=p.name, path=rel_str, analysis_count=0))
    rows.sort(key=lambda r: (r.path.lower(), r.file_name.lower()))
    return rows


def count_source_files(source_files: Iterable[object], *, repo_root: Path) -> Counter[str]:
    """
    Count how many times each `source_file` (normalized absolute path) appears.
    """
    c: Counter[str] = Counter()
    for sf in source_files:
        p = normalize_source_file_to_abs(sf, repo_root=repo_root)
        if p is None:
            continue
        c[str(p)] += 1
    return c


def apply_counts_to_catalog(
    catalog: list[PdfCatalogRow],
    *,
    source_file_counts: Counter[str],
    repo_root: Path,
) -> list[PdfCatalogRow]:
    """
    Return a new catalog with analysis_count filled from `source_file_counts`.
    """
    out: list[PdfCatalogRow] = []
    for row in catalog:
        abs_p = normalize_source_file_to_abs(row.path, repo_root=repo_root)
        count = source_file_counts.get(str(abs_p), 0) if abs_p is not None else 0
        out.append(PdfCatalogRow(file_name=row.file_name, path=row.path, analysis_count=int(count)))
    return out

