"""Dynamic risk vocabulary with synonym expansion and hierarchical reasoning.

The RiskVocabulary class replaces direct keyword iteration in
risk_identify_tool with a richer lookup that supports synonyms
and parent-child term hierarchies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import KeywordMatch, RiskTerm
from src.apps.api.app.agents.risk_semantic.vocabulary_data import DEFAULT_SEED_KEYWORDS


class RiskVocabulary:
    """Risk vocabulary with synonym expansion and hierarchical reasoning.

    Seeds from DEFAULT_SEED_KEYWORDS by default. Custom vocabularies can be
    loaded from a JSON file.

    Usage::

        vocab = RiskVocabulary()
        matches = vocab.lookup("涉及冻结账户和审计追责事项")
        for m in matches:
            print(m.term, m.level, m.is_hierarchical)
    """

    def __init__(self, terms: list[RiskTerm] | None = None) -> None:
        self._terms: dict[str, RiskTerm] = {}
        # Reverse index: synonym/child → canonical
        self._synonym_index: dict[str, str] = {}
        self._child_index: dict[str, str] = {}

        seed = terms if terms is not None else list(DEFAULT_SEED_KEYWORDS)
        for term in seed:
            self.add(term)

    # ── Public API ────────────────────────────────────────────────────────

    def add(self, term: RiskTerm) -> None:
        """Add a risk term to the vocabulary."""
        self._terms[term.canonical] = term
        # Index synonyms
        for syn in term.synonyms:
            self._synonym_index[syn] = term.canonical
        # Index children
        for child in term.children:
            self._child_index[child] = term.canonical

    def remove(self, canonical: str) -> None:
        """Remove a risk term from the vocabulary."""
        term = self._terms.pop(canonical, None)
        if term is None:
            return
        for syn in term.synonyms:
            self._synonym_index.pop(syn, None)
        for child in term.children:
            self._child_index.pop(child, None)

    def lookup(self, text: str, *, expand: bool = False) -> list[KeywordMatch]:
        """Scan *text* for all vocabulary matches.

        When *expand* is False (default), only canonical terms are matched,
        which preserves backward compatibility with the original keyword lists.

        When *expand* is True, synonyms and hierarchical children are also
        scanned, producing additional matches beyond the canonical terms.

        Returns matches sorted by level (L3 first), then by position in text.
        Each match records whether it was found as a canonical term, a synonym,
        or a hierarchical child.
        """
        matches: list[KeywordMatch] = []
        seen_terms: set[str] = set()

        # 1. Scan for canonical terms (always)
        for canonical, term in self._terms.items():
            if canonical in text:
                if canonical not in seen_terms:
                    seen_terms.add(canonical)
                    matches.append(KeywordMatch(
                        term=canonical,
                        matched_synonym=None,
                        matched_child=None,
                        level=term.level,
                        category=term.category,
                        is_synonym=False,
                        is_hierarchical=False,
                    ))

        if not expand:
            # Without expansion, return only canonical matches
            level_order = {"L3": 0, "L2": 1}
            matches.sort(key=lambda m: level_order.get(m.level, 99))
            return matches

        # 2. Scan for synonyms (only when expand=True)
        for synonym, canonical in self._synonym_index.items():
            if synonym in text and canonical not in seen_terms:
                term = self._terms.get(canonical)
                if term is None:
                    continue
                seen_terms.add(canonical)
                matches.append(KeywordMatch(
                    term=canonical,
                    matched_synonym=synonym,
                    matched_child=None,
                    level=term.level,
                    category=term.category,
                    is_synonym=True,
                    is_hierarchical=False,
                ))

        # 3. Scan for children (hierarchical matches, only when expand=True)
        for child, canonical in self._child_index.items():
            if child in text and canonical not in seen_terms:
                term = self._terms.get(canonical)
                if term is None:
                    continue
                seen_terms.add(canonical)
                matches.append(KeywordMatch(
                    term=canonical,
                    matched_synonym=None,
                    matched_child=child,
                    level=term.level,
                    category=term.category,
                    is_synonym=False,
                    is_hierarchical=True,
                ))

        # Sort: L3 first, then L2
        level_order = {"L3": 0, "L2": 1}
        matches.sort(key=lambda m: level_order.get(m.level, 99))
        return matches

    def get_term(self, canonical: str) -> RiskTerm | None:
        """Retrieve a term by its canonical name."""
        return self._terms.get(canonical)

    @property
    def all_terms(self) -> list[RiskTerm]:
        """Return all terms in the vocabulary."""
        return list(self._terms.values())

    @property
    def l3_keywords(self) -> list[str]:
        """Return L3 canonical keywords (for backward compatibility)."""
        return [t.canonical for t in self._terms.values() if t.level == "L3"]

    @property
    def l2_keywords(self) -> list[str]:
        """Return L2 canonical keywords (for backward compatibility)."""
        return [t.canonical for t in self._terms.values() if t.level == "L2"]

    def all_lookup_strings(self) -> list[str]:
        """Return all strings that the vocabulary can match (canonical + synonyms + children).

        Useful for ensuring backward-compatible coverage with the original
        keyword lists.
        """
        strings: list[str] = []
        for term in self._terms.values():
            strings.append(term.canonical)
            strings.extend(term.synonyms)
            strings.extend(term.children)
        return strings

    # ── Serialization ──────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, path: str | Path) -> RiskVocabulary:
        """Load a custom vocabulary from a JSON file.

        The JSON file should contain a list of term dicts, each with keys:
        canonical, level, category, synonyms, children, parent.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        terms = []
        for item in data:
            terms.append(RiskTerm(
                canonical=item["canonical"],
                level=item["level"],
                category=item["category"],
                synonyms=item.get("synonyms", []),
                children=item.get("children", []),
                parent=item.get("parent"),
            ))
        return cls(terms=terms)

    def to_json(self, path: str | Path) -> None:
        """Serialize the vocabulary to a JSON file."""
        data = []
        for term in self._terms.values():
            data.append({
                "canonical": term.canonical,
                "level": term.level,
                "category": term.category,
                "synonyms": term.synonyms,
                "children": term.children,
                "parent": term.parent,
            })
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
