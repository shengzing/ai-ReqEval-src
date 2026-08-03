"""
指标与模型说明加载器

从 DOCS/指标.md 与 DOCS/model.md 提取章节内容，结构化为 dict。
解析逻辑：基于 Markdown 三级标题 `### 1.`、`### 2.` 等进行分段。
"""
from pathlib import Path
import re
from typing import Dict, List, Optional


class MetricsLoader:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).resolve().parents[2] / "DOCS"

    def _parse_markdown_sections(self, content: str) -> Dict[str, str]:
        """
        按照 '### <number>. <title>' 分段提取章节内容。
        """
        sections: Dict[str, str] = {}
        pattern = re.compile(r"^###\s+\d+\.\s*(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(content))
        for idx, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            sections[title] = content[start:end].strip()
        return sections

    def load_indicators(self) -> Dict[str, str]:
        """
        读取 DOCS/指标.md，返回 {标题: 内容}。
        """
        path = self.base_dir / "指标.md"
        if not path.exists():
            return {}
        content = path.read_text(encoding="utf-8")
        return self._parse_markdown_sections(content)

    def load_models(self) -> Dict[str, str]:
        """
        读取 DOCS/model.md，返回 {标题: 内容}。
        """
        path = self.base_dir / "model.md"
        if not path.exists():
            return {}
        content = path.read_text(encoding="utf-8")
        return self._parse_markdown_sections(content)

    def load_all(self) -> Dict[str, Dict[str, str]]:
        """
        综合返回指标与模型说明。
        """
        return {
            "indicators": self.load_indicators(),
            "models": self.load_models(),
        }


__all__ = ["MetricsLoader"]
