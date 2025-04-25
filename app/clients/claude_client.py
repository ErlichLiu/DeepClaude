"""Claude API 客户端"""

import json
from typing import AsyncGenerator, Dict, Optional

from app.utils.logger import logger

from .base_client import BaseClient


class ClaudeClient(BaseClient):
    """Claude API 客户端"""
    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.anthropic.com/v1/messages",
        provider: str = "anthropic",
        proxy: str = None,
    ):
        """初始化 Claude 客户端

        Args:
            api_key: Claude API密钥
            api_url: Claude API地址
            provider: API提供商，支持 anthropic、openrouter、oneapi
            proxy: 代理服务器地址
        """
        super().__init__(api_key, api_url, proxy=proxy)
        self.provider = provider

    def data_format(
        self,
        messages: list,
        model_arg: Dict[str, Optional[float]],
        model: str,
        system_prompt: str = None,
        stream: bool = True
    ):
        """数据格式化

        Args:
            messages: 消息列表
            model_arg: 模型参数元组[temperature, top_p, presence_penalty, frequency_penalty]
            model: 模型名称。如果是 OpenRouter, 会自动转换为 'anthropic/claude-3.5-sonnet' 格式
            system_prompt: 系统提示
            stream: 是否使用流式输出，默认为 True

        Returns:
            tuple[str, str]: (内容类型, 内容)
                内容类型: "answer"
                内容: 实际的文本内容
        """
        if self.provider == "openrouter":
            # 转换模型名称为 OpenRouter 格式
            model = "anthropic/" + model

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/ErlichLiu/DeepClaude",  # OpenRouter 需要
                "X-Title": "DeepClaude",  # OpenRouter 需要
            }

            # 传递 OpenRouterOneAPI system prompt
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            data = {
                "model": model,  # OpenRouter 使用 anthropic/claude-3.5-sonnet 格式
                "messages": messages,
                "stream": stream,
            }
            # 只有当参数值存在时才添加到请求数据中
            if model_arg.get("temperature") is not None:
                data["temperature"] = model_arg["temperature"]
            if model_arg.get("top_p") is not None:
                data["top_p"] = model_arg["top_p"]
            if model_arg.get("presence_penalty") is not None:
                data["presence_penalty"] = model_arg["presence_penalty"]
            if model_arg.get("frequency_penalty") is not None:
                data["frequency_penalty"] = model_arg["frequency_penalty"]

        elif self.provider == "oneapi":
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # 传递 OneAPI system prompt
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            data = {
                "model": model,
                "messages": messages,
                "stream": stream,
            }
            # 只有当参数值存在时才添加到请求数据中
            if model_arg.get("temperature") is not None:
                data["temperature"] = model_arg["temperature"]
            if model_arg.get("top_p") is not None:
                data["top_p"] = model_arg["top_p"]
            if model_arg.get("presence_penalty") is not None:
                data["presence_penalty"] = model_arg["presence_penalty"]
            if model_arg.get("frequency_penalty") is not None:
                data["frequency_penalty"] = model_arg["frequency_penalty"]

        elif self.provider == "anthropic":
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "accept": "text/event-stream" if stream else "application/json",
            }

            data = {
                "model": model,
                "messages": messages,
                "max_tokens": 8192,
                "stream": stream,
            }

            # Anthropic 原生 API 支持 system 参数
            if system_prompt:
                data["system"] = system_prompt
            # 只有当参数值存在时才添加到请求数据中
            if model_arg.get("temperature") is not None:
                data["temperature"] = model_arg["temperature"]
            if model_arg.get("top_p") is not None:
                data["top_p"] = model_arg["top_p"]

        else:
            raise ValueError(f"不支持的Claude Provider: {self.provider}")

        return headers, data


    async def chat(
        self,
        messages: list,
        model_arg: Dict[str, Optional[float]],
        model: str,
        stream: bool = True,
        system_prompt: str = None,)-> AsyncGenerator[tuple[str, str], None]:
        """非流式对话

        Args:
            messages: 消息列表
            model_arg: 模型参数元组[temperature, top_p, presence_penalty, frequency_penalty]
            model: 模型名称
            stream: 是否使用流式输出，默认为 True
            system_prompt: 系统提示

        Yields:
            tuple[str, str]: (role, content) 消息元组
                role: 角色
                content: 实际的文本内容
        """
        headers, data = self.data_format(messages, model_arg, model, system_prompt, stream)
        logger.debug("开始对话: ")
        async for chunk in self._make_request(headers, data):
            try:
                response = json.loads(chunk.decode("utf-8"))
                if self.provider in ("openrouter", "oneapi"):
                    content = (
                        response.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    if content:
                        yield "answer", content
                elif self.provider == "anthropic":
                    content = response.get("content", [{}])[0].get("text", "")
                    if content:
                        yield "answer", content
                else:
                    raise ValueError(f"不支持的Claude Provider: {self.provider}")
            except json.JSONDecodeError:
                continue

    async def stream_chat(
        self,
        messages: list,
        model_arg: Dict[str, Optional[float]],
        model: str,
        stream: bool = True,
        system_prompt: str = None,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """流式对话

        Args:
            messages: 消息列表
            model_arg: 模型参数元组[temperature, top_p, presence_penalty, frequency_penalty]
            model: 模型名称
            stream: 是否使用流式输出，默认为 True
            system_prompt: 系统提示

        Yields:
            tuple[str, str]: (内容类型, 内容)
                内容类型: "answer"
                内容: 实际的文本内容
        """
        headers, data = self.data_format(messages, model_arg, model, system_prompt, stream)

        logger.debug("开始对话: ")
        async for chunk in self._make_request(headers, data):
            chunk_str = chunk.decode("utf-8")
            if not chunk_str.strip():
                continue

            for line in chunk_str.split("\n"):
                if line.startswith("data: "):
                    json_str = line[6:]  # 去掉 'data: ' 前缀
                    if json_str.strip() == "[DONE]":
                        return

                    try:
                        data = json.loads(json_str)
                        if self.provider in ("openrouter", "oneapi"):
                            # OpenRouter/OneApi 格式
                            content = (
                                data.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content:
                                yield "answer", content
                        elif self.provider == "anthropic":
                            # Anthropic 格式
                            if data.get("type") == "content_block_delta":
                                content = data.get("delta", {}).get("text", "")
                                if content:
                                    yield "answer", content
                        else:
                            raise ValueError(
                                f"不支持的Claude Provider: {self.provider}"
                            )
                    except json.JSONDecodeError:
                        continue
