"""Default seed keyword data for the risk vocabulary.

Maps the existing RISK_L3_KEYWORDS and RISK_L2_KEYWORDS into
RiskTerm format with initial synonyms and hierarchical relationships.
"""

from __future__ import annotations

from src.apps.api.app.agents.risk_semantic.models import RiskTerm

DEFAULT_SEED_KEYWORDS: list[RiskTerm] = [
    # ── L3 keywords (15 canonical terms) ──────────────────────────────────
    RiskTerm(
        canonical="风险等级调整",
        level="L3",
        category="compliance",
        synonyms=["风险等级变更", "风险级别调整", "风险等级修改"],
        children=[],
    ),
    RiskTerm(
        canonical="客户处置",
        level="L3",
        category="customer",
        synonyms=["客户处理", "客户处置流程", "客户账户处置"],
        children=["冻结账户", "客户销户", "账户限制"],
    ),
    RiskTerm(
        canonical="监管敏感",
        level="L3",
        category="compliance",
        synonyms=["监管关注", "监管风险", "敏感监管事项"],
        children=[],
    ),
    RiskTerm(
        canonical="审计追责",
        level="L3",
        category="compliance",
        synonyms=["审计问责", "审计责任追究", "追责审计"],
        children=[],
    ),
    RiskTerm(
        canonical="漏报风险",
        level="L3",
        category="compliance",
        synonyms=["遗漏上报", "未上报", "漏报事项", "应报未报"],
        children=[],
    ),
    RiskTerm(
        canonical="未脱敏",
        level="L3",
        category="data",
        synonyms=["未脱敏数据", "数据未脱敏", "脱敏缺失", "未做脱敏"],
        children=[],
    ),
    RiskTerm(
        canonical="客户经营数据",
        level="L3",
        category="data",
        synonyms=["客户经营信息", "客户经营资料", "经营数据"],
        children=[],
    ),
    RiskTerm(
        canonical="合规复核",
        level="L3",
        category="compliance",
        synonyms=["合规审查", "合规复检", "合规审核"],
        children=[],
    ),
    RiskTerm(
        canonical="适当性管理",
        level="L3",
        category="customer",
        synonyms=["适当性评估", "投资者适当性", "适当性匹配"],
        children=[],
    ),
    RiskTerm(
        canonical="投资建议",
        level="L3",
        category="customer",
        synonyms=["投资咨询", "投资推荐", "投资指导", "投资意见"],
        children=[],
    ),
    RiskTerm(
        canonical="误导性收益",
        level="L3",
        category="customer",
        synonyms=["虚假收益", "收益误导", "夸大收益", "收益承诺"],
        children=[],
    ),
    RiskTerm(
        canonical="对客内容",
        level="L3",
        category="customer",
        synonyms=["面向客户内容", "客户可见内容", "对客披露"],
        children=[],
    ),
    RiskTerm(
        canonical="算法歧视",
        level="L3",
        category="model",
        synonyms=["算法偏见", "模型歧视", "算法不公平", "模型偏见"],
        children=[],
    ),
    RiskTerm(
        canonical="模型漂移",
        level="L3",
        category="model",
        synonyms=["模型退化", "概念漂移", "数据漂移", "模型偏移"],
        children=[],
    ),
    RiskTerm(
        canonical="数据跨境",
        level="L3",
        category="data",
        synonyms=["跨境数据传输", "数据出境", "跨境数据流"],
        children=[],
    ),
    # ── L2 keywords (8 canonical terms) ───────────────────────────────────
    RiskTerm(
        canonical="人工确认",
        level="L2",
        category="operational",
        synonyms=["人工审核", "人工复核", "人工审查", "人工校验"],
        children=[],
    ),
    RiskTerm(
        canonical="审计留痕",
        level="L2",
        category="compliance",
        synonyms=["审计痕迹", "审计记录", "操作留痕"],
        children=[],
    ),
    RiskTerm(
        canonical="责任人",
        level="L2",
        category="compliance",
        synonyms=["责任人员", "责任主体", "负责人员"],
        children=[],
    ),
    RiskTerm(
        canonical="对外发送",
        level="L2",
        category="data",
        synonyms=["外部传输", "对外传输", "数据外发", "外部发送"],
        children=[],
    ),
    RiskTerm(
        canonical="复核",
        level="L2",
        category="operational",
        synonyms=["复查", "二次确认", "复检"],
        children=[],
    ),
    RiskTerm(
        canonical="数据隐私",
        level="L2",
        category="data",
        synonyms=["隐私保护", "个人隐私", "数据私密性", "隐私数据"],
        children=[],
    ),
    RiskTerm(
        canonical="业务连续性",
        level="L2",
        category="operational",
        synonyms=["业务持续", "连续性保障", "业务中断风险"],
        children=[],
    ),
    RiskTerm(
        canonical="模型可解释性",
        level="L2",
        category="model",
        synonyms=["模型解释", "可解释AI", "模型透明度", "模型可理解性"],
        children=[],
    ),
]
