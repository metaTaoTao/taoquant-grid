"""
策略状态与权限矩阵

四态状态机：
- NORMAL: 正常卖波动状态
- DEFENSIVE: 防御状态
- DAMAGE_CONTROL: 风险处置状态
- EMERGENCY_STOP: 紧急停止
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Set


class StrategyState(Enum):
    """
    策略运行状态枚举
    
    状态迁移规则：
    - NORMAL → DEFENSIVE: 价格触边 / inv_warn / vol_spike
    - DEFENSIVE → DAMAGE_CONTROL: inv_damage / structural_break / risk_budget_stop
    - 任意 → EMERGENCY_STOP: liquidity_gap / liq_distance / api_fault
    - DEFENSIVE/DAMAGE_CONTROL → NORMAL: 所有条件恢复
    """
    NORMAL = auto()
    DEFENSIVE = auto()
    DAMAGE_CONTROL = auto()
    EMERGENCY_STOP = auto()


class OrderMode(Enum):
    """
    订单模式枚举
    
    与状态机绑定，决定允许的订单行为
    """
    FULL = auto()              # 允许所有订单
    NO_NEW_BUYS = auto()       # 禁止新增 buy
    REDUCE_ONLY = auto()       # 只允许 reduce-only
    KILL_SWITCH = auto()       # 停止所有订单


@dataclass(frozen=True)
class StatePermissions:
    """
    状态权限矩阵
    
    定义每个状态下允许的行为
    """
    allow_new_buy: bool        # 允许新增 buy
    allow_refill_buy: bool     # 允许补 buy
    allow_sell: bool           # 允许 sell
    allow_reduce_only: bool    # 允许 reduce-only
    allow_reanchor: bool       # 允许 re-anchor
    order_mode: OrderMode      # 订单模式
    
    @property
    def can_increase_inventory(self) -> bool:
        """是否可以增加库存"""
        return self.allow_new_buy or self.allow_refill_buy


# 权限矩阵定义
STATE_PERMISSIONS: Dict[StrategyState, StatePermissions] = {
    StrategyState.NORMAL: StatePermissions(
        allow_new_buy=True,
        allow_refill_buy=True,
        allow_sell=True,
        allow_reduce_only=False,  # NORMAL 下不强制 reduce-only
        allow_reanchor=True,      # 受约束
        order_mode=OrderMode.FULL,
    ),
    StrategyState.DEFENSIVE: StatePermissions(
        allow_new_buy=False,      # 冻结新增 buy
        allow_refill_buy=False,   # 禁止补 buy
        allow_sell=True,          # 允许 sell 减仓
        allow_reduce_only=True,   # 推荐 reduce-only
        allow_reanchor=False,     # 默认不允许
        order_mode=OrderMode.NO_NEW_BUYS,
    ),
    StrategyState.DAMAGE_CONTROL: StatePermissions(
        allow_new_buy=False,
        allow_refill_buy=False,
        allow_sell=True,          # 分段减仓
        allow_reduce_only=True,   # 强制 reduce-only
        allow_reanchor=False,
        order_mode=OrderMode.REDUCE_ONLY,
    ),
    StrategyState.EMERGENCY_STOP: StatePermissions(
        allow_new_buy=False,
        allow_refill_buy=False,
        allow_sell=True,          # 紧急处理
        allow_reduce_only=True,   # 强制 reduce-only
        allow_reanchor=False,
        order_mode=OrderMode.KILL_SWITCH,
    ),
}


def get_permissions(state: StrategyState) -> StatePermissions:
    """获取指定状态的权限"""
    return STATE_PERMISSIONS[state]


# 状态迁移图（用于验证）
VALID_TRANSITIONS: Dict[StrategyState, Set[StrategyState]] = {
    StrategyState.NORMAL: {
        StrategyState.DEFENSIVE,
        StrategyState.EMERGENCY_STOP,
    },
    StrategyState.DEFENSIVE: {
        StrategyState.NORMAL,
        StrategyState.DAMAGE_CONTROL,
        StrategyState.EMERGENCY_STOP,
    },
    StrategyState.DAMAGE_CONTROL: {
        StrategyState.NORMAL,
        StrategyState.DEFENSIVE,
        StrategyState.EMERGENCY_STOP,
    },
    StrategyState.EMERGENCY_STOP: {
        # EMERGENCY_STOP 需要人工复核才能恢复
        # 可以恢复到 NORMAL（人工确认后）
        StrategyState.NORMAL,
    },
}


def is_valid_transition(from_state: StrategyState, to_state: StrategyState) -> bool:
    """检查状态迁移是否合法"""
    if from_state == to_state:
        return True  # 保持状态不变是合法的
    return to_state in VALID_TRANSITIONS.get(from_state, set())

