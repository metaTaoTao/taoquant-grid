"""
优势识别引擎模块

包含:
- gate: 优势门控接口
- opportunity_window: 机会窗口评估
- core_zone: 核心区域计算
"""

from src.advantage_engine.gate import AdvantageGateStub, AdvantageGateFull
from src.advantage_engine.opportunity_window import (
    OpportunityWindow,
    CycleActivityMetrics,
    InventoryReversionMetrics,
    BreakevenSlopeMetrics,
)
from src.advantage_engine.core_zone import CoreZoneCalculator, FillDensityCalculator

__all__ = [
    "AdvantageGateStub",
    "AdvantageGateFull",
    "OpportunityWindow",
    "CycleActivityMetrics",
    "InventoryReversionMetrics",
    "BreakevenSlopeMetrics",
    "CoreZoneCalculator",
    "FillDensityCalculator",
]

