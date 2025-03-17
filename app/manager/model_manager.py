"""模型管理器，负责处理模型选择、参数验证和请求处理"""

import os
import json
from typing import Dict, Any, Tuple, List, AsyncGenerator, Optional

from fastapi.responses import StreamingResponse

from app.deepclaude.deepclaude import DeepClaude
from app.openai_composite import OpenAICompatibleComposite
from app.utils.logger import logger


class ModelManager:
    """模型管理器，负责创建和管理模型实例，处理请求参数"""

    def __init__(self):
        """初始化模型管理器"""
        # 配置文件路径
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model_manager", "model_configs.json")
        # 加载模型配置
        self.config = self._load_config()
        # 模型实例缓存
        self.model_instances = {}
        # 是否原生支持推理字段
        self.is_origin_reasoning = os.getenv("IS_ORIGIN_REASONING", "True").lower() == "true"

    def _load_config(self) -> Dict[str, Any]:
        """加载模型配置文件

        Returns:
            Dict[str, Any]: 配置信息
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"成功加载模型配置，包含 {len(config.get('composite_models', {}))} 个组合模型")
            return config
        except Exception as e:
            logger.error(f"加载模型配置失败: {e}")
            # 返回空配置
            return {"reasoner_models": {}, "target_models": {}, "composite_models": {}, "proxy": {"proxy_open": False}}

    def get_composite_model_config(self, model_name: str) -> Dict[str, Any]:
        """获取组合模型配置

        Args:
            model_name: 模型名称

        Returns:
            Dict[str, Any]: 组合模型配置

        Raises:
            ValueError: 模型不存在或无效
        """
        composite_models = self.config.get("composite_models", {})
        if model_name not in composite_models:
            raise ValueError(f"模型 '{model_name}' 不存在")

        model_config = composite_models[model_name]
        if not model_config.get("is_valid", False):
            raise ValueError(f"模型 '{model_name}' 当前不可用")

        return model_config

    def get_model_details(self, model_name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """获取模型详细配置

        Args:
            model_name: 模型名称

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: (推理模型配置, 目标模型配置)

        Raises:
            ValueError: 模型不存在或无效
        """
        # 获取组合模型配置
        composite_config = self.get_composite_model_config(model_name)
        
        # 获取推理模型配置
        reasoner_model_name = composite_config.get("reasoner_models")
        reasoner_models = self.config.get("reasoner_models", {})
        if reasoner_model_name not in reasoner_models:
            raise ValueError(f"推理模型 '{reasoner_model_name}' 不存在")
        
        reasoner_config = reasoner_models[reasoner_model_name]
        if not reasoner_config.get("is_valid", False):
            raise ValueError(f"推理模型 '{reasoner_model_name}' 当前不可用")
        
        # 获取目标模型配置
        target_model_name = composite_config.get("target_models")
        target_models = self.config.get("target_models", {})
        if target_model_name not in target_models:
            raise ValueError(f"目标模型 '{target_model_name}' 不存在")
        
        target_config = target_models[target_model_name]
        if not target_config.get("is_valid", False):
            raise ValueError(f"目标模型 '{target_model_name}' 当前不可用")
        
        return reasoner_config, target_config

    def _get_model_instance(self, model_name: str) -> Any:
        """获取或创建模型实例

        Args:
            model_name: 模型名称

        Returns:
            Any: 模型实例

        Raises:
            ValueError: 模型不存在或无效
        """
        # 如果已经有缓存的实例，直接返回
        if model_name in self.model_instances:
            return self.model_instances[model_name]
        
        # 获取模型详细配置
        reasoner_config, target_config = self.get_model_details(model_name)
        
        # 获取代理配置
        proxy_config = self.config.get("proxy", {})
        proxy = None
        if proxy_config.get("proxy_open", False):
            proxy = proxy_config.get("proxy_address")
            logger.info(f"模型 {model_name} 将使用代理: {proxy}")
        
        # 创建模型实例
        if target_config.get("model_format", "") == "anthropic":
            # 创建 DeepClaude 实例
            instance = DeepClaude(
                deepseek_api_key=reasoner_config["api_key"],
                claude_api_key=target_config["api_key"],
                deepseek_api_url=f"{reasoner_config['api_base_url']}/{reasoner_config['api_request_address']}",
                claude_api_url=f"{target_config['api_base_url']}/{target_config['api_request_address']}",
                claude_provider="anthropic",
                is_origin_reasoning=reasoner_config.get("is_origin_reasoning", self.is_origin_reasoning),
                proxy=proxy,
            )
        else:
            # 创建 OpenAICompatibleComposite 实例
            instance = OpenAICompatibleComposite(
                deepseek_api_key=reasoner_config["api_key"],
                openai_api_key=target_config["api_key"],
                deepseek_api_url=f"{reasoner_config['api_base_url']}/{reasoner_config['api_request_address']}",
                openai_api_url=f"{target_config['api_base_url']}/{target_config['api_request_address']}",
                is_origin_reasoning=reasoner_config.get("is_origin_reasoning", self.is_origin_reasoning),
                proxy=proxy,
            )
        
        # 缓存实例
        self.model_instances[model_name] = instance
        return instance

    def validate_and_prepare_params(self, body: Dict[str, Any]) -> Tuple[List[Dict[str, str]], str, Tuple[float, float, float, float, bool]]:
        """验证和准备请求参数

        Args:
            body: 请求体

        Returns:
            Tuple[List[Dict[str, str]], str, Tuple[float, float, float, float, bool]]: 
                (消息列表, 模型名称, (temperature, top_p, presence_penalty, frequency_penalty, stream))

        Raises:
            ValueError: 参数验证失败时抛出
        """
        # 获取基础信息
        messages = body.get("messages")
        model = body.get("model")

        if not model:
            raise ValueError("必须指定模型名称")

        if not messages:
            raise ValueError("消息列表不能为空")

        # 验证并提取参数
        temperature: float = body.get("temperature", 0.5)
        top_p: float = body.get("top_p", 0.9)
        presence_penalty: float = body.get("presence_penalty", 0.0)
        frequency_penalty: float = body.get("frequency_penalty", 0.0)
        stream: bool = body.get("stream", False)

        # 模型特定验证
        if "sonnet" in model:  # Sonnet 模型温度必须在 0 到 1 之间
            if not isinstance(temperature, (float, int)) or temperature < 0.0 or temperature > 1.0:
                raise ValueError("Sonnet 设定 temperature 必须在 0 到 1 之间")

        return messages, model, (temperature, top_p, presence_penalty, frequency_penalty, stream)

    def get_model_list(self) -> List[Dict[str, Any]]:
        """获取可用模型列表

        Returns:
            List[Dict[str, Any]]: 模型列表
        """
        models = []
        for model_id, config in self.config.get("composite_models", {}).items():
            if config.get("is_valid", False):
                models.append({
                    "id": model_id,
                    "object": "model",
                    "created": 1740268800,
                    "owned_by": "deepclaude",
                    "permission": {
                        "id": "modelperm-{}".format(model_id),
                        "object": "model_permission",
                        "created": 1740268800,
                        "allow_create_engine": False,
                        "allow_sampling": True,
                        "allow_logprobs": True,
                        "allow_search_indices": False,
                        "allow_view": True,
                        "allow_fine_tuning": False,
                        "organization": "*",
                        "group": None,
                        "is_blocking": False
                    },
                    "root": "deepclaude",
                    "parent": None
                })
        return models

    async def process_request(self, body: Dict[str, Any]) -> Any:
        """处理聊天完成请求

        Args:
            body: 请求体

        Returns:
            Any: 响应对象，可能是 StreamingResponse 或 Dict

        Raises:
            ValueError: 参数验证或处理失败时抛出
        """
        # 验证和准备参数
        messages, model, model_args = self.validate_and_prepare_params(body)
        temperature, top_p, presence_penalty, frequency_penalty, stream = model_args

        # 模型参数，不包含 stream
        model_params = (temperature, top_p, presence_penalty, frequency_penalty)

        # 获取模型详细配置
        reasoner_config, target_config = self.get_model_details(model)

        # 获取模型实例
        model_instance = self._get_model_instance(model)

        # 处理请求
        if target_config.get("model_format", "") == "anthropic":
            # 使用 DeepClaude
            if stream:
                return StreamingResponse(
                    model_instance.chat_completions_with_stream(
                        messages=messages,
                        model_arg=model_params,
                        deepseek_model=reasoner_config["model_id"],
                        claude_model=target_config["model_id"],
                    ),
                    media_type="text/event-stream",
                )
            else:
                return await model_instance.chat_completions_without_stream(
                    messages=messages,
                    model_arg=model_params,
                    deepseek_model=reasoner_config["model_id"],
                    claude_model=target_config["model_id"],
                )
        else:
            # 使用 OpenAI 兼容组合模型
            if stream:
                return StreamingResponse(
                    model_instance.chat_completions_with_stream(
                        messages=messages,
                        model_arg=model_params,
                        deepseek_model=reasoner_config["model_id"],
                        target_model=target_config["model_id"],
                    ),
                    media_type="text/event-stream",
                )
            else:
                return await model_instance.chat_completions_without_stream(
                    messages=messages,
                    model_arg=model_params,
                    deepseek_model=reasoner_config["model_id"],
                    target_model=target_config["model_id"],
                )


    def get_config(self) -> Dict[str, Any]:
        """获取当前配置
        
        Returns:
            Dict[str, Any]: 当前配置
        """
        # 每次都从文件重新加载最新配置
        self.config = self._load_config()
        return self.config

    def update_config(self, config: Dict[str, Any]) -> None:
        """更新配置
        
        Args:
            config: 新配置
            
        Raises:
            ValueError: 配置无效
        """
        # 验证配置
        if not isinstance(config, dict):
            raise ValueError("配置必须是字典")
        
        # 更新配置
        self.config = config
        
        # 清空模型实例缓存，以便重新创建
        self.model_instances = {}
        
        # 保存配置到文件
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

# 创建全局 ModelManager 实例
model_manager = ModelManager()