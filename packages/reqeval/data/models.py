"""
数据模型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class ScenarioType(str, Enum):
    """评估场景类型"""
    PRE = "pre"  # 建设前评估
    POST = "post"  # 建设后评估


class EvaluationMethod(str, Enum):
    """评估方法"""
    MCKINSEY = "mckinsey"
    DX = "dx"
    BCG = "bcg"
    MIT = "mit"
    SERVICENOW = "servicenow"
    YIOU = "yiou"


@dataclass
class DocumentInfo:
    """文档信息"""
    filename: str
    content: str
    parsed_data: Optional[Dict[str, Any]] = None
    upload_time: datetime = field(default_factory=datetime.now)


@dataclass
class MetricResult:
    """单个指标结果"""
    name: str
    value: Any
    unit: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None


@dataclass
class EvaluationInput:
    """评估输入数据"""
    scenario: ScenarioType
    method: EvaluationMethod
    documents: List[DocumentInfo]
    user_inputs: Dict[str, Any] = field(default_factory=dict)
    related_evaluation_id: Optional[str] = None  # 关联的评估ID（用于后期验证关联前期评估）


@dataclass
class EvaluationReport:
    """评估报告"""
    id: str
    scenario: ScenarioType
    method: EvaluationMethod
    timestamp: datetime

    # 输入数据
    user_input: Dict[str, Any]
    documents: List[DocumentInfo]

    # 评估结果
    metrics: List[MetricResult]
    summary: str
    recommendations: List[str]

    # 可视化数据
    visualizations: Dict[str, Any] = field(default_factory=dict)

    # 原始LLM输出
    raw_llm_output: str = ""

    # 关联评估
    related_evaluation_id: Optional[str] = None

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationSession:
    """评估会话"""
    session_id: str
    scenario: ScenarioType
    method: Optional[EvaluationMethod]
    chat_history: List[ChatMessage] = field(default_factory=list)
    documents: List[DocumentInfo] = field(default_factory=list)
    current_step: str = "init"
    state: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


# 方法元数据
EVALUATION_METHODS_INFO = {
    EvaluationMethod.MCKINSEY: {
        "name": "麦肯锡高效能基准法",
        "name_en": "McKinsey High Performer Benchmarking",
        "description": "通过对标行业高效能者的实践，评估AI部署路径和成熟度",
        "适用场景": "企业级AI成熟度评估、寻找与行业领跑者的差距",
        "核心指标": ["部署原型", "战略清晰度", "运营模式", "技术工程化", "风险管理"],
        "前期评估": "部署路径决策（Taker/Shaper/Maker）",
        "后期验证": "成熟度对标与差距分析"
    },
    EvaluationMethod.DX: {
        "name": "DX研发效能ROI法",
        "name_en": "DX Developer Experience ROI",
        "description": "专注研发场景，通过利用率-影响-成本三维评估AI工具价值",
        "适用场景": "软件研发部门、CTO办公室，评估Copilot或Devin类工具的效果",
        "核心指标": ["工具活跃度", "节省时间", "周期时间", "变更失败率", "智能体等效工时", "净时间收益"],
        "前期评估": "基线与预期设定",
        "后期验证": "真实ROI计算与三维诊断"
    },
    EvaluationMethod.BCG: {
        "name": "BCG变革配比法(10-20-70)",
        "name_en": "BCG Transformation Allocation",
        "description": "强调AI项目中业务变革的重要性，避免技术中心论陷阱",
        "适用场景": "数字化转型项目立项、资源分配审查",
        "核心指标": ["算法投入占比", "IT基建占比", "业务变革占比", "流程重塑率", "价值归因"],
        "前期评估": "预算与资源审计（10-20-70配比）",
        "后期验证": "流程变革深度评估"
    },
    EvaluationMethod.MIT: {
        "name": "MIT AI平衡计分卡",
        "name_en": "MIT AI Balanced Scorecard",
        "description": "从财务、客户、流程、学习四个维度全面评估AI价值",
        "适用场景": "董事会汇报、长期战略规划、评估AI的无形资产",
        "核心指标": ["财务ROI", "客户满意度", "流程效率", "数据资产", "算法资产", "人才密度"],
        "前期评估": "价值地图绘制（四象限映射）",
        "后期验证": "无形资产盘点与平衡性评分"
    },
    EvaluationMethod.SERVICENOW: {
        "name": "ServiceNow/Deloitte价值三角",
        "name_en": "ServiceNow Value Triangle",
        "description": "确保成本、运营、体验三个维度平衡发展，防止单维度优化",
        "适用场景": "具体AI应用场景的落地效果监测（如AI客服、AI代码助手）",
        "核心指标": ["单位成本", "处理时长", "吞吐量", "用户接受率", "员工推荐值"],
        "前期评估": "三角破坏测试与Guardrails设定",
        "后期验证": "平衡性诊断与偏态分析"
    },
    EvaluationMethod.YIOU: {
        "name": "亿欧SCE场景评估法",
        "name_en": "YiOu SCE Model",
        "description": "通过战略-成本-经济三维加权打分，快速筛选高价值场景",
        "适用场景": "中国企业进行大模型选型、应用场景筛选",
        "核心指标": ["战略价值(S)", "成本价值(C)", "经济价值(E)", "综合得分", "兑现率"],
        "前期评估": "场景打分与优先级排序",
        "后期验证": "价值兑现率与偏差分析"
    }
}
