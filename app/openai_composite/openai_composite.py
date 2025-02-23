"""OpenAI 兼容的组合模型服务，用于协调 DeepSeek 和其他 OpenAI 兼容模型的调用"""

import asyncio
import json
import time
from typing import AsyncGenerator, Dict, Any, List

from app.clients import DeepSeekClient
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.utils.logger import logger


class OpenAICompatibleComposite:
    """处理 DeepSeek 和其他 OpenAI 兼容模型的流式输出衔接"""

    def __init__(
        self,
        deepseek_api_key: str,
        openai_api_key: str,
        deepseek_api_url: str = "https://api.deepseek.com/v1/chat/completions",
        openai_api_url: str = "",  # 将由具体实现提供
        is_origin_reasoning: bool = True,
    ):
        """初始化 API 客户端

        Args:
            deepseek_api_key: DeepSeek API密钥
            openai_api_key: OpenAI 兼容服务的 API密钥
            deepseek_api_url: DeepSeek API地址
            openai_api_url: OpenAI 兼容服务的 API地址
            is_origin_reasoning: 是否使用原始推理过程
        """
        self.deepseek_client = DeepSeekClient(deepseek_api_key, deepseek_api_url)
        self.openai_client = OpenAICompatibleClient(openai_api_key, openai_api_url)
        self.is_origin_reasoning = is_origin_reasoning

    async def chat_completions_with_stream(
        self,
        messages: List[Dict[str, str]],
        model_arg: tuple[float, float, float, float],
        deepseek_model: str = "deepseek-reasoner",
        target_model: str = "",
    ) -> AsyncGenerator[bytes, None]:
        """处理完整的流式输出过程

        Args:
            messages: 初始消息列表
            model_arg: 模型参数 (temperature, top_p, presence_penalty, frequency_penalty)
            deepseek_model: DeepSeek 模型名称
            target_model: 目标 OpenAI 兼容模型名称

        Yields:
            字节流数据，格式如下：
            {
                "id": "chatcmpl-xxx",
                "object": "chat.completion.chunk",
                "created": timestamp,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "reasoning_content": reasoning_content,
                        "content": content
                    }
                }]
            }
        """
        # 生成唯一的会话ID和时间戳
        chat_id = f"chatcmpl-{hex(int(time.time() * 1000))[2:]}"
        created_time = int(time.time())

        # 创建队列，用于收集输出数据
        output_queue = asyncio.Queue()
        # 队列，用于传递 DeepSeek 推理内容
        reasoning_queue = asyncio.Queue()

        # 用于存储 DeepSeek 的推理累积内容
        reasoning_content = []

        async def process_deepseek():
            logger.info(f"开始处理 DeepSeek 流，使用模型：{deepseek_model}")
            try:
                async for content_type, content in self.deepseek_client.stream_chat(
                    messages, deepseek_model, self.is_origin_reasoning
                ):
                    if content_type == "reasoning":
                        reasoning_content.append(content)
                        response = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": deepseek_model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "reasoning_content": content,
                                        "content": "",
                                    },
                                }
                            ],
                        }
                        await output_queue.put(
                            f"data: {json.dumps(response)}\n\n".encode("utf-8")
                        )
                    elif content_type == "content":
                        # 当收到 content 类型时，将完整的推理内容发送到 reasoning_queue
                        logger.info(
                            f"DeepSeek 推理完成，收集到的推理内容长度：{len(''.join(reasoning_content))}"
                        )
                        await reasoning_queue.put("".join(reasoning_content))
                        break
            except Exception as e:
                logger.error(f"处理 DeepSeek 流时发生错误: {e}")
                await reasoning_queue.put("")
            # 标记 DeepSeek 任务结束
            logger.info("DeepSeek 任务处理完成，标记结束")
            await output_queue.put(None)

        async def process_openai():
            try:
                logger.info("等待获取 DeepSeek 的推理内容...")
                reasoning = await reasoning_queue.get()
                logger.debug(
                    f"获取到推理内容，内容长度：{len(reasoning) if reasoning else 0}"
                )
                if not reasoning:
                    logger.warning("未能获取到有效的推理内容，将使用默认提示继续")
                    reasoning = "获取推理内容失败"

                # 构造 OpenAI 的输入消息
                openai_messages = messages.copy()
                combined_content = f"""
                Here's my another model's reasoning process:\n{reasoning}\n\n
                Based on this reasoning, provide your response directly to me:"""

                # 处理可能 messages 内存在 role = system 的情况
                openai_messages = [
                    message
                    for message in openai_messages
                    if message.get("role", "") != "system"
                ]

                # 检查过滤后的消息列表是否为空
                if not openai_messages:
                    raise ValueError("消息列表为空，无法处理请求")

                # 获取最后一个消息并检查其角色
                last_message = openai_messages[-1]
                if last_message.get("role", "") != "user":
                    raise ValueError("最后一个消息的角色不是用户，无法处理请求")

                # 修改最后一个消息的内容
                original_content = last_message["content"]
                fixed_content = f"Here's my original input:\n{original_content}\n\n{combined_content}"
                last_message["content"] = fixed_content

                logger.info(f"开始处理 OpenAI 兼容流，使用模型: {target_model}")

                async for role, content in self.openai_client.stream_chat(
                    messages=openai_messages,
                    model=target_model,
                ):
                    response = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": target_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": role, "content": content},
                            }
                        ],
                    }
                    await output_queue.put(
                        f"data: {json.dumps(response)}\n\n".encode("utf-8")
                    )
            except Exception as e:
                logger.error(f"处理 OpenAI 兼容流时发生错误: {e}")
            # 标记 OpenAI 任务结束
            logger.info("OpenAI 兼容任务处理完成，标记结束")
            await output_queue.put(None)

        # 创建并发任务
        asyncio.create_task(process_deepseek())
        asyncio.create_task(process_openai())

        # 等待两个任务完成
        finished_tasks = 0
        while finished_tasks < 2:
            item = await output_queue.get()
            if item is None:
                finished_tasks += 1
                continue
            yield item

        # 发送结束标记
        yield b"data: [DONE]\n\n"

    async def chat_completions_without_stream(
        self,
        messages: List[Dict[str, str]],
        model_arg: tuple[float, float, float, float],
        deepseek_model: str = "deepseek-reasoner",
        target_model: str = "",
    ) -> Dict[str, Any]:
        """处理非流式输出请求

        Args:
            messages: 初始消息列表
            model_arg: 模型参数
            deepseek_model: DeepSeek 模型名称
            target_model: 目标 OpenAI 兼容模型名称

        Returns:
            Dict[str, Any]: 完整的响应数据
        """
        full_response = {
            "id": f"chatcmpl-{hex(int(time.time() * 1000))[2:]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": target_model,
            "choices": [],
            "usage": {},
        }

        content_parts = []
        async for chunk in self.chat_completions_with_stream(
            messages, model_arg, deepseek_model, target_model
        ):
            if chunk != b"data: [DONE]\n\n":
                try:
                    response_data = json.loads(chunk.decode("utf-8")[6:])
                    if (
                        "choices" in response_data
                        and len(response_data["choices"]) > 0
                        and "delta" in response_data["choices"][0]
                    ):
                        delta = response_data["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            content_parts.append(delta["content"])
                except json.JSONDecodeError:
                    continue

        full_response["choices"] = [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(content_parts)},
                "finish_reason": "stop",
            }
        ]

        return full_response
