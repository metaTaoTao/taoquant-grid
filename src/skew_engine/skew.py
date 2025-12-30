"""
偏置定价引擎 (SkewEngine)

实现:
- 基于库存状态的价格偏置
- 门控条件（只在有利条件下启用）
- 偏置幅度限制
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from src.models.state import StrategyState


@dataclass
class SkewConfig:
    """偏置配置"""
    # 偏置幅度限制
    skew_max: float = 0.25  # 最大偏置 25%
    skew_per_inv_unit: float = 0.1  # 每单位库存偏置 10%
    
    # 门控条件
    require_core_zone: bool = True  # 只在 core zone 内启用
    require_normal_state: bool = True  # 只在 NORMAL 状态启用
    require_opportunity_valid: bool = True  # 只在机会有效时启用
    
    # 库存阈值
    inv_threshold_for_skew: float = 0.3  # 库存 > 30% 才开始偏置


@dataclass
class SkewEngine:
    """
    偏置定价引擎
    
    目的：
    - 当库存偏高时，主动偏低卖出价格以加速出货
    - 当库存偏低时，主动偏高买入价格以加速补货
    - 严格门控，只在有利条件下启用
    """
    config: SkewConfig = None
    
    # 当前状态
    _is_enabled: bool = False
    _current_skew: float = 0.0
    _gate_status: str = "disabled"
    
    def __post_init__(self):
        if self.config is None:
            self.config = SkewConfig()
    
    def calculate_skew(
        self,
        base_price: float,
        side: str,  # "buy" | "sell"
        inventory_ratio: float,
        state: StrategyState,
        opportunity_valid: bool,
        is_in_core_zone: bool,
    ) -> Tuple[float, bool, str]:
        """
        计算偏置后的价格
        
        Args:
            base_price: 基础价格
            side: 订单方向
            inventory_ratio: 库存比率 [-1, 1] 正为多头
            state: 当前策略状态
            opportunity_valid: 机会窗口是否有效
            is_in_core_zone: 是否在 core zone 内
            
        Returns:
            (skewed_price, is_skewed, reason)
        """
        # 检查门控条件
        gate_result = self._check_gate(
            state, opportunity_valid, is_in_core_zone, inventory_ratio
        )
        
        if not gate_result[0]:
            self._is_enabled = False
            self._current_skew = 0.0
            self._gate_status = gate_result[1]
            return (base_price, False, gate_result[1])
        
        # 计算偏置方向和幅度
        skew_direction, skew_magnitude = self._calculate_skew_params(
            side, inventory_ratio
        )
        
        if skew_magnitude <= 0:
            self._is_enabled = False
            self._current_skew = 0.0
            self._gate_status = "no_skew_needed"
            return (base_price, False, "no_skew_needed")
        
        # 应用偏置
        skew_ratio = skew_direction * skew_magnitude
        skewed_price = base_price * (1 + skew_ratio)
        
        self._is_enabled = True
        self._current_skew = skew_ratio
        self._gate_status = "active"
        
        return (
            skewed_price,
            True,
            f"skew={skew_ratio:.2%} inv={inventory_ratio:.2%}",
        )
    
    def _check_gate(
        self,
        state: StrategyState,
        opportunity_valid: bool,
        is_in_core_zone: bool,
        inventory_ratio: float,
    ) -> Tuple[bool, str]:
        """检查门控条件"""
        # 状态检查
        if self.config.require_normal_state:
            if state != StrategyState.NORMAL:
                return (False, f"state={state.name}")
        
        # 机会窗口检查
        if self.config.require_opportunity_valid:
            if not opportunity_valid:
                return (False, "opportunity_invalid")
        
        # Core zone 检查
        if self.config.require_core_zone:
            if not is_in_core_zone:
                return (False, "outside_core_zone")
        
        # 库存阈值检查
        if abs(inventory_ratio) < self.config.inv_threshold_for_skew:
            return (False, f"inv_below_threshold={inventory_ratio:.2%}")
        
        return (True, "gate_passed")
    
    def _calculate_skew_params(
        self,
        side: str,
        inventory_ratio: float,
    ) -> Tuple[float, float]:
        """
        计算偏置参数
        
        Returns:
            (direction, magnitude)
            direction: +1 提高价格, -1 降低价格
            magnitude: [0, skew_max]
        """
        # 库存为正（多头）：
        #   - 卖单：降低价格以加速出货（direction = -1）
        #   - 买单：提高价格以减少补货（direction = +1）
        # 库存为负（空头，极少情况）：
        #   - 买单：降低价格以加速补货（direction = -1）
        #   - 卖单：提高价格以减少出货（direction = +1）
        
        if inventory_ratio > 0:  # 多头
            if side == "sell":
                direction = -1  # 降低卖价，加速出货
            else:
                direction = +1  # 提高买价，减少补货
        else:  # 空头或中性
            if side == "buy":
                direction = -1  # 降低买价，加速补货
            else:
                direction = +1  # 提高卖价，减少出货
        
        # 计算偏置幅度（基于库存超出阈值的部分）
        excess_inv = abs(inventory_ratio) - self.config.inv_threshold_for_skew
        if excess_inv <= 0:
            return (0, 0)
        
        magnitude = excess_inv * self.config.skew_per_inv_unit
        magnitude = min(magnitude, self.config.skew_max)
        
        return (direction, magnitude)
    
    def get_skewed_levels(
        self,
        buy_prices: list,
        sell_prices: list,
        inventory_ratio: float,
        state: StrategyState,
        opportunity_valid: bool,
        core_zone_low: float,
        core_zone_high: float,
    ) -> Tuple[list, list]:
        """
        批量计算偏置后的价格
        
        Args:
            buy_prices: 买单价格列表
            sell_prices: 卖单价格列表
            inventory_ratio: 库存比率
            state: 策略状态
            opportunity_valid: 机会有效性
            core_zone_low: core zone 下限
            core_zone_high: core zone 上限
            
        Returns:
            (skewed_buy_prices, skewed_sell_prices)
        """
        skewed_buys = []
        skewed_sells = []
        
        for price in buy_prices:
            is_in_core = core_zone_low <= price <= core_zone_high
            skewed_price, _, _ = self.calculate_skew(
                price, "buy", inventory_ratio, state, opportunity_valid, is_in_core
            )
            skewed_buys.append(skewed_price)
        
        for price in sell_prices:
            is_in_core = core_zone_low <= price <= core_zone_high
            skewed_price, _, _ = self.calculate_skew(
                price, "sell", inventory_ratio, state, opportunity_valid, is_in_core
            )
            skewed_sells.append(skewed_price)
        
        return (skewed_buys, skewed_sells)
    
    @property
    def is_enabled(self) -> bool:
        """偏置是否启用"""
        return self._is_enabled
    
    @property
    def current_skew(self) -> float:
        """当前偏置幅度"""
        return self._current_skew
    
    @property
    def gate_status(self) -> str:
        """门控状态"""
        return self._gate_status

