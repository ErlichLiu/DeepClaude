"""模型管理器，负责处理模型选择、参数验证和请求处理"""

import json
from typing import Dict, Any, Tuple, List, Optional

from fastapi.responses import StreamingResponse

from app.deepclaude.deepclaude import DeepClaude
from app.openai_composite import OpenAICompatibleComposite
from app.utils.logger import logger
from app.utils.model_cache import ModelInstanceCache
from app.utils.db_manager_pool import DBManagerPool
from app.clients.claude_client import ClaudeClient
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.clients.deepseek_client import DeepSeekClient


class ModelManager:
    """模型管理器，负责创建和管理模型实例，处理请求参数"""

    def __init__(self, db_manager: DBManagerPool):
        """初始化模型管理器"""
        self.db_manager = db_manager
        # 获取系统配置信息
        self.config = self.get_system_config()
        # 模型实例缓存，使用LRU策略管理，最多保存5个实例
        self.model_cache = ModelInstanceCache(max_size=5)

    def get_system_config(self) -> Dict[str, Any]:
        """获取系统配置信息

        Returns:
            Dict[str, Any]: 系统配置信息
        """
        return self.db_manager.get_all_settings()

    def get_model_details(self, model_name: str, model_type: str) -> Tuple[Dict[str, Any], str]:
        """获取模型详细配置

        Args:
            model_name: 模型名称
            model_type: 模型类型

        Returns:
            Tuple[Dict[str, Any], str]: (推理模型配置, 模型类型)

        Raises:
            ValueError: 模型不存在或无效
        """

        if model_type in ("reasoner", "general"):
            model=self.db_manager.get_model_for_name(model_name)
            if not model:
                raise ValueError(f"模型 '{model_name}' 不存在")
            return model,model.get("model_type")

        if model_type == "composite":
            model = self.db_manager.get_composite_model(model_name)
            if not model:
                raise ValueError(f"组合模型 '{model_name}' 不存在")
            return model, "composite"

        model=self.db_manager.get_model_for_name(model_name)
        if not model:
            model = self.db_manager.get_composite_model(model_name)
            if not model:
                raise ValueError(f"模型 '{model_name}' 不存在")
            return model, "composite"
        return model, model.get("model_type")

    def validate_and_prepare_params(self, body: Dict[str, Any]) -> Tuple[List[Dict[str, str]], str, str, Dict[str, Optional[float]], bool]:
        """验证和准备请求参数

        Args:
            body: 请求体

        Returns:
            Tuple[List[Dict[str, str]], str, str, Dict[str, Optional[float]], bool]:
                (消息列表, 模型名称, 模型类型, 模型参数, 流式输出)

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
        model_args = {
            "temperature": body.get("temperature", None),
            "top_p": body.get("top_p", None),
            "presence_penalty": body.get("presence_penalty", None),
            "frequency_penalty": body.get("frequency_penalty", None),
        }
        stream = body.get("stream", False)
        model_type: str = body.get("model_type", "")

        # 模型特定验证
        if "sonnet" in model:  # Sonnet 模型温度必须在 0 到 1 之间
            if not isinstance(model_args["temperature"], (float, int)) or model_args["temperature"] < 0.0 or model_args["temperature"] > 1.0:
                raise ValueError("Sonnet 设定 temperature 必须在 0 到 1 之间")

        return messages, model, model_type, model_args, stream

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

    def composite_model(self, model_details: Dict[str, Any]) -> Any:
        """获取组合模型实例

        Args:
            model_details: 组合模型配置

        Returns:
            Any: 组合模型实例
        """
        # 获取组合模型配置
        reasoner_model_id = model_details.get("reasoner_model_id")
        general_model_id = model_details.get("general_model_id")

        reasoner_model = self.db_manager.get_model_for_id(reasoner_model_id)
        general_model = self.db_manager.get_model_for_id(general_model_id)

        # 获取reasoner实例
        reasoner_provider_id = reasoner_model.get("provider_id")
        reasoner_model_format = reasoner_model.get("model_format")
        reasoner_instance_id = str(reasoner_provider_id) + "-" + reasoner_model_format
        reasoner_instance = self.model_cache.get(reasoner_instance_id)
        if not reasoner_instance:
            reasoner_instance = self.create_instance(reasoner_provider_id, reasoner_model_format)

        # 获取general实例
        general_provider_id = general_model.get("provider_id")
        general_model_format = general_model.get("model_format")
        general_instance_id = str(general_provider_id) + "-" + general_model_format
        general_instance = self.model_cache.get(general_instance_id)
        if not general_instance:
            general_instance = self.create_instance(general_provider_id, general_model_format)

        if reasoner_model_format == "reasoner" and general_model_format == "anthropic":
            return DeepClaude(reasoner_instance, general_instance, reasoner_model.get("is_origin_reasoning", True))

        if reasoner_model_format == "reasoner" and general_model_format == "openai":
            return OpenAICompatibleComposite(reasoner_instance, general_instance, reasoner_model.get("is_origin_reasoning", True))

        raise ValueError(f"不支持的组合模型格式: {reasoner_model_format} + {general_model_format}")

    def create_instance(self, provider_id: int, model_format: str):
        """创建模型实例

        Args:
            provider_id: 供应商ID
            model_format: 模型格式

        Returns:
            Any: 模型实例
        """

        instance_id = str(provider_id) + "-" + model_format
        provider = self.db_manager.get_provider_for_id(provider_id)
        if model_format == "openai":
            instance = OpenAICompatibleClient(
                api_key=provider["api_key"],
                api_url=provider["api_url"],
                timeout = None,
                proxy= self.config.get("proxy_address") if self.config.get("proxy_open").bool() else None,
            )
            self.model_cache.put(instance_id, instance)
            return instance
        elif model_format == "anthropic":
            instance = ClaudeClient(
                api_key=provider["api_key"],
                api_url=provider["api_url"],
                provider=model_format,
                proxy= self.config.get("proxy_address") if self.config.get("proxy_open").bool() else None,
            )
            self.model_cache.put(instance_id, instance)
            return instance
        elif model_format == "reasoner":
            instance = DeepSeekClient(
                api_key=provider["api_key"],
                api_url=provider["api_url"],
                proxy= self.config.get("proxy_address") if self.config.get("proxy_open").bool() else None,
            )
            self.model_cache.put(instance_id, instance)
            return instance
        else:
            raise ValueError(f"不支持的供应商格式: {model_format}")


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
        messages, model, model_type, model_args, stream = self.validate_and_prepare_params(body)

        # 获取模型详细配置
        model_details, model_type = self.get_model_details(model, model_type)



        # 获取模型实例
        model_instance = self._get_model_instance(model)

        # 处理请求
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
        self.model_cache.clear()
        logger.info("配置已更新，模型实例缓存已清空")

        # 保存配置到文件
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)