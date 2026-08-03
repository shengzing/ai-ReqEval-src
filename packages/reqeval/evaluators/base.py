"""
评估器基类 - 所有评估方法的抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
import uuid

from src.packages.reqeval.data.models import (
    EvaluationReport, EvaluationInput, MetricResult,
    DocumentInfo, ScenarioType, EvaluationMethod
)


@dataclass
class EvaluatorConfig:
    """评估器配置"""
    method: EvaluationMethod
    name: str
    name_en: str
    description: str
    applicable_scenarios: List[str]
    core_metrics: List[str]
    pre_evaluation_desc: str
    post_evaluation_desc: str


class BaseEvaluator(ABC):
    """
    评估器基类

    所有评估方法（McKinsey, DX, BCG, MIT, ServiceNow, YiOu）
    都必须继承此基类并实现相应方法。
    """

    def __init__(self, llm_client=None):
        """
        初始化评估器

        Args:
            llm_client: LLM客户端（用于智能分析）
        """
        self.llm_client = llm_client
        self.config = self._get_config()

    @abstractmethod
    def _get_config(self) -> EvaluatorConfig:
        """获取评估器配置（子类必须实现）"""
        pass

    @abstractmethod
    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        前期评估（建设前）

        Args:
            inputs: 评估输入数据，包含：
                - documents: 上传的文档内容
                - user_inputs: 用户通过对话提供的信息
                - context: 上下文信息

        Returns:
            EvaluationReport: 评估报告
        """
        pass

    @abstractmethod
    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        后期验证（建设后）

        Args:
            inputs: 评估输入数据，包含：
                - documents: 实施后的数据文档
                - user_inputs: 用户提供的实际数据
                - pre_evaluation: 关联的前期评估报告（可选）

        Returns:
            EvaluationReport: 验证报告
        """
        pass

    @abstractmethod
    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        """
        获取所需输入信息

        Args:
            scenario: 评估场景（pre/post）

        Returns:
            所需输入信息的结构定义，包含：
            - fields: 必填字段列表
            - optional_fields: 可选字段列表
            - descriptions: 字段说明
        """
        pass

    @abstractmethod
    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        """
        计算评估指标

        Args:
            data: 输入数据

        Returns:
            计算后的指标列表
        """
        pass

    def generate_report(
        self,
        scenario: ScenarioType,
        metrics: List[MetricResult],
        summary: str,
        recommendations: List[str],
        user_input: Dict[str, Any],
        documents: List[DocumentInfo],
        visualizations: Dict[str, Any] = None,
        raw_llm_output: str = "",
        related_evaluation_id: Optional[str] = None
    ) -> EvaluationReport:
        """
        生成评估报告

        Args:
            scenario: 评估场景
            metrics: 指标列表
            summary: 评估摘要
            recommendations: 建议列表
            user_input: 用户输入
            documents: 文档列表
            visualizations: 可视化数据
            raw_llm_output: 原始LLM输出
            related_evaluation_id: 关联的评估ID

        Returns:
            EvaluationReport: 完整的评估报告
        """
        return EvaluationReport(
            id=str(uuid.uuid4()),
            scenario=scenario,
            method=self.config.method,
            timestamp=datetime.now(),
            user_input=user_input,
            documents=documents,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            visualizations=visualizations or {},
            raw_llm_output=raw_llm_output,
            related_evaluation_id=related_evaluation_id,
            metadata={
                "evaluator": self.config.name,
                "version": "1.0"
            }
        )

    def validate_inputs(self, inputs: Dict[str, Any], scenario: ScenarioType) -> tuple[bool, List[str]]:
        """
        验证输入数据

        Args:
            inputs: 输入数据
            scenario: 评估场景

        Returns:
            (是否有效, 错误信息列表)
        """
        required = self.get_required_inputs(scenario)
        errors = []

        for field in required.get("fields", []):
            if field not in inputs or inputs[field] is None:
                errors.append(f"缺少必填字段: {field}")

        return len(errors) == 0, errors

    def _call_llm(self, prompt: str, system_prompt: str = None) -> str:
        """
        调用LLM

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词

        Returns:
            LLM响应文本
        """
        if self.llm_client is None:
            return ""

        try:
            return self.llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt
            )
        except Exception as e:
            print(f"LLM调用失败: {e}")
            return ""

    def _extract_json_from_response(self, response: str) -> Dict[str, Any]:
        """从LLM响应中提取JSON"""
        import json
        import re

        # 尝试直接解析
        try:
            return json.loads(response)
        except:
            pass

        # 尝试提取```json```块
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass

        # 尝试提取{}块
        brace_match = re.search(r'\{.*\}', response, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except:
                pass

        return {}

    def get_info(self) -> Dict[str, Any]:
        """获取评估器信息"""
        return {
            "method": self.config.method.value,
            "name": self.config.name,
            "name_en": self.config.name_en,
            "description": self.config.description,
            "applicable_scenarios": self.config.applicable_scenarios,
            "core_metrics": self.config.core_metrics,
            "pre_evaluation": self.config.pre_evaluation_desc,
            "post_evaluation": self.config.post_evaluation_desc
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        """
        获取提示词模板（如需与LLM结合时使用）
        返回结构: {"pre": "...", "post": "..."}
        """
        return {}
