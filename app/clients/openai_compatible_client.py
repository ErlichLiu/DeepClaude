"""OpenAI 兼容格式的客户端类,用于处理符合 OpenAI API 格式的服务"""

import json
from typing import AsyncGenerator, Optional, Dict, Any, List

import aiohttp
from aiohttp.client_exceptions import ClientError

from app.clients.base_client import BaseClient
from app.utils.logger import logger


class OpenAICompatibleClient(BaseClient):
    """OpenAI 兼容格式的客户端类

    用于处理符合 OpenAI API 格式的服务,如 Gemini 等
    """

    def __init__(
        self,
        api_key: str,
        api_url: str,
        timeout: Optional[aiohttp.ClientTimeout] = None,
        proxy: str = None,
    ):
        """初始化 OpenAI 兼容客户端

        Args:
            api_key: API密钥
            api_url: API地址
            timeout: 请求超时设置,None则使用默认值
            proxy: 代理服务器地址
        """
        super().__init__(api_key, api_url, timeout, proxy=proxy)

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头

        Returns:
            Dict[str, str]: 请求头字典
        """
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _prepare_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """处理消息格式

        Args:
            messages: 原始消息列表

        Returns:
            List[Dict[str, str]]: 处理后的消息列表
        """
        return messages

    async def chat(
        self, messages: List[Dict[str, str]], model: str, model_arg: Dict[str, Optional[float]]
    ) -> Dict[str, Any]:
        """非流式对话

        Args:
            messages: 消息列表
            model: 模型名称

        Returns:
            Dict[str, Any]: OpenAI 格式的完整响应

        Raises:
            ClientError: 请求错误
        """
        headers = self._get_headers()
        processed_messages = self._prepare_messages(messages)

        data = {
            "model": model,
            "messages": processed_messages,
            "stream": False,
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

        try:
            response_chunks = []
            async for chunk in self._make_request(headers, data):
                response_chunks.append(chunk)

            response_text = b"".join(response_chunks).decode("utf-8")
            return json.loads(response_text)

        except Exception as e:
            error_msg = f"Chat请求失败: {str(e)}"
            logger.error(error_msg)
            raise ClientError(error_msg) from e

    async def stream_chat(
        self, messages: List[Dict[str, str]], model: str, model_arg: Dict[str, Optional[float]]
    ) -> AsyncGenerator[tuple[str, str], None]:
        """流式对话

        Args:
            messages: 消息列表
            model: 模型名称

        Yields:
            tuple[str, str]: (role, content) 消息元组

        Raises:
            ClientError: 请求错误
        """
        headers = self._get_headers()
        processed_messages = self._prepare_messages(messages)

        data = {
            "model": model,
            "messages": processed_messages,
            "stream": True,
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


        buffer = ""
        try:
            async for chunk in self._make_request(headers, data):
                buffer += chunk.decode("utf-8")

                # 处理 buffer 中的数据行
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()

                    # 跳过空行和 data: [DONE] 行
                    if not line or line == "data: [DONE]":
                        continue

                    # 解析 SSE 数据
                    if line.startswith("data: "):
                        json_str = line[6:].strip()
                        try:
                            response = json.loads(json_str)
                            if (
                                "choices" in response
                                and len(response["choices"]) > 0
                                and "delta" in response["choices"][0]
                            ):
                                delta = response["choices"][0]["delta"]
                                if "content" in delta:
                                    yield "assistant", delta["content"]
                        except json.JSONDecodeError as e:
                            logger.error("JSON解析错误: %s, 原始数据: %s", str(e), json_str)
                            continue

        except Exception as e:
            error_msg = f"Stream chat请求失败: {str(e)}"
            logger.error(error_msg)
            raise ClientError(error_msg) from e
