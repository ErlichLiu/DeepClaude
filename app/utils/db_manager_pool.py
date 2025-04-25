"""
使用连接池的数据库管理器实现
"""

import json
import logging
from typing import Dict, Any, Optional

from app.utils.db_pool import get_db_connection, close_db_pool,get_db_pool

# 设置日志
logger = logging.getLogger("db_manager_pool")

class DBManagerPool:
    """使用连接池的数据库管理器"""

    def __init__(self, db_path=None):
        """初始化数据库管理器

        Args:
            db_path: 数据库文件路径，默认为None，使用默认路径
        """
        # 数据库路径
        self.db_path = db_path

        # 初始化数据库表
        self._init_db()

    # 应用程序关闭时关闭连接池
    def close_db_manager(self):
        """关闭数据库连接池

        在应用程序关闭时调用，确保所有数据库连接被正确关闭
        """
        close_db_pool()

    def open_db_manager(self):
        """打开数据库连接池

        在应用程序启动时调用，确保所有数据库连接被正确打开
        """
        get_db_pool()

    def _init_system_settings(self, db):
        """初始化系统设置数据

        Args:
            db: 数据库连接
        """
        try:
            # 检查是否已有数据
            db.execute("SELECT COUNT(*) as count FROM system_settings")
            row = db.fetchone()
            if row and row["count"] > 0:
                logger.debug("系统设置数据已存在，跳过初始化")
                return

            # 默认系统设置
            default_settings = [
                # 日志级别
                ("log_level", "INFO", "str"),
                # 允许的源
                ("allow_origins", "[\"*\"]", "json"),
                # API密钥
                ("api_key", "123456", "str"),
                # 代理设置
                ("proxy_open", "false", "bool"),
                ("proxy_address", "127.0.0.1:7890", "str"),
                # 缓存大小
                ("model_cache_size", "5", "int"),
                # 保存deepseek token
                ("save_deepseek_tokens", "false", "bool"),
                ("save_deepseek_tokens_max_tokens", "5", "int"),
            ]

            # 插入默认设置
            for key, value, type_name in default_settings:
                db.execute("""
                INSERT OR IGNORE INTO system_settings (setting_key, setting_value, setting_type)
                VALUES (?, ?, ?)
                """, (key, value, type_name))

            logger.info("初始化了 %d 条系统设置数据",len(default_settings))
        except Exception as e:
            logger.error("初始化系统设置数据失败: %s", e)

    def _init_db(self):
        """初始化数据库，创建必要的表"""
        try:
            with get_db_connection() as db:
                # 创建供应商表
                db.execute('''
                CREATE TABLE IF NOT EXISTS providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_name TEXT NOT NULL UNIQUE,  -- 供应商名称，如 'openai', 'anthropic', 'deepseek' 等
                    api_key TEXT NOT NULL,               -- API密钥
                    api_base_url TEXT NOT NULL,          -- 基础URL
                    api_request_address TEXT NOT NULL,   -- 请求地址
                    provider_format TEXT NOT NULL,       -- 供应商格式，如 'openrouter', 'anthropic', 'oneapi' , 'deepseek' 等
                    is_valid INTEGER NOT NULL            -- 是否有效
                )
                ''')

                # 创建models表
                db.execute('''
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id INTEGER NOT NULL,  -- 对应的供应商ID
                    model_type TEXT NOT NULL,  -- 'reasoner' 或 'general'
                    model_id TEXT NOT NULL,
                    model_name TEXT NOT NULL UNIQUE,
                    model_format TEXT NOT NULL,          -- 模型格式，如 'openai', 'anthropic', 'reasoner' 等
                    is_valid INTEGER NOT NULL,
                    is_origin_reasoning INTEGER,  -- 仅对推理模型有意义
                    FOREIGN KEY (provider_id) REFERENCES providers(id)
                )
                ''')

                # 创建composite_models表
                db.execute('''
                CREATE TABLE IF NOT EXISTS composite_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL UNIQUE,
                    reasoner_model_id INTEGER NOT NULL,
                    general_model_id INTEGER NOT NULL,
                    is_valid INTEGER NOT NULL,
                    FOREIGN KEY (reasoner_model_id) REFERENCES models(id),
                    FOREIGN KEY (general_model_id) REFERENCES models(id)
                )
                ''')

                # 创建system_settings表
                db.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    setting_type TEXT NOT NULL  -- 用于指示值的类型（整数、布尔、字符串等）
                )
                ''')

                # 初始化系统设置数据
                self._init_system_settings(db)

                logger.info("数据库初始化成功")
        except Exception as e:
            logger.error("数据库初始化失败: %s", e)
            raise

    # ===== Providers 操作 =====

    def get_all_providers(self) -> Dict[str, Dict[str, Any]]:
        """获取所有供应商配置

        Returns:
            Dict[str, Dict[str, Any]]: 供应商配置字典，键为供应商名称
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, provider_name, api_base_url, api_request_address, provider_format, is_valid
                FROM providers
                """)
                rows = db.fetchall()

                result = {}
                for row in rows:
                    config = {
                        "id": row["id"],
                        "provider_name": row["provider_name"],
                        "api_key": row["api_key"],
                        "api_base_url": row["api_base_url"],
                        "api_request_address": row["api_request_address"],
                        "provider_format": row["provider_format"],
                        "is_valid": bool(row["is_valid"])
                    }
                    result[row["provider_name"]] = config

                return result
        except Exception as e:
            logger.error("获取供应商配置失败: %s", e)
            return {}

    def get_provider_for_name(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """获取指定供应商配置

        Args:
            provider_name: 供应商名称

        Returns:
            Optional[Dict[str, Any]]: 供应商配置，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, provider_name, api_key, api_base_url, api_request_address, provider_format, is_valid
                FROM providers
                WHERE provider_name = ?
                """, (provider_name,))

                row = db.fetchone()

                if row:
                    return {
                        "id": row["id"],
                        "provider_name": row["provider_name"],
                        "api_key": row["api_key"],
                        "api_base_url": row["api_base_url"],
                        "api_request_address": row["api_request_address"],
                        "provider_format": row["provider_format"],
                        "is_valid": bool(row["is_valid"])
                    }
                return None
        except Exception as e:
            logger.error("获取供应商配置失败: %s", e)
            return None

    def get_provider_for_id(self, provider_id: int) -> Optional[Dict[str, Any]]:
        """获取指定供应商配置

        Args:
            provider_id: 供应商ID

        Returns:
            Optional[Dict[str, Any]]: 供应商配置，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, provider_name, api_key, api_base_url, api_request_address, provider_format, is_valid
                FROM providers
                WHERE id = ?
                """, (provider_id,))

                row = db.fetchone()

                if row:
                    return {
                        "id": row["id"],
                        "provider_name": row["provider_name"],
                        "api_key": row["api_key"],
                        "api_base_url": row["api_base_url"],
                        "api_request_address": row["api_request_address"],
                        "provider_format": row["provider_format"],
                        "is_valid": bool(row["is_valid"])
                    }
                return None
        except Exception as e:
            logger.error("获取供应商配置失败: %s", e)
            return None


    def save_provider(self, config: Dict[str, Any]) -> bool:
        """保存供应商配置

        Args:
            config: 供应商配置，必须包含provider_name, api_key, api_base_url, api_request_address, provider_format

        Returns:
            bool: 是否保存成功
        """
        try:
            # 从配置中提取字段
            provider_id = config.get("id", None)
            provider_name = config.get("provider_name", "")
            api_key = config.get("api_key", "")
            api_base_url = config.get("api_base_url", "")
            api_request_address = config.get("api_request_address", "")
            provider_format = config.get("provider_format", "")
            is_valid = 1 if config.get("is_valid", True) else 0

            with get_db_connection() as db:
                if provider_id:
                    # 更新
                    db.execute("""
                    UPDATE providers SET
                        provider_name = ?,
                        api_key = ?,
                        api_base_url = ?,
                        api_request_address = ?,
                        provider_format = ?,
                        is_valid = ?
                    WHERE id = ?
                    """, (provider_name, api_key, api_base_url, api_request_address, provider_format, is_valid, provider_id))
                else:
                    # 插入
                    db.execute("""
                    INSERT INTO providers (
                        provider_name, api_key, api_base_url, api_request_address, provider_format, is_valid
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (provider_name, api_key, api_base_url, api_request_address, provider_format, is_valid))
                return True
        except Exception as e:
            logger.error("保存供应商配置失败: %s", e)
            return False

    def delete_provider(self, provider_id: int) -> bool:
        """删除供应商配置

        Args:
            provider_id: 供应商ID

        Returns:
            bool: 是否删除成功
        """
        try:
            with get_db_connection() as db:
                db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
                return True
        except Exception as e:
            logger.error("删除供应商配置失败: %s", e)
            return False

    # ===== Models 操作 =====

    def get_all_models(self, model_type=None) -> Dict[str, Dict[str, Any]]:
        """获取所有模型配置

        Args:
            model_type: 可选，模型类型过滤

        Returns:
            Dict[str, Dict[str, Any]]: 模型配置字典，键为模型名称
        """
        try:
            with get_db_connection() as db:
                # 基础SQL查询
                sql = """
                SELECT id, model_id, model_name, provider_id, is_origin_reasoning, is_valid, model_type, model_format
                FROM models
                """

                # 添加过滤条件
                params = []
                if model_type:
                    sql += " WHERE model_type = ?"
                    params.append(model_type)

                # 执行查询
                if params:
                    db.execute(sql, params)
                else:
                    db.execute(sql)

                rows = db.fetchall()

                # 处理结果
                result = {}
                for row in rows:
                    config = {
                        "id": row["id"],
                        "model_id": row["model_id"],
                        "model_name": row["model_name"],
                        "model_type": row["model_type"],
                        "model_format": row["model_format"],
                        "provider_id": row["provider_id"],
                        "is_valid": bool(row["is_valid"]),
                        "is_origin_reasoning": bool(row["is_origin_reasoning"])
                    }
                    result[row["model_name"]] = config

                return result
        except Exception as e:
            logger.error("获取模型配置失败: %s", e)
            return {}

    def get_model_for_name(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取指定模型配置

        Args:
            model_name: 模型名称

        Returns:
            Optional[Dict[str, Any]]: 模型配置，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, model_id, model_name, provider_id, is_origin_reasoning, is_valid, model_type, model_format
                FROM models
                WHERE
                is_valid = 1
                AND model_name = ?
                """, (model_name,))

                row = db.fetchone()

                if row:
                    return {
                        "id": row["id"],
                        "model_id": row["model_id"],
                        "model_name": row["model_name"],
                        "model_type": row["model_type"],
                        "model_format": row["model_format"],
                        "provider_id": row["provider_id"],
                        "is_origin_reasoning": bool(row["is_origin_reasoning"]),
                        "is_valid": bool(row["is_valid"])
                    }
                return None
        except Exception as e:
            logger.error("获取模型配置失败: %s", e)
            return None

    def get_model_for_id(self, models_id: str) -> Optional[Dict[str, Any]]:
        """获取指定模型配置

        Args:
            models_id: 模型ID

        Returns:
            Optional[Dict[str, Any]]: 模型配置，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, model_id, model_name, model_format, provider_id, is_origin_reasoning, is_valid, model_type
                FROM models
                WHERE
                is_valid = 1
                AND id = ?
                """, (models_id,))

                row = db.fetchone()

                if row:
                    return {
                        "id": row["id"],
                        "model_id": row["model_id"],
                        "model_name": row["model_name"],
                        "model_type": row["model_type"],
                        "model_format": row["model_format"],
                        "provider_id": row["provider_id"],
                        "is_origin_reasoning": bool(row["is_origin_reasoning"]),
                        "is_valid": bool(row["is_valid"])
                    }
                return None
        except Exception as e:
            logger.error("获取模型配置失败: %s", e)
            return None


    def save_model(self, config: Dict[str, Any]) -> bool:
        """保存模型配置

        Args:
            config: 模型配置

        Returns:
            bool: 是否保存成功
        """
        try:
            # 从配置中提取字段
            models_id = config.get("id", None)
            model_name = config.get("model_name", "")
            model_id = config.get("model_id", "")
            api_key = config.get("api_key", "")
            provider_id = config.get("provider_id", None)
            is_origin_reasoning = 1 if config.get("is_origin_reasoning", False) else 0
            is_valid = 1 if config.get("is_valid", False) else 0
            model_type = config.get("model_type", "")
            model_format = config.get("model_format", "")

            with get_db_connection() as db:
                if models_id:
                    # 更新
                    db.execute('''
                    UPDATE models SET
                        model_id = ?,
                        api_key = ?,
                        provider_id = ?,
                        is_origin_reasoning = ?,
                        is_valid = ?,
                        model_type = ?,
                        model_format = ?
                    WHERE id = ?
                    ''', (model_id, api_key, provider_id, is_origin_reasoning, is_valid, model_type, model_format, models_id))
                else:
                    # 插入
                    db.execute('''
                    INSERT INTO models (
                        model_name, model_id, api_key, provider_id, is_origin_reasoning, is_valid, model_type, model_format
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (model_name, model_id, api_key, provider_id, is_origin_reasoning, is_valid, model_type, model_format))

                return True
        except Exception as e:
            logger.error("保存模型配置失败: %s", e)
            return False

    def delete_model(self, models_id: int) -> bool:
        """删除模型配置

        Args:
            models_id: 模型ID

        Returns:
            bool: 是否删除成功
        """
        try:
            with get_db_connection() as db:
                db.execute("DELETE FROM models WHERE id = ?", (models_id,))
                return True
        except Exception as e:
            logger.error("删除模型配置失败: %s", e)
            return False

    # ===== Composite Models 操作 =====

    def get_all_composite_models(self) -> Dict[str, Dict[str, Any]]:
        """获取所有组合模型配置

        Returns:
            Dict[str, Dict[str, Any]]: 组合模型配置字典，键为模型名称
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, model_name, is_valid,
                       reasoner_model_id,
                       general_model_id
                FROM composite_models
                """)

                rows = db.fetchall()

                result = {}
                for row in rows:
                    config = {
                        "id": row["id"],
                        "model_name": row["model_name"],
                        "reasoner_model_id": row["reasoner_model_id"],
                        "general_model_id": row["general_model_id"],
                        "is_valid": bool(row["is_valid"])
                    }
                    result[row["model_name"]] = config

                return result
        except Exception as e:
            logger.error("获取组合模型配置失败: %s", e)
            return {}

    def get_composite_model(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取指定组合模型配置

        Args:
            model_name: 模型名称

        Returns:
            Optional[Dict[str, Any]]: 组合模型配置，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("""
                SELECT id, model_name, is_valid,
                       reasoner_model_id,
                       general_model_id
                FROM composite_models
                WHERE model_name = ? AND is_valid = 1
                """, (model_name,))

                row = db.fetchone()

                if row:
                    return {
                        "id": row["id"],
                        "model_name": row["model_name"],
                        "reasoner_model_id": row["reasoner_model_id"],
                        "general_model_id": row["general_model_id"],
                        "is_valid": bool(row["is_valid"])
                    }
                return None
        except Exception as e:
            logger.error("获取组合模型配置失败: %s", e)
            return None

    def save_composite_model(self, config: Dict[str, Any]) -> bool:
        """保存组合模型配置

        Args:
            config: 组合模型配置

        Returns:
            bool: 是否保存成功
        """
        try:
            # 从配置中提取字段
            composite_id = config.get("id", None)
            model_name = config.get("model_name", "")
            reasoner_model_id = config.get("reasoner_model_id", None)
            general_model_id = config.get("general_model_id", None)
            is_valid = 1 if config.get("is_valid", False) else 0

            with get_db_connection() as db:
                if composite_id:
                    # 更新
                    db.execute("""
                    UPDATE composite_models SET
                        reasoner_model_id = ?,
                        general_model_id = ?,
                        is_valid = ?
                    WHERE id = ?
                    """, (reasoner_model_id, general_model_id, is_valid, composite_id))
                else:
                    # 插入
                    db.execute("""
                    INSERT INTO composite_models (
                        model_name, reasoner_model_id, general_model_id, is_valid
                    ) VALUES (?, ?, ?, ?)
                    """, (model_name, reasoner_model_id, general_model_id, is_valid))

                return True
        except Exception as e:
            logger.error("保存组合模型配置失败: %s", e)
            return False

    def delete_composite_model(self, composite_id: int) -> bool:
        """删除组合模型配置

        Args:
            composite_id: 组合模型ID

        Returns:
            bool: 是否删除成功
        """
        try:
            with get_db_connection() as db:
                db.execute("DELETE FROM composite_models WHERE id = ?", (composite_id,))
                return True
        except Exception as e:
            logger.error("删除组合模型配置失败: %s", e)
            return False

    # ===== 系统设置操作 =====

    def get_setting(self, key: str) -> Optional[Any]:
        """获取系统设置

        Args:
            key: 设置键名

        Returns:
            Optional[Any]: 设置值，如果不存在则返回None
        """
        try:
            with get_db_connection() as db:
                db.execute("SELECT setting_value, setting_type FROM system_settings WHERE setting_key = ?", (key,))
                row = db.fetchone()

                if row:
                    value = row["setting_value"]
                    type_name = row["setting_type"]

                    # 根据类型转换值
                    if type_name == "int":
                        return int(value)
                    elif type_name == "float":
                        return float(value)
                    elif type_name == "bool":
                        return value.lower() in ("true", "1", "yes")
                    elif type_name == "json":
                        return json.loads(value)
                    else:
                        return value

                return None
        except Exception as e:
            logger.error("获取系统设置失败: %s", e)
            return None

    def get_all_settings(self) -> Dict[str, Any]:
        """获取所有系统设置

        Returns:
            Dict[str, Any]: 系统设置字典
        """
        try:
            with get_db_connection() as db:
                db.execute("SELECT setting_key, setting_value, setting_type FROM system_settings")
                rows = db.fetchall()

                result = {}
                for row in rows:
                    key = row["setting_key"]
                    value = row["setting_value"]
                    type_name = row["setting_type"]

                    # 根据类型转换值
                    if type_name == "int":
                        result[key] = int(value)
                    elif type_name == "float":
                        result[key] = float(value)
                    elif type_name == "bool":
                        result[key] = value.lower() in ("true", "1", "yes")
                    elif type_name == "json":
                        result[key] = json.loads(value)
                    else:
                        result[key] = value

                return result
        except Exception as e:
            logger.error("获取所有系统设置失败: %s", e)
            return {}

    def save_setting(self, key: str, value: Any) -> bool:
        """保存系统设置

        Args:
            key: 设置键名
            value: 设置值

        Returns:
            bool: 是否保存成功
        """
        try:
            # 确定值的类型
            if isinstance(value, int):
                type_name = "int"
                str_value = str(value)
            elif isinstance(value, float):
                type_name = "float"
                str_value = str(value)
            elif isinstance(value, bool):
                type_name = "bool"
                str_value = "true" if value else "false"
            elif isinstance(value, (dict, list)):
                type_name = "json"
                str_value = json.dumps(value, ensure_ascii=False)
            else:
                type_name = "str"
                str_value = str(value)

            with get_db_connection() as db:
                # 检查是否已存在
                db.execute("SELECT 1 FROM system_settings WHERE setting_key = ?", (key,))
                exists = db.fetchone() is not None

                if exists:
                    # 更新
                    db.execute("""
                    UPDATE system_settings SET
                        setting_value = ?,
                        setting_type = ?
                    WHERE setting_key = ?
                    """, (str_value, type_name, key))
                else:
                    # 插入
                    db.execute("""
                    INSERT INTO system_settings (
                        setting_key, setting_value, setting_type
                    ) VALUES (?, ?, ?)
                    """, (key, str_value, type_name))

                return True
        except Exception as e:
            logger.error("保存系统设置失败: %s", e)
            return False

    def delete_setting(self, key: str) -> bool:
        """删除系统设置

        Args:
            key: 设置键名

        Returns:
            bool: 是否删除成功
        """
        try:
            with get_db_connection() as db:
                db.execute("DELETE FROM system_settings WHERE setting_key = ?", (key,))
                return True
        except Exception as e:
            logger.error("删除系统设置失败: %s", e)
            return False

    # ===== 配置导入导出 =====

    def export_config(self) -> Dict[str, Any]:
        """导出所有配置

        Returns:
            Dict[str, Any]: 配置字典
        """
        try:
            result = {
                "providers": self.get_all_providers(),
                "models": self.get_all_models(),
                "composite_models": self.get_all_composite_models(),
                "system": self.get_all_settings()
            }
            return result
        except Exception as e:
            logger.error("导出配置失败: %s", e)
            return {}

    def import_config(self, config: Dict[str, Any]) -> bool:
        """导入配置

        Args:
            config: 配置字典

        Returns:
            bool: 是否导入成功
        """
        try:
            with get_db_connection() as db:
                # 清空现有数据
                db.execute("DELETE FROM providers")
                db.execute("DELETE FROM models")
                db.execute("DELETE FROM composite_models")
                db.execute("DELETE FROM system_settings")

                # 导入供应商
                for provider_config in config.get("providers", {}).values():
                    self.save_provider(provider_config)

                # 导入模型
                for model_config in config.get("models", {}).values():
                    self.save_model(model_config)

                # 导入组合模型
                for composite_config in config.get("composite_models", {}).values():
                    self.save_composite_model(composite_config)

                # 导入系统设置
                for key, value in config.get("system", {}).items():
                    self.save_setting(key, value)

                return True
        except Exception as e:
            logger.error("导入配置失败: %s", e)
            return False
