"""Knowledge service for layered domain knowledge injection.

分层领域知识注入服务。按【三层 + 一隔离】分层管理评估模型注入所需的银行业务领域知识：

- 常识层（common/）   ：参数化知识，不注入 prompt，仅在结果中声明 model_capability_tag
- 行规层（regulation/）：监管发文条款，RAG 引用，强制 chunk_id + 文号 + 条款号
- 标尺层（scenario_skeleton/）：通用组织骨架/监管频次硬约束，prompt 注入随 config_version_id 冻结
- 隔离层             ：该行架构/阈值/风险偏好，不预注入，由产出/校核环节引入

设计文档：DOCS/design/2026-08-13_领域知识分层注入设计.md
知识库物理位置：data/研究材料/00_领域知识/

判定准绳：
    通用性 + 可追溯原文版本 = 上下文（可注入）
    特定性 + 需该行确认 = 评估对象（不可预注入，由产出/校核环节引入）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# 知识层枚举：与 data/研究材料/00_领域知识/ 子目录一一对应
LAYER_COMMON = "common"
LAYER_REGULATION = "regulation"
LAYER_SKELETON = "scenario_skeleton"
SUPPORTED_LAYERS: tuple[str, ...] = (LAYER_COMMON, LAYER_REGULATION, LAYER_SKELETON)

# 各层默认注入机制（与设计文档 §3 一致）
LAYER_INJECTION_MECHANISM: dict[str, str] = {
    LAYER_COMMON: "parametric",  # 参数化知识，不注入 prompt
    LAYER_REGULATION: "rag",  # RAG 引用
    LAYER_SKELETON: "prompt",  # prompt 注入随 config_version_id 冻结
}

# 知识库根目录：相对仓库根的固定路径
KNOWLEDGE_ROOT_REL = "data/研究材料/00_领域知识"


def _repo_root() -> Path:
    """从本文件位置向上定位仓库根（src/apps/api/app/agents/knowledge/service.py）。

    文件路径深度：repo/src/apps/api/app/agents/knowledge/service.py
    parents[6] = repo root。
    """
    return Path(__file__).resolve().parents[6]


def knowledge_root() -> Path:
    """返回知识库根目录绝对路径。"""
    return _repo_root() / KNOWLEDGE_ROOT_REL


def _compute_content_hash(payload: dict[str, Any]) -> str:
    """计算知识条目内容哈希（稳定排序后 sha256，复用 contracts._payload_digest 模式）。"""
    serialized = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class KnowledgeItem:
    """单个知识条目的解析视图。"""

    source_id: str
    source_version: str
    content_hash: str
    layer: str
    injection_mechanism: str
    raw: dict[str, Any] = field(default_factory=dict)
    path: str = ""

    @classmethod
    def from_yaml(cls, path: Path, layer: str) -> "KnowledgeItem":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source_id = str(raw.get("source_id", path.stem))
        source_version = str(raw.get("source_version", "unknown"))
        # 落地时回填 content_hash：占位值（pending-compute / 空）触发重算
        stored_hash = raw.get("content_hash")
        if not stored_hash or str(stored_hash).startswith("pending"):
            content_hash = _compute_content_hash(raw)
        else:
            content_hash = str(stored_hash)
        return cls(
            source_id=source_id,
            source_version=source_version,
            content_hash=content_hash,
            layer=layer,
            injection_mechanism=LAYER_INJECTION_MECHANISM.get(layer, "parametric"),
            raw=raw,
            path=str(path.relative_to(_repo_root())),
        )

    def to_bundle_entry(self) -> dict[str, Any]:
        """转为 knowledge_bundle 中的单条目（含审计所需元数据）。"""
        return {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "layer": self.layer,
            "injection_mechanism": self.injection_mechanism,
            "path": self.path,
            "发布机构": self.raw.get("发布机构", ""),
            "文号": self.raw.get("文号", ""),
            "现行状态": self.raw.get("现行状态", ""),
            "检索日期": self.raw.get("检索日期", ""),
            "条款摘要": self.raw.get("条款摘要", ""),
            "评估对象边界": self.raw.get("评估对象边界", ""),
        }


@dataclass
class KnowledgeBundle:
    """按层聚合的知识包，用于注入 HarnessRequest.knowledge_context。"""

    stage_id: str
    flow_id: str
    layers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # 注入记录：写 HarnessResult.traces 的 knowledge_injection_record
    injection_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "flow_id": self.flow_id,
            "layers": self.layers,
            "injection_record": self.injection_record,
        }


class KnowledgeService:
    """只读 data/研究材料/00_领域知识/ 的受控读取层 + 注入层。

    职责边界：
    - 只读知识库目录，不另立知识库
    - 按 stage_id + flow_id + knowledge_layers 返回 knowledge_bundle
    - 不承载知识注入逻辑本身（由 skill/流程构造 HarnessRequest 时调用本服务注入）
    - content_hash 计算与 chunk 冻结快照由本服务提供，RAG 查询日志由调用方记录
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or knowledge_root()
        if not self.root.exists():
            logger.warning("[knowledge] 知识库根目录不存在: %s", self.root)

    def resolve(
        self,
        *,
        stage_id: str,
        flow_id: str = "",
        knowledge_layers: list[str] | None = None,
    ) -> KnowledgeBundle:
        """按层读取知识条目，返回 KnowledgeBundle。

        Args:
            stage_id: 阶段标识（如 stage-1）
            flow_id: 流程标识（如某 Agent 的 flow_id），可为空
            knowledge_layers: 需注入的层列表；None 表示读全部已支持层

        Returns:
            KnowledgeBundle，调用方据此构造 HarnessRequest.knowledge_context
        """
        layers_to_load = knowledge_layers or list(SUPPORTED_LAYERS)
        bundle = KnowledgeBundle(stage_id=stage_id, flow_id=flow_id)
        injected_source_ids: list[str] = []
        injected_paths: list[str] = []

        for layer in layers_to_load:
            if layer not in SUPPORTED_LAYERS:
                logger.warning("[knowledge] 不支持的层: %s，跳过", layer)
                continue
            layer_dir = self.root / layer
            if not layer_dir.exists():
                continue
            entries: list[dict[str, Any]] = []
            for yaml_path in sorted(layer_dir.glob("*.yaml")):
                item = KnowledgeItem.from_yaml(yaml_path, layer)
                entries.append(item.to_bundle_entry())
                injected_source_ids.append(item.source_id)
                injected_paths.append(item.path)
            bundle.layers[layer] = entries

        bundle.injection_record = {
            "source_ids": injected_source_ids,
            "paths": injected_paths,
            "layer_counts": {layer: len(items) for layer, items in bundle.layers.items()},
            "injection_point": f"stage={stage_id}/flow={flow_id or 'default'}",
        }
        logger.info(
            "[knowledge] resolve stage=%s flow=%s layers=%s counts=%s",
            stage_id,
            flow_id,
            layers_to_load,
            bundle.injection_record["layer_counts"],
        )
        return bundle

    def list_items(self, layer: str) -> list[KnowledgeItem]:
        """列出某层全部知识条目（调试/盘点用）。"""
        if layer not in SUPPORTED_LAYERS:
            return []
        layer_dir = self.root / layer
        if not layer_dir.exists():
            return []
        return [KnowledgeItem.from_yaml(p, layer) for p in sorted(layer_dir.glob("*.yaml"))]


_default_service: KnowledgeService | None = None


def get_default_service() -> KnowledgeService:
    """返回进程级默认 KnowledgeService 单例。"""
    global _default_service
    if _default_service is None:
        _default_service = KnowledgeService()
    return _default_service
