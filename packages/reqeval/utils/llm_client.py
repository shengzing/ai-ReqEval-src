"""
LLM客户端封装
支持Anthropic Claude和OpenAI
"""
import os
from typing import Optional, Dict, Any, Generator
from abc import ABC, abstractmethod

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class BaseLLMClient(ABC):
    """LLM客户端基类"""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> str:
        """生成文本"""
        pass

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Generator[str, None, None]:
        """流式生成文本"""
        pass


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        base_url: Optional[str] = None,
    ):
        if Anthropic is None:
            raise ImportError("请安装anthropic: pip install anthropic")

        # Workaround for anthropic SDK: if ANTHROPIC_AUTH_TOKEN is present but empty/whitespace,
        # it produces an invalid `Authorization: Bearer ` header and requests fail.
        if "ANTHROPIC_AUTH_TOKEN" in os.environ and not os.environ["ANTHROPIC_AUTH_TOKEN"].strip():
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("未提供Anthropic API Key")

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = Anthropic(**client_kwargs)
        self.model = model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> str:
        """生成文本"""
        messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        return response.content[0].text

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Generator[str, None, None]:
        """流式生成文本"""
        messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text


class OpenAIClient(BaseLLMClient):
    """OpenAI客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        base_url: Optional[str] = None
    ):
        if OpenAI is None:
            raise ImportError("请安装openai: pip install openai")

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("未提供OpenAI API Key")

        client_kwargs = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        self.model = model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> str:
        """生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Generator[str, None, None]:
        """流式生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class MockLLMClient(BaseLLMClient):
    """模拟LLM客户端（用于测试）"""

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> str:
        return f"[Mock Response] Received prompt: {prompt[:100]}..."

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Generator[str, None, None]:
        response = self.generate(prompt, system_prompt, temperature, max_tokens)
        for char in response:
            yield char


def create_llm_client(
    provider: str = "anthropic",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseLLMClient:
    """
    创建LLM客户端

    Args:
        provider: 提供商 (anthropic, openai, mock)
        api_key: API密钥
        model: 模型名称
        **kwargs: 其他参数

    Returns:
        LLM客户端实例
    """
    provider = provider.lower()

    if provider == "anthropic":
        return AnthropicClient(
            api_key=api_key,
            model=model or "claude-sonnet-4-5-20250929",
            base_url=kwargs.get("base_url"),
        )
    elif provider == "openai":
        return OpenAIClient(
            api_key=api_key,
            model=model or "gpt-4o",
            base_url=kwargs.get("base_url")
        )
    elif provider == "mock":
        return MockLLMClient()
    else:
        raise ValueError(f"未知的LLM提供商: {provider}")
