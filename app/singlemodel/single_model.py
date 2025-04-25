"""单模型服务，用于处理单个模型API的调用"""

import asyncio
import json
import time
from typing import AsyncGenerator, Dict, Any, List, Tuple
from app.clients import DeepSeekClient, ClaudeClient,OpenAICompatibleClient

import tiktoken

from app.utils.logger import logger


class SingleModel:
    """处理单个模型API的调用，支持流式和非流式输出"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model_type: str = "openai",  # 支持 "openai", "anthropic", "deepseek" 等
        proxy: str = None
    ):
        """初始化 API 客户端

        Args:
            api_key: API密钥
            api_url: API地址
            model_type: 模型类型，支持 "openai", "anthropic", "deepseek" 等
            proxy: 代理服务器地址
        """
        self.api_key = api_key
        self.api_url = api_url
        self.model_type = model_type
        self.proxy = proxy
        
        # 根据模型类型初始化对应的客户端
        if model_type == "openai":
            self.client = OpenAICompatibleClient(api_key, api_url, proxy=proxy)
        elif model_type == "anthropic":
            self.client = ClaudeClient(api_key, api_url, "anthropic", proxy=proxy)
        elif model_type == "deepseek":
            self.client = DeepSeekClient(api_key, api_url, proxy=proxy)
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")

    async def chat_completions_with_stream(
        self,
        messages: List[Dict[str, str]],
        model_arg: Tuple[float, float, float, float],
        model: str,
    ) -> AsyncGenerator[bytes, None]:
        """处理流式输出过程

        Args:
            messages: 消息列表
            model_arg: 模型参数 (temperature, top_p, presence_penalty, frequency_penalty)
            model: 模型名称

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
                        "content": content
                    }
                }]
            }
        """
        # 生成唯一的会话ID和时间戳
        chat_id = f"chatcmpl-{hex(int(time.time() * 1000))[2:]}"
        created_time = int(time.time())
        
        temperature, top_p, presence_penalty, frequency_penalty = model_arg
        
        # 创建队列，用于收集输出数据
        output_queue = asyncio.Queue()
        
        async def process_stream():
            try:
                logger.info(f"开始处理流式输出，使用模型：{model}")
                
                if self.model_type == "openai":
                    async for content in self.client.stream_chat(
                        messages, 
                        model,
                        temperature=temperature,
                        top_p=top_p,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty
                    ):
                        response = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": content,
                                    },
                                }
                            ],
                        }
                        await output_queue.put(
                            f"data: {json.dumps(response)}\n\n".encode("utf-8")
                        )
                        
                elif self.model_type == "anthropic":
                    async for content in self.client.stream_chat(
                        messages, 
                        model,
                        temperature=temperature,
                        top_p=top_p
                    ):
                        response = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": content,
                                    },
                                }
                            ],
                        }
                        await output_queue.put(
                            f"data: {json.dumps(response)}\n\n".encode("utf-8")
                        )
                        
                elif self.model_type == "deepseek":
                    async for content_type, content in self.client.stream_chat(
                        messages, model, False
                    ):
                        if content_type == "content":
                            response = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "role": "assistant",
                                            "content": content,
                                        },
                                    }
                                ],
                            }
                            await output_queue.put(
                                f"data: {json.dumps(response)}\n\n".encode("utf-8")
                            )
                
            except Exception as e:
                logger.error(f"处理流式输出时发生错误: {e}")
            
            # 标记任务结束
            logger.info("流式输出处理完成")
            await output_queue.put(None)
        
        # 创建任务
        asyncio.create_task(process_stream())
        
        # 等待任务完成
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        
        # 发送结束标记
        yield b"data: [DONE]\n\n"

    async def chat_completions_without_stream(
        self,
        messages: List[Dict[str, str]],
        model_arg: Tuple[float, float, float, float],
        model: str,
    ) -> Dict[str, Any]:
        """处理非流式输出过程

        Args:
            messages: 消息列表
            model_arg: 模型参数 (temperature, top_p, presence_penalty, frequency_penalty)
            model: 模型名称

        Returns:
            Dict[str, Any]: OpenAI 格式的完整响应
        """
        chat_id = f"chatcmpl-{hex(int(time.time() * 1000))[2:]}"
        created_time = int(time.time())
        temperature, top_p, presence_penalty, frequency_penalty = model_arg
        
        try:
            # 计算输入tokens
            token_content = "\n".join(
                [message.get("content", "") for message in messages]
            )
            encoding = tiktoken.encoding_for_model("gpt-4o")
            input_tokens = encoding.encode(token_content)
            logger.debug(f"输入 Tokens: {len(input_tokens)}")
            
            # 根据不同模型类型获取响应
            if self.model_type == "openai":
                response_content = await self.client.chat_completion(
                    messages, 
                    model,
                    temperature=temperature,
                    top_p=top_p,
                    presence_penalty=presence_penalty,
                    frequency_penalty=frequency_penalty
                )
                
            elif self.model_type == "anthropic":
                response_content = await self.client.chat_completion(
                    messages, 
                    model,
                    temperature=temperature,
                    top_p=top_p
                )
                
            elif self.model_type == "deepseek":
                response_content = await self.client.chat_completion(
                    messages, 
                    model
                )
                
            # 计算输出tokens
            output_tokens = encoding.encode(response_content)
            logger.debug(f"输出 Tokens: {len(output_tokens)}")
            
            # 构造OpenAI格式的响应
            response = {
                "id": chat_id,
                "object": "chat.completion",
                "created": created_time,
                "model": model,
                "usage": {
                    "prompt_tokens": len(input_tokens),
                    "completion_tokens": len(output_tokens),
                    "total_tokens": len(input_tokens) + len(output_tokens),
                },
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": response_content,
                        },
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
            }
            
            return response
            
        except Exception as e:
            logger.error(f"处理非流式输出时发生错误: {e}")
            # 返回错误响应
            return {
                "id": chat_id,
                "object": "chat.completion",
                "created": created_time,
                "model": model,
                "error": str(e),
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"处理请求时发生错误: {str(e)}",
                        },
                        "index": 0,
                        "finish_reason": "error",
                    }
                ],
            }
