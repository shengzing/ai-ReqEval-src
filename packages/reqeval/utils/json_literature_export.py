"""
Utilities for aggregating many JSON files (possibly nested directories) into a
single tabular dataset and exporting to Excel.

This is intentionally generic: it unions all fields across JSON records and
supports flattening nested dicts with dot-notation keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


ListMode = Literal["smart", "json", "index"]


@dataclass(frozen=True)
class LoadSummary:
    ok_files: int
    bad_files: int
    columns: int
    bad_file_paths: list[str]


def iter_json_files(root_dir: str | Path, *, recursive: bool = True) -> Iterable[Path]:
    root = Path(root_dir)
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    if recursive:
        return (p for p in root.rglob("*.json") if p.is_file())
    return (p for p in root.glob("*.json") if p.is_file())


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _to_json_str(v: Any) -> str:
    # Keep Chinese readable in Excel.
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def flatten_json(
    obj: Any,
    *,
    sep: str = ".",
    list_mode: ListMode = "smart",
    _parent_key: str = "",
) -> dict[str, Any]:
    """
    Flatten nested dicts to a single-level dict.

    - dict: recurse with `sep` joined keys
    - list:
        - smart: join scalar lists with '; ', otherwise JSON-stringify
        - json: always JSON-stringify
        - index: expand as key[0], key[1]... (and recurse if element is dict)
    - scalar: keep as-is
    """
    out: dict[str, Any] = {}

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{_parent_key}{sep}{k}" if _parent_key else str(k)
            if isinstance(v, dict):
                out.update(flatten_json(v, sep=sep, list_mode=list_mode, _parent_key=key))
            elif isinstance(v, list):
                if list_mode == "index":
                    for i, item in enumerate(v):
                        ikey = f"{key}[{i}]"
                        if isinstance(item, dict):
                            out.update(flatten_json(item, sep=sep, list_mode=list_mode, _parent_key=ikey))
                        elif isinstance(item, list):
                            out[ikey] = _to_json_str(item)
                        else:
                            out[ikey] = item
                elif list_mode == "json":
                    out[key] = _to_json_str(v)
                else:  # smart
                    if all(_is_scalar(x) for x in v):
                        # Preserve original ordering.
                        out[key] = "; ".join("" if x is None else str(x) for x in v)
                    else:
                        out[key] = _to_json_str(v)
            else:
                out[key] = v
        return out

    # Non-dict JSON roots are uncommon, but still handle them.
    root_key = _parent_key or "__root__"
    if isinstance(obj, list):
        if list_mode == "json":
            out[root_key] = _to_json_str(obj)
        elif list_mode == "index":
            for i, item in enumerate(obj):
                out[f"{root_key}[{i}]"] = _to_json_str(item) if not _is_scalar(item) else item
        else:
            out[root_key] = "; ".join("" if x is None else str(x) for x in obj) if all(_is_scalar(x) for x in obj) else _to_json_str(obj)
    else:
        out[root_key] = obj
    return out


def load_json_records(
    root_dir: str | Path = "result",
    *,
    recursive: bool = True,
    ignore_filenames: set[str] | None = None,
    require_key: str | None = None,
    require_key_nonempty: bool = False,
    include_meta: bool = True,
    sep: str = ".",
    list_mode: ListMode = "smart",
) -> tuple[list[dict[str, Any]], list[str], LoadSummary]:
    """
    Read and flatten all JSON files under root_dir into a list of dict records.

    Returns (records, columns, summary). Bad/invalid JSON files are skipped and reported.
    """
    ignore_filenames = ignore_filenames or set()
    root = Path(root_dir)
    root_abs = root.resolve()

    records: list[dict[str, Any]] = []
    bad_paths: list[str] = []

    for p in iter_json_files(root, recursive=recursive):
        if p.name in ignore_filenames:
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            bad_paths.append(str(p))
            continue

        if require_key is not None:
            if not isinstance(data, dict) or require_key not in data:
                continue
            if require_key_nonempty and (data.get(require_key) is None or data.get(require_key) == ""):
                continue

        flat = flatten_json(data, sep=sep, list_mode=list_mode)
        if include_meta:
            try:
                rel = str(p.resolve().relative_to(root_abs))
            except Exception:
                rel = str(p)
            flat = {
                "__file__": rel,
                "__file_stem__": p.stem,
                **flat,
            }
        records.append(flat)

    # Deterministic column ordering: meta first, then the rest sorted.
    all_keys: set[str] = set()
    for r in records:
        all_keys.update(r.keys())
    meta = [k for k in ["__file__", "__file_stem__"] if k in all_keys]
    rest = sorted(k for k in all_keys if k not in set(meta))
    columns = meta + rest

    summary = LoadSummary(
        ok_files=len(records),
        bad_files=len(bad_paths),
        columns=len(columns),
        bad_file_paths=bad_paths,
    )
    return records, columns, summary


def records_to_dataframe(records: list[dict[str, Any]], columns: list[str] | None = None):
    """
    Optional helper for callers that prefer pandas.
    Kept as a soft-dependency to avoid hard failing when pandas isn't installed.
    """
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("pandas is required for records_to_dataframe()") from e

    df = pd.DataFrame.from_records(records, columns=columns)
    if not df.empty:
        df = df.where(pd.notnull(df), None)
    return df
