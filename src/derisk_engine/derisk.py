"""
风险递减引擎 (DeRiskEngine)

实现:
- Harvest 模式：当盈利条件满足时收割
- DeRisk 模式：当边际效率下降时减仓
- House-Money 检测：累计盈利足够时转入保守模式
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from src.models.state import StrategyState
from src.models.inventory import Inventory, Breakeven


@dataclass
class DeRiskConfig:
    """风险递减配置"""
    # Harvest 条件
    harvest_profit_threshold: float = 0.02  # 2% 盈利触发 harvest
    harvest_inventory_ratio: float = 0.35   # 库存 > 35% 时才 harvest
    harvest_require_opportunity_valid: bool = True
    harvest_require_minutes: int = 60       # 机会有效持续 60 分钟
    
    # DeRisk 条件
    derisk_efficiency_drop: float = 0.30    # 效率下降 30% 触发 de-risk
    derisk_min_inventory: float = 0.20      # 库存 > 20% 才 de-risk
    
    # House-Money 条件
    house_money_profit_pct: float = 0.05    # 5% 累计盈利 = house money
    house_money_reduce_target: float = 0.50 # 进入 house money 后减仓到 50%
    
    # 减仓参数
    reduce_batch_size: float = 0.10         # 每次减仓 10%
    reduce_cooldown_minutes: int = 15       # 减仓冷却 15 分钟


@dataclass
class HarvestState:
    """Harvest 状态"""
    is_active: bool = False
    triggered_at: Optional[datetime] = None
    trigger_reason: str = ""
    target_reduce_ratio: float = 0.0


@dataclass
class DeRiskState:
    """DeRisk 状态"""
    is_active: bool = False
    triggered_at: Optional[datetime] = None
    trigger_reason: str = ""
    target_reduce_ratio: float = 0.0


@dataclass
class HouseMoneyState:
    """House-Money 状态"""
    is_active: bool = False
    activated_at: Optional[datetime] = None
    locked_profit: float = 0.0
    conservative_mode: bool = False


@dataclass
class DeRiskEngine:
    """
    风险递减引擎
    
    职责:
    - 检测 Harvest 条件并触发收割
    - 检测 DeRisk 条件并触发减仓
    - 检测 House-Money 状态并转入保守模式
    """
    config: DeRiskConfig = None
    session_id: str = ""
    
    # 状态
    harvest_state: HarvestState = field(default_factory=HarvestState)
    derisk_state: DeRiskState = field(default_factory=DeRiskState)
    house_money_state: HouseMoneyState = field(default_factory=HouseMoneyState)
    
    # 上次减仓时间
    _last_reduce_time: Optional[datetime] = None
    
    # 效率追踪
    _efficiency_history: list = field(default_factory=list)
    _peak_efficiency: float = 0.0
    
    def __post_init__(self):
        if self.config is None:
            self.config = DeRiskConfig()
    
    def evaluate(
        self,
        timestamp: datetime,
        inventory: Inventory,
        breakeven: Breakeven,
        current_price: float,
        opportunity_valid: bool,
        opportunity_valid_minutes: int,
        strategy_state: StrategyState,
        initial_equity: float,
        current_equity: float,
    ) -> Tuple[bool, str, float]:
        """
        评估是否需要减仓
        
        Args:
            timestamp: 当前时间
            inventory: 库存状态
            breakeven: 盈亏平衡状态
            current_price: 当前价格
            opportunity_valid: 机会窗口是否有效
            opportunity_valid_minutes: 机会有效持续时间
            strategy_state: 策略状态
            initial_equity: 初始权益
            current_equity: 当前权益
            
        Returns:
            (should_reduce, reason, target_ratio)
        """
        # 检查冷却期
        if not self._check_cooldown(timestamp):
            return (False, "in_cooldown", 0.0)
        
        # 1. 检查 House-Money 条件
        house_money_result = self._check_house_money(
            timestamp, initial_equity, current_equity
        )
        if house_money_result[0]:
            return house_money_result
        
        # 2. 检查 Harvest 条件
        harvest_result = self._check_harvest(
            timestamp, inventory, breakeven, current_price,
            opportunity_valid, opportunity_valid_minutes, strategy_state
        )
        if harvest_result[0]:
            return harvest_result
        
        # 3. 检查 DeRisk 条件
        derisk_result = self._check_derisk(
            timestamp, inventory, strategy_state
        )
        if derisk_result[0]:
            return derisk_result
        
        return (False, "no_action", 0.0)
    
    def _check_cooldown(self, timestamp: datetime) -> bool:
        """检查冷却期"""
        if self._last_reduce_time is None:
            return True
        
        elapsed = (timestamp - self._last_reduce_time).total_seconds() / 60
        return elapsed >= self.config.reduce_cooldown_minutes
    
    def _check_house_money(
        self,
        timestamp: datetime,
        initial_equity: float,
        current_equity: float,
    ) -> Tuple[bool, str, float]:
        """检查 House-Money 条件"""
        if initial_equity <= 0:
            return (False, "", 0.0)
        
        profit_pct = (current_equity - initial_equity) / initial_equity
        
        # 已经在 house money 模式
        if self.house_money_state.is_active:
            return (False, "already_house_money", 0.0)
        
        # 检查是否达到 house money 阈值
        if profit_pct >= self.config.house_money_profit_pct:
            self.house_money_state.is_active = True
            self.house_money_state.activated_at = timestamp
            self.house_money_state.locked_profit = profit_pct
            self.house_money_state.conservative_mode = True
            
            return (
                True,
                f"house_money: profit={profit_pct:.2%} >= {self.config.house_money_profit_pct:.2%}",
                self.config.house_money_reduce_target,
            )
        
        return (False, "", 0.0)
    
    def _check_harvest(
        self,
        timestamp: datetime,
        inventory: Inventory,
        breakeven: Breakeven,
        current_price: float,
        opportunity_valid: bool,
        opportunity_valid_minutes: int,
        strategy_state: StrategyState,
    ) -> Tuple[bool, str, float]:
        """检查 Harvest 条件"""
        # 状态检查
        if strategy_state not in (StrategyState.NORMAL, StrategyState.DEFENSIVE):
            return (False, "", 0.0)
        
        # 库存检查
        if inventory.inventory_ratio < self.config.harvest_inventory_ratio:
            return (False, "", 0.0)
        
        # 机会窗口检查
        if self.config.harvest_require_opportunity_valid:
            if not opportunity_valid:
                return (False, "", 0.0)
            if opportunity_valid_minutes < self.config.harvest_require_minutes:
                return (False, "", 0.0)
        
        # 盈利检查
        if breakeven.price <= 0:
            return (False, "", 0.0)
        
        profit_pct = (current_price - breakeven.price) / breakeven.price
        
        if profit_pct >= self.config.harvest_profit_threshold:
            self.harvest_state.is_active = True
            self.harvest_state.triggered_at = timestamp
            self.harvest_state.trigger_reason = f"harvest: profit={profit_pct:.2%}"
            
            target = inventory.inventory_ratio - self.config.reduce_batch_size
            self.harvest_state.target_reduce_ratio = max(0.0, target)
            
            return (
                True,
                f"harvest: profit={profit_pct:.2%} >= {self.config.harvest_profit_threshold:.2%}",
                self.harvest_state.target_reduce_ratio,
            )
        
        return (False, "", 0.0)
    
    def _check_derisk(
        self,
        timestamp: datetime,
        inventory: Inventory,
        strategy_state: StrategyState,
    ) -> Tuple[bool, str, float]:
        """检查 DeRisk 条件"""
        # 状态检查
        if strategy_state == StrategyState.EMERGENCY_STOP:
            return (False, "", 0.0)
        
        # 库存检查
        if inventory.inventory_ratio < self.config.derisk_min_inventory:
            return (False, "", 0.0)
        
        # 效率检查
        current_efficiency = self._calculate_efficiency(inventory)
        self._efficiency_history.append((timestamp, current_efficiency))
        self._peak_efficiency = max(self._peak_efficiency, current_efficiency)
        
        if self._peak_efficiency <= 0:
            return (False, "", 0.0)
        
        efficiency_drop = (self._peak_efficiency - current_efficiency) / self._peak_efficiency
        
        if efficiency_drop >= self.config.derisk_efficiency_drop:
            self.derisk_state.is_active = True
            self.derisk_state.triggered_at = timestamp
            self.derisk_state.trigger_reason = f"derisk: efficiency_drop={efficiency_drop:.2%}"
            
            target = inventory.inventory_ratio - self.config.reduce_batch_size
            self.derisk_state.target_reduce_ratio = max(0.0, target)
            
            return (
                True,
                f"derisk: efficiency_drop={efficiency_drop:.2%} >= {self.config.derisk_efficiency_drop:.2%}",
                self.derisk_state.target_reduce_ratio,
            )
        
        return (False, "", 0.0)
    
    def _calculate_efficiency(self, inventory: Inventory) -> float:
        """
        计算效率指标
        
        简化版：盈利 / 持仓时间
        """
        if inventory.position_notional <= 0:
            return 0.0
        
        # 简化计算：使用库存比率作为效率代理
        # 实际应该考虑：盈利速度、周转率等
        return 1.0 - inventory.inventory_ratio
    
    def on_reduce_executed(self, timestamp: datetime) -> None:
        """减仓执行完成回调"""
        self._last_reduce_time = timestamp
        
        # 重置状态
        if self.harvest_state.is_active:
            self.harvest_state.is_active = False
        if self.derisk_state.is_active:
            self.derisk_state.is_active = False
    
    def reset_efficiency_peak(self) -> None:
        """重置效率峰值（用于新周期）"""
        self._peak_efficiency = 0.0
        self._efficiency_history.clear()
    
    @property
    def is_conservative_mode(self) -> bool:
        """是否处于保守模式"""
        return self.house_money_state.conservative_mode
    
    @property
    def has_pending_action(self) -> bool:
        """是否有待执行的动作"""
        return (
            self.harvest_state.is_active or
            self.derisk_state.is_active
        )

