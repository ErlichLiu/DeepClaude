"""DeepSeek API 客户端"""

import os
import json
from typing import AsyncGenerator

from app.utils.logger import logger

from .base_client import BaseClient


class DeepSeekClient(BaseClient):
    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.siliconflow.cn/v1/chat/completions",
        proxy: str = None,
        system_config: dict = None,
    ):
        """初始化 DeepSeek 客户端

        Args:
            api_key: DeepSeek API密钥
            api_url: DeepSeek API地址
            proxy: 代理服务器地址
            system_config: 系统配置，包含 save_deepseek_tokens 等设置
        """
        super().__init__(api_key, api_url, proxy=proxy)
        self.system_config = system_config or {}

    def _process_think_tag_content(self, content: str) -> tuple[bool, str]:
        """处理包含 think 标签的内容

        Args:
            content: 需要处理的内容字符串

        Returns:
            tuple[bool, str]:
                bool: 是否检测到完整的 think 标签对
                str: 处理后的内容
        """
        has_start = "<think>" in content
        has_end = "</think>" in content

        if has_start and has_end:
            return True, content
        elif has_start:
            return False, content
        elif not has_start and not has_end:
            return False, content
        else:
            return True, content

    async def stream_chat(
        self,
        messages: list,
        model: str = "deepseek-ai/DeepSeek-R1",
        is_origin_reasoning: bool = True,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """流式对话

        Args:
            messages: 消息列表
            model: 模型名称

        Yields:
            tuple[str, str]: (内容类型, 内容)
                内容类型: "reasoning" 或 "content"
                内容: 实际的文本内容
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        data = {
            "model": model,
            "messages": messages,
            "stream": True
        }
        
        # 检测是否为 DeepSeek v3.1 模型，默认启用思考模式
        is_v31_model = (
            model == "deepseek-v3-1-250821" or
            "v3.1" in model.lower() or
            "v3-1" in model.lower()
        )
        
        if is_v31_model:
            data["thinking"] = {"type": "enabled"}
            logger.info(f"检测到 DeepSeek v3.1 模型 ({model})，已启用思考模式")

        # 检查系统配置中的 save_deepseek_tokens 设置
        save_deepseek_tokens = self.system_config.get("save_deepseek_tokens", False)
        max_tokens_limit = self.system_config.get("save_deepseek_tokens_max_tokens", 5)

        logger.info(f"DeepSeek 客户端配置 - save_deepseek_tokens: {save_deepseek_tokens}, max_tokens_limit: {max_tokens_limit}")

        # 如果模型包含 deepseek-v3.1-terminus，启用 thinking 模式
        if "terminus" in model.lower():
            data["enable_thinking"] = True

        # 只在支持原生推理且开启了节省 tokens 功能时才添加 max_tokens 参数
        if is_origin_reasoning and save_deepseek_tokens:
            data["max_tokens"] = max_tokens_limit
            logger.info(f"已开启节省 DeepSeek tokens 功能，设置 max_tokens 为: {max_tokens_limit}")

        logger.debug(f"开始流式对话：{data}")

        accumulated_content = ""
        is_collecting_think = False

        async for chunk in self._make_request(headers, data):
            chunk_str = chunk.decode("utf-8")

            try:
                lines = chunk_str.splitlines()
                for line in lines:
                    if line.startswith("data: "):
                        json_str = line[len("data: ") :]
                        if json_str == "[DONE]":
                            return

                        data = json.loads(json_str)
                        if (
                            data
                            and data.get("choices")
                            and data["choices"][0].get("delta")
                        ):
                            delta = data["choices"][0]["delta"]

                            if is_origin_reasoning:
                                # 处理 reasoning_content
                                if delta.get("reasoning_content"):
                                    content = delta["reasoning_content"]
                                    logger.debug(f"提取推理内容：{content}")
                                    yield "reasoning", content

                                if delta.get("reasoning_content") is None and delta.get(
                                    "content"
                                ):
                                    content = delta["content"]
                                    logger.info(
                                        f"提取内容信息，推理阶段结束: {content}"
                                    )
                                    yield "content", content
                            else:
                                # 处理其他模型的输出
                                if delta.get("content"):
                                    content = delta["content"]
                                    if content == "":  # 只跳过完全空的字符串
                                        continue
                                    logger.debug(f"非原生推理内容：{content}")
                                    accumulated_content += content

                                    # 检查累积的内容是否包含完整的 think 标签对
                                    is_complete, processed_content = (
                                        self._process_think_tag_content(
                                            accumulated_content
                                        )
                                    )

                                    if "<think>" in content and not is_collecting_think:
                                        # 开始收集推理内容
                                        logger.debug(f"开始收集推理内容：{content}")
                                        is_collecting_think = True
                                        yield "reasoning", content
                                    elif is_collecting_think:
                                        if "</think>" in content:
                                            # 推理内容结束
                                            logger.debug(f"推理内容结束：{content}")
                                            is_collecting_think = False
                                            yield "reasoning", content
                                            # 输出空的 content 来触发 Claude 处理
                                            yield "content", ""
                                            # 重置累积内容
                                            accumulated_content = ""
                                        else:
                                            # 继续收集推理内容
                                            yield "reasoning", content
                                    else:
                                        # 普通内容
                                        yield "content", content

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析错误: {e}")
            except Exception as e:
                logger.error(f"处理 chunk 时发生错误: {e}")
