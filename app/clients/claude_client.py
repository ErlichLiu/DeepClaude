"""Claude API 客户端"""
import json
from typing import AsyncGenerator
from app.utils.logger import logger
from .base_client import BaseClient


class ClaudeClient(BaseClient):
    def __init__(self, api_key: str, api_url: str = "https://api.anthropic.com/v1/messages", provider: str = "anthropic"):
        """初始化 Claude 客户端
        
        Args:
            api_key: Claude API密钥
            api_url: Claude API地址
            is_openrouter: 是否使用 OpenRouter API
        """
        super().__init__(api_key, api_url)
        self.provider = provider

    async def stream_chat(
        self,
        messages: list,
        model_arg: tuple[float, float, float, float],
        model: str,
        stream: bool = True
    ) -> AsyncGenerator[tuple[str, str], None]:
        """流式或非流式对话
        
        Args:
            messages: 消息列表
            model_arg: 模型参数元组[temperature, top_p, presence_penalty, frequency_penalty]
            model: 模型名称。如果是 OpenRouter, 会自动转换为 'anthropic/claude-3.5-sonnet' 格式
            stream: 是否使用流式输出，默认为 True
            
        Yields:
            tuple[str, str]: (内容类型, 内容)
                内容类型: "answer"
                内容: 实际的文本内容
        """

        if self.provider == "openrouter":
            # 转换模型名称为 OpenRouter 格式
            model = "anthropic/claude-3.5-sonnet"
                
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/ErlichLiu/DeepClaude",  # OpenRouter 需要
                "X-Title": "DeepClaude"  # OpenRouter 需要
            }

            data = {
                "model": model,  # OpenRouter 使用 anthropic/claude-3.5-sonnet 格式
                "messages": messages,
                "stream": stream,
                "temperature": 1 if model_arg[0] < 0 or model_arg[0] > 1 else model_arg[0],
                "top_p": model_arg[1],
                "presence_penalty": model_arg[2],
                "frequency_penalty": model_arg[3]
            }
        elif self.provider == "oneapi":
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": model,
                "messages": messages,
                "stream": stream,
                "temperature": 1 if model_arg[0] < 0 or model_arg[0] > 1 else model_arg[0],
                "top_p": model_arg[1],
                "presence_penalty": model_arg[2],
                "frequency_penalty": model_arg[3]
            }
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
                "temperature": 1 if model_arg[0] < 0 or model_arg[0] > 1 else model_arg[0], # Claude仅支持temperature与top_p
                "top_p": model_arg[1]
            }
        else:
            raise ValueError(f"不支持的Claude Provider: {self.provider}")

        logger.debug(f"开始对话：{data}")

        if stream:
            async for chunk in self._make_request(headers, data):
                chunk_str = chunk.decode('utf-8')
                if not chunk_str.strip():
                    continue
                    
                for line in chunk_str.split('\n'):
                    if line.startswith('data: '):
                        json_str = line[6:]  # 去掉 'data: ' 前缀
                        if json_str.strip() == '[DONE]':
                            return
                            
                        try:
                            data = json.loads(json_str)
                            if self.provider in ("openrouter", "oneapi"):
                                # OpenRouter/OneApi 格式
                                content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                if content:
                                    yield "answer", content
                            elif self.provider == "anthropic":
                                # Anthropic 格式
                                if data.get('type') == 'content_block_delta':
                                    content = data.get('delta', {}).get('text', '')
                                    if content:
                                        yield "answer", content
                            else:
                                raise ValueError(f"不支持的Claude Provider: {self.provider}")
                        except json.JSONDecodeError:
                            continue
        else:
            # 非流式输出
            async for chunk in self._make_request(headers, data):
                try:
                    response = json.loads(chunk.decode('utf-8'))
                    if self.provider in ("openrouter", "oneapi"):
                        content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                        if content:
                            yield "answer", content
                    elif self.provider == "anthropic":
                        content = response.get('content', [{}])[0].get('text', '')
                        if content:
                            yield "answer", content
                    else:
                        raise ValueError(f"不支持的Claude Provider: {self.provider}")
                except json.JSONDecodeError:
                    continue
