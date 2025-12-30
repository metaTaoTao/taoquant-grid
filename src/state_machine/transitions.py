"""
状态迁移触发器

定义状态迁移的触发条件
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from src.models.state import StrategyState


class TransitionTrigger(Enum):
    """状态迁移触发器类型"""
    # NORMAL → DEFENSIVE
    PRICE_BOUNDARY = auto()        # 价格触边
    INV_WARN = auto()              # 库存预警
    VOL_SPIKE = auto()             # 波动率冲击
    
    # DEFENSIVE → DAMAGE_CONTROL
    INV_DAMAGE = auto()            # 库存危险
    STRUCTURAL_BREAK = auto()      # 结构性破位
    RISK_BUDGET_STOP = auto()      # 风险预算止损
    
    # 任意 → EMERGENCY_STOP
    LIQUIDITY_GAP = auto()         # 流动性缺口
    LIQ_DISTANCE = auto()          # 强平距离
    API_FAULT = auto()             # API 故障
    DATA_STALE = auto()            # 数据过期
    
    # 恢复
    CONDITIONS_RECOVERED = auto()  # 条件恢复
    MANUAL_RESET = auto()          # 人工重置


@dataclass
class TransitionResult:
    """状态迁移结果"""
    triggered: bool
    target_state: Optional[StrategyState]
    trigger: Optional[TransitionTrigger]
    reason: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    
    @classmethod
    def no_transition(cls) -> "TransitionResult":
        """不需要迁移"""
        return cls(
            triggered=False,
            target_state=None,
            trigger=None,
            reason="",
        )
    
    @classmethod
    def to_defensive(
        cls,
        trigger: TransitionTrigger,
        reason: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> "TransitionResult":
        """迁移到 DEFENSIVE"""
        return cls(
            triggered=True,
            target_state=StrategyState.DEFENSIVE,
            trigger=trigger,
            reason=reason,
            value=value,
            threshold=threshold,
        )
    
    @classmethod
    def to_damage_control(
        cls,
        trigger: TransitionTrigger,
        reason: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> "TransitionResult":
        """迁移到 DAMAGE_CONTROL"""
        return cls(
            triggered=True,
            target_state=StrategyState.DAMAGE_CONTROL,
            trigger=trigger,
            reason=reason,
            value=value,
            threshold=threshold,
        )
    
    @classmethod
    def to_emergency_stop(
        cls,
        trigger: TransitionTrigger,
        reason: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> "TransitionResult":
        """迁移到 EMERGENCY_STOP"""
        return cls(
            triggered=True,
            target_state=StrategyState.EMERGENCY_STOP,
            trigger=trigger,
            reason=reason,
            value=value,
            threshold=threshold,
        )
    
    @classmethod
    def to_normal(
        cls,
        trigger: TransitionTrigger,
        reason: str,
    ) -> "TransitionResult":
        """迁移到 NORMAL"""
        return cls(
            triggered=True,
            target_state=StrategyState.NORMAL,
            trigger=trigger,
            reason=reason,
        )

