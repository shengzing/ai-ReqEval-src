"""Knowledge service package — 分层领域知识注入。"""

from src.apps.api.app.agents.knowledge.service import (
    KNOWLEDGE_ROOT_REL,
    LAYER_COMMON,
    LAYER_REGULATION,
    LAYER_SKELETON,
    SUPPORTED_LAYERS,
    KnowledgeBundle,
    KnowledgeItem,
    KnowledgeService,
    get_default_service,
    knowledge_root,
)

__all__ = [
    "KNOWLEDGE_ROOT_REL",
    "LAYER_COMMON",
    "LAYER_REGULATION",
    "LAYER_SKELETON",
    "SUPPORTED_LAYERS",
    "KnowledgeBundle",
    "KnowledgeItem",
    "KnowledgeService",
    "get_default_service",
    "knowledge_root",
]
