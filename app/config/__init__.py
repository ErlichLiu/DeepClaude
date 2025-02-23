"""配置模块"""

import os
from pathlib import Path
from typing import Dict, List, Any

import yaml

def load_models_config() -> Dict[str, List[Dict[str, Any]]]:
    """加载模型配置

    Returns:
        Dict[str, List[Dict[str, Any]]]: 模型配置字典
    """
    config_path = Path(__file__).parent / "models.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
