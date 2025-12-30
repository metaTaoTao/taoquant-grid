"""
网格引擎模块

包含:
- grid_builder: 网格生成
- active_window: 活跃窗口
- spacing: 间距管理
"""

from src.grid_engine.grid_builder import (
    GridEngine,
    SpacingConfig,
    ActiveWindowConfig,
    EdgeDecayConfig,
)

__all__ = [
    "GridEngine",
    "SpacingConfig",
    "ActiveWindowConfig",
    "EdgeDecayConfig",
]

