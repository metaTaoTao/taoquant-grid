"""
配置模块

包含:
- schema: 配置数据结构
- loader: 配置加载
- validator: 配置校验
"""

from src.config.schema import GridStrategyConfig
from src.config.loader import load_config
from src.config.validator import ConfigValidator, ConfigValidationError

__all__ = [
    "GridStrategyConfig",
    "load_config",
    "ConfigValidator",
    "ConfigValidationError",
]

