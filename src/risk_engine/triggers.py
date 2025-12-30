"""
风控触发器

实现各类风控触发条件的检测
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from src.models.state import StrategyState
from src.state_machine.transitions import TransitionTrigger, TransitionResult


class IRiskTrigger(ABC):
    """风控触发器接口"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """触发器名称"""
        pass
    
    @abstractmethod
    def check(self, timestamp: datetime) -> TransitionResult:
        """
        检查是否触发
        
        Returns:
            TransitionResult (triggered, target_state, reason)
        """
        pass
    
    @property
    @abstractmethod
    def enforce_point(self) -> str:
        """
        触发检查点
        
        Returns:
            "on_fill" | "on_bar_close" | "both" | "immediate"
        """
        pass


@dataclass
class InventoryTrigger(IRiskTrigger):
    """
    库存触发器
    
    阈值:
    - inv_warn: 0.55 → DEFENSIVE
    - inv_damage: 0.70 → DAMAGE_CONTROL
    - inv_stop: 0.85 → 强制减仓
    - inv_back_to_normal: 0.40 → 恢复 NORMAL
    """
    # 阈值配置
    inv_warn: float = 0.55
    inv_damage: float = 0.70
    inv_stop: float = 0.85
    inv_back_to_normal: float = 0.40
    
    # 当前值（由外部更新）
    current_inventory_ratio: float = 0.0
    current_state: StrategyState = StrategyState.NORMAL
    
    @property
    def name(self) -> str:
        return "InventoryTrigger"
    
    @property
    def enforce_point(self) -> str:
        return "both"  # on_fill AND on_bar_close
    
    def check(self, timestamp: datetime) -> TransitionResult:
        """检查库存触发条件"""
        ratio = self.current_inventory_ratio
        state = self.current_state
        
        # 检查 EMERGENCY 触发（inv_stop）
        if ratio >= self.inv_stop:
            return TransitionResult.to_damage_control(
                trigger=TransitionTrigger.INV_DAMAGE,
                reason=f"inventory_stop: ratio={ratio:.2%} >= {self.inv_stop:.2%}",
                value=ratio,
                threshold=self.inv_stop,
            )
        
        # 检查 DAMAGE_CONTROL 触发（inv_damage）
        if ratio >= self.inv_damage:
            if state in (StrategyState.NORMAL, StrategyState.DEFENSIVE):
                return TransitionResult.to_damage_control(
                    trigger=TransitionTrigger.INV_DAMAGE,
                    reason=f"inventory_damage: ratio={ratio:.2%} >= {self.inv_damage:.2%}",
                    value=ratio,
                    threshold=self.inv_damage,
                )
        
        # 检查 DEFENSIVE 触发（inv_warn）
        if ratio >= self.inv_warn:
            if state == StrategyState.NORMAL:
                return TransitionResult.to_defensive(
                    trigger=TransitionTrigger.INV_WARN,
                    reason=f"inventory_warn: ratio={ratio:.2%} >= {self.inv_warn:.2%}",
                    value=ratio,
                    threshold=self.inv_warn,
                )
        
        # 检查恢复到 NORMAL
        if ratio <= self.inv_back_to_normal:
            if state == StrategyState.DEFENSIVE:
                return TransitionResult.to_normal(
                    trigger=TransitionTrigger.CONDITIONS_RECOVERED,
                    reason=f"inventory_recovered: ratio={ratio:.2%} <= {self.inv_back_to_normal:.2%}",
                )
        
        return TransitionResult.no_transition()
    
    def update(self, inventory_ratio: float, state: StrategyState) -> None:
        """更新当前值"""
        self.current_inventory_ratio = inventory_ratio
        self.current_state = state


@dataclass
class RiskBudgetTrigger(IRiskTrigger):
    """
    风险预算触发器
    
    触发条件:
    - margin_usage >= margin_cap
    - drawdown >= max_dd
    """
    margin_cap: float = 0.80
    max_dd: float = 0.15
    
    # 当前值
    current_margin_usage: float = 0.0
    current_drawdown: float = 0.0
    current_state: StrategyState = StrategyState.NORMAL
    
    @property
    def name(self) -> str:
        return "RiskBudgetTrigger"
    
    @property
    def enforce_point(self) -> str:
        return "both"
    
    def check(self, timestamp: datetime) -> TransitionResult:
        """检查风险预算触发条件"""
        # 检查保证金使用率
        if self.current_margin_usage >= self.margin_cap:
            if self.current_state != StrategyState.EMERGENCY_STOP:
                return TransitionResult.to_damage_control(
                    trigger=TransitionTrigger.RISK_BUDGET_STOP,
                    reason=f"margin_cap_exceeded: usage={self.current_margin_usage:.2%} >= {self.margin_cap:.2%}",
                    value=self.current_margin_usage,
                    threshold=self.margin_cap,
                )
        
        # 检查回撤
        if self.current_drawdown >= self.max_dd:
            if self.current_state != StrategyState.EMERGENCY_STOP:
                return TransitionResult.to_damage_control(
                    trigger=TransitionTrigger.RISK_BUDGET_STOP,
                    reason=f"max_dd_exceeded: dd={self.current_drawdown:.2%} >= {self.max_dd:.2%}",
                    value=self.current_drawdown,
                    threshold=self.max_dd,
                )
        
        return TransitionResult.no_transition()
    
    def update(
        self,
        margin_usage: float,
        drawdown: float,
        state: StrategyState,
    ) -> None:
        """更新当前值"""
        self.current_margin_usage = margin_usage
        self.current_drawdown = drawdown
        self.current_state = state


@dataclass
class StructuralTrigger(IRiskTrigger):
    """
    结构性破位触发器
    
    确认定义 (B + C):
    - stage_B: close 超出 outer_range ± ATR_buffer
    - stage_C: 边界外累计时间 >= T_confirm (默认 4H)
    
    计时规则:
    - method: timestamp_diff
    - accumulation: continuous_only
    - reset_on_return: immediate
    """
    # 配置
    outer_range_low: float = 0.0
    outer_range_high: float = 0.0
    atr_buffer: float = 0.0           # ATR * buffer_mult
    confirm_minutes: int = 240        # 4H = 240 分钟
    
    # 当前值
    current_price: float = 0.0
    current_state: StrategyState = StrategyState.NORMAL
    
    # 内部状态（用于时间累计）
    _is_outside: bool = False
    _outside_since: Optional[datetime] = None
    _confirmed: bool = False
    
    @property
    def name(self) -> str:
        return "StructuralTrigger"
    
    @property
    def enforce_point(self) -> str:
        return "on_bar_close"  # 只在 bar_close 检查
    
    def check(self, timestamp: datetime) -> TransitionResult:
        """检查结构性破位触发条件"""
        # 计算边界
        lower_boundary = self.outer_range_low - self.atr_buffer
        upper_boundary = self.outer_range_high + self.atr_buffer
        
        # 检查是否在边界外
        is_outside = (
            self.current_price < lower_boundary or
            self.current_price > upper_boundary
        )
        
        if is_outside:
            if not self._is_outside:
                # 首次出界
                self._is_outside = True
                self._outside_since = timestamp
                self._confirmed = False
            else:
                # 持续在外，检查累计时间
                if self._outside_since is not None:
                    duration_minutes = (timestamp - self._outside_since).total_seconds() / 60
                    
                    if duration_minutes >= self.confirm_minutes:
                        self._confirmed = True
                        
                        # 触发
                        if self.current_state not in (StrategyState.DAMAGE_CONTROL, StrategyState.EMERGENCY_STOP):
                            return TransitionResult.to_damage_control(
                                trigger=TransitionTrigger.STRUCTURAL_BREAK,
                                reason=f"structural_break_confirmed: price={self.current_price:.2f} outside for {duration_minutes:.0f}min",
                                value=duration_minutes,
                                threshold=float(self.confirm_minutes),
                            )
        else:
            # 回到区间内，立即清零
            self._is_outside = False
            self._outside_since = None
            self._confirmed = False
        
        return TransitionResult.no_transition()
    
    def update(
        self,
        price: float,
        state: StrategyState,
        outer_range_low: float,
        outer_range_high: float,
        atr_buffer: float,
    ) -> None:
        """更新当前值"""
        self.current_price = price
        self.current_state = state
        self.outer_range_low = outer_range_low
        self.outer_range_high = outer_range_high
        self.atr_buffer = atr_buffer
    
    @property
    def is_outside(self) -> bool:
        """是否在边界外"""
        return self._is_outside
    
    @property
    def confirmed(self) -> bool:
        """是否已确认"""
        return self._confirmed
    
    @property
    def outside_duration_minutes(self) -> float:
        """在边界外的累计时间（分钟）"""
        if not self._is_outside or self._outside_since is None:
            return 0.0
        return (datetime.now() - self._outside_since).total_seconds() / 60


@dataclass
class EmergencyTrigger(IRiskTrigger):
    """
    紧急触发器
    
    触发条件（任一满足）:
    - liq_distance < 0.03 (3%)
    - margin_ratio < 1.2 (120%)
    - api_fault: 连续 N 次失败
    - data_stale: 超过 30 秒无数据
    - price_gap: abs(price_change) > ATR * 5
    """
    # 阈值配置
    liq_distance_threshold: float = 0.03
    margin_ratio_threshold: float = 1.2
    api_fault_max_consecutive: int = 3
    data_stale_seconds: int = 30
    price_gap_atr_mult: float = 5.0
    
    # 当前值（默认安全值，不会触发）
    current_liq_distance: Optional[float] = None
    current_margin_ratio: float = 10.0  # 默认安全值（1000% 保证金率）
    current_api_fault_count: int = 0
    current_data_age_seconds: float = 0.0
    current_price_change_ratio: float = 0.0
    current_atr: float = 0.0
    
    @property
    def name(self) -> str:
        return "EmergencyTrigger"
    
    @property
    def enforce_point(self) -> str:
        return "immediate"  # 立即检查
    
    def check(self, timestamp: datetime) -> TransitionResult:
        """检查紧急触发条件"""
        # 检查强平距离
        if self.current_liq_distance is not None:
            if self.current_liq_distance < self.liq_distance_threshold:
                return TransitionResult.to_emergency_stop(
                    trigger=TransitionTrigger.LIQ_DISTANCE,
                    reason=f"liq_distance_critical: {self.current_liq_distance:.2%} < {self.liq_distance_threshold:.2%}",
                    value=self.current_liq_distance,
                    threshold=self.liq_distance_threshold,
                )
        
        # 检查保证金率
        if self.current_margin_ratio < self.margin_ratio_threshold:
            return TransitionResult.to_emergency_stop(
                trigger=TransitionTrigger.LIQ_DISTANCE,
                reason=f"margin_ratio_critical: {self.current_margin_ratio:.2%} < {self.margin_ratio_threshold:.2%}",
                value=self.current_margin_ratio,
                threshold=self.margin_ratio_threshold,
            )
        
        # 检查 API 故障
        if self.current_api_fault_count >= self.api_fault_max_consecutive:
            return TransitionResult.to_emergency_stop(
                trigger=TransitionTrigger.API_FAULT,
                reason=f"api_fault: consecutive_failures={self.current_api_fault_count}",
                value=float(self.current_api_fault_count),
                threshold=float(self.api_fault_max_consecutive),
            )
        
        # 检查数据过期
        if self.current_data_age_seconds >= self.data_stale_seconds:
            return TransitionResult.to_emergency_stop(
                trigger=TransitionTrigger.DATA_STALE,
                reason=f"data_stale: age={self.current_data_age_seconds:.0f}s >= {self.data_stale_seconds}s",
                value=self.current_data_age_seconds,
                threshold=float(self.data_stale_seconds),
            )
        
        # 检查价格跳空
        if self.current_atr > 0:
            gap_threshold = self.current_atr * self.price_gap_atr_mult
            if abs(self.current_price_change_ratio) > gap_threshold:
                return TransitionResult.to_emergency_stop(
                    trigger=TransitionTrigger.LIQUIDITY_GAP,
                    reason=f"price_gap: change={self.current_price_change_ratio:.2%} > {gap_threshold:.2%}",
                    value=abs(self.current_price_change_ratio),
                    threshold=gap_threshold,
                )
        
        return TransitionResult.no_transition()
    
    def update(
        self,
        liq_distance: Optional[float] = None,
        margin_ratio: Optional[float] = None,
        api_fault_count: Optional[int] = None,
        data_age_seconds: Optional[float] = None,
        price_change_ratio: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> None:
        """更新当前值"""
        if liq_distance is not None:
            self.current_liq_distance = liq_distance
        if margin_ratio is not None:
            self.current_margin_ratio = margin_ratio
        if api_fault_count is not None:
            self.current_api_fault_count = api_fault_count
        if data_age_seconds is not None:
            self.current_data_age_seconds = data_age_seconds
        if price_change_ratio is not None:
            self.current_price_change_ratio = price_change_ratio
        if atr is not None:
            self.current_atr = atr
    
    def reset_api_fault_count(self) -> None:
        """重置 API 故障计数"""
        self.current_api_fault_count = 0
    
    def increment_api_fault_count(self) -> None:
        """增加 API 故障计数"""
        self.current_api_fault_count += 1


@dataclass
class PriceBoundaryTrigger(IRiskTrigger):
    """
    价格触边触发器
    
    触发条件:
    - mark_price 进入边界 buffer 区域 (outer_range ± 0.5*ATR)
    
    特点:
    - 瞬时判断 (check_timing: instant)
    - 最小状态持续时间: 15 分钟 (防止抖动)
    """
    # 配置
    outer_range_low: float = 0.0
    outer_range_high: float = 0.0
    buffer_atr_mult: float = 0.5
    min_state_hold_minutes: int = 15
    
    # 当前值
    current_mark_price: float = 0.0
    current_atr: float = 0.0
    current_state: StrategyState = StrategyState.NORMAL
    state_since: Optional[datetime] = None
    
    @property
    def name(self) -> str:
        return "PriceBoundaryTrigger"
    
    @property
    def enforce_point(self) -> str:
        return "immediate"  # 瞬时判断
    
    def check(self, timestamp: datetime) -> TransitionResult:
        """检查价格触边触发条件"""
        if self.current_state != StrategyState.NORMAL:
            return TransitionResult.no_transition()
        
        # 计算边界 buffer
        buffer = self.current_atr * self.buffer_atr_mult
        lower_buffer_zone = self.outer_range_low + buffer
        upper_buffer_zone = self.outer_range_high - buffer
        
        # 检查是否进入边界区域
        in_lower_buffer = self.current_mark_price <= lower_buffer_zone
        in_upper_buffer = self.current_mark_price >= upper_buffer_zone
        
        if in_lower_buffer or in_upper_buffer:
            side = "lower" if in_lower_buffer else "upper"
            return TransitionResult.to_defensive(
                trigger=TransitionTrigger.PRICE_BOUNDARY,
                reason=f"price_boundary: mark={self.current_mark_price:.2f} in {side} buffer zone",
                value=self.current_mark_price,
                threshold=lower_buffer_zone if in_lower_buffer else upper_buffer_zone,
            )
        
        return TransitionResult.no_transition()
    
    def check_recovery(self, timestamp: datetime) -> TransitionResult:
        """
        检查是否可以恢复到 NORMAL
        
        条件:
        - 价格回到安全区域
        - 状态持续时间 >= min_state_hold_minutes
        """
        if self.current_state != StrategyState.DEFENSIVE:
            return TransitionResult.no_transition()
        
        # 检查最小持续时间
        if self.state_since is not None:
            duration_minutes = (timestamp - self.state_since).total_seconds() / 60
            if duration_minutes < self.min_state_hold_minutes:
                return TransitionResult.no_transition()
        
        # 计算安全区域
        buffer = self.current_atr * self.buffer_atr_mult
        lower_safe = self.outer_range_low + buffer * 1.5
        upper_safe = self.outer_range_high - buffer * 1.5
        
        # 检查是否在安全区域
        if lower_safe <= self.current_mark_price <= upper_safe:
            return TransitionResult.to_normal(
                trigger=TransitionTrigger.CONDITIONS_RECOVERED,
                reason=f"price_boundary_cleared: mark={self.current_mark_price:.2f} in safe zone",
            )
        
        return TransitionResult.no_transition()
    
    def update(
        self,
        mark_price: float,
        atr: float,
        state: StrategyState,
        outer_range_low: float,
        outer_range_high: float,
        state_since: Optional[datetime] = None,
    ) -> None:
        """更新当前值"""
        self.current_mark_price = mark_price
        self.current_atr = atr
        self.current_state = state
        self.outer_range_low = outer_range_low
        self.outer_range_high = outer_range_high
        self.state_since = state_since

