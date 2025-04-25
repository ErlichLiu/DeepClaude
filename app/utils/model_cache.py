"""
模型实例缓存管理器，使用LRU策略管理模型实例
"""

from collections import OrderedDict
import logging

# 设置日志
logger = logging.getLogger("model_cache")

class ModelInstanceCache:
    """模型实例缓存管理器，使用LRU策略"""

    def __init__(self, max_size=5):
        """初始化缓存管理器

        Args:
            max_size: 最大缓存实例数量
        """
        self.max_size = max_size
        self.instances = OrderedDict()  # 有序字典，保持访问顺序
        logger.info("初始化模型实例缓存管理器，最大缓存数量: %d", max_size)

    def get(self, model_key):
        """获取模型实例

        Args:
            model_key: 模型唯一标识，如 "deepclaude", "deepgeminipro" 等

        Returns:
            模型实例，如果不存在则返回None
        """
        if model_key in self.instances:
            # 将访问的实例移到末尾（最新使用）
            instance = self.instances.pop(model_key)
            self.instances[model_key] = instance
            logger.debug("从缓存获取模型实例: %s", model_key)
            return instance
        logger.debug("缓存中不存在模型实例: %s", model_key)
        return None

    def put(self, model_key, instance):
        """添加或更新模型实例

        Args:
            model_key: 模型唯一标识
            instance: 模型实例

        Returns:
            None
        """
        # 如果已存在，先移除（会在后面重新添加到末尾）
        if model_key in self.instances:
            self.instances.pop(model_key)
            logger.debug("更新缓存中的模型实例: %s", model_key)

        # 如果达到最大容量，移除最久未使用的实例（第一个）
        if len(self.instances) >= self.max_size:
            oldest_key, _ = self.instances.popitem(last=False)  # last=False表示移除第一个元素
            logger.info("缓存已满，移除最久未使用的模型实例: %s", oldest_key)

        # 添加新实例到末尾
        self.instances[model_key] = instance
        logger.debug("添加模型实例到缓存: %s", model_key)

    def remove(self, model_key):
        """移除指定的模型实例

        Args:
            model_key: 模型唯一标识

        Returns:
            bool: 是否成功移除
        """
        if model_key in self.instances:
            self.instances.pop(model_key)
            logger.info("从缓存中移除模型实例: %s", model_key)
            return True
        logger.debug("尝试移除不存在的模型实例: %s", model_key)
        return False

    def clear(self):
        """清空所有缓存的实例"""
        count = len(self.instances)
        self.instances.clear()
        logger.info("清空缓存，移除 %d 个模型实例", count)

    def get_all_keys(self):
        """获取所有缓存的模型键名"""
        return list(self.instances.keys())

    def __len__(self):
        """返回缓存中的实例数量"""
        return len(self.instances)
