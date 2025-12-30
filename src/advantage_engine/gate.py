"""
优势门控接口

M2/M3 提供 stub 实现，M4 替换为完整实现
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal
from src.config.loader import compute_config_hash
from src.config.schema import GridStrategyConfig
from src.interfaces import IAdvantageGate


class AdvantageGateStub(IAdvantageGate):
    """
    M2/M3 stub 实现
    
    默认行为:
    - opportunity_valid 始终返回 True
    - core_zone 等于 outer_range
    - on_control_loop 只写 PARAM_UPDATE 审计
    """
    
    def __init__(
        self,
        config: GridStrategyConfig,
        session_id: str,
        audit_journal: Optional[IAuditJournal] = None,
    ):
        """
        初始化 stub
        
        Args:
            config: 策略配置
            session_id: 会话 ID
            audit_journal: 审计日志
        """
        self._config = config
        self._session_id = session_id
        self._audit_journal = audit_journal
        
        # 从配置获取 outer_range
        self._outer_range_low = config.trader_input.outer_range_low
        self._outer_range_high = config.trader_input.outer_range_high
        
        # 控制循环计数
        self._control_loop_count = 0
    
    @property
    def opportunity_valid(self) -> bool:
        """
        机会窗口是否有效
        
        stub: 始终返回 True
        M4 实现: 基于 cycle_activity/inv_reversion/breakeven_slope 判断
        """
        return True
    
    @property
    def core_zone(self) -> Tuple[float, float]:
        """
        返回 (core_low, core_high)
        
        stub: 等于 outer_range
        M4 实现: 基于 fill_density 和 adv_score 计算
        """
        return (self._outer_range_low, self._outer_range_high)
    
    def on_control_loop(self, timestamp: datetime) -> None:
        """
        control_loop 调用
        
        4H/1D 更新一次，写 PARAM_UPDATE 审计
        """
        self._control_loop_count += 1
        
        # 写 PARAM_UPDATE 审计
        if self._audit_journal is not None:
            config_hash = compute_config_hash(self._config)
            
            event = AuditEvent.param_update(
                session_id=self._session_id,
                timestamp=timestamp,
                param_name="control_loop",
                old_value=self._control_loop_count - 1,
                new_value=self._control_loop_count,
                config_hash=config_hash,
                reason=f"control_loop #{self._control_loop_count}",
            )
            self._audit_journal.write(event)
    
    def update_outer_range(self, low: float, high: float) -> None:
        """更新 outer_range"""
        self._outer_range_low = low
        self._outer_range_high = high


@dataclass
class AdvantageGateFull(IAdvantageGate):
    """
    M4 完整实现
    
    功能:
    - OpportunityWindow 计算
    - CoreZone 计算 (fill_density + adv_score)
    - control_loop 参数更新
    """
    config: GridStrategyConfig = None
    session_id: str = ""
    audit_journal: Optional[IAuditJournal] = None
    
    # 内部组件（需要延迟初始化）
    _opportunity_window: Optional["OpportunityWindow"] = None
    _core_zone_calc: Optional["CoreZoneCalculator"] = None
    
    # 外部区间
    _outer_range_low: float = 0.0
    _outer_range_high: float = 0.0
    
    # 当前状态
    _current_price: float = 0.0
    _inventory_ratio: float = 0.0
    _breakeven_price: float = 0.0
    
    # 控制循环计数
    _control_loop_count: int = 0
    
    def __post_init__(self):
        """延迟初始化组件"""
        from src.advantage_engine.opportunity_window import OpportunityWindow
        from src.advantage_engine.core_zone import CoreZoneCalculator
        
        if self.config is not None:
            self._outer_range_low = self.config.trader_input.outer_range_low
            self._outer_range_high = self.config.trader_input.outer_range_high
            
            self._opportunity_window = OpportunityWindow(
                valid_threshold=self.config.advantage.opportunity_valid_threshold,
                timeout_hours=self.config.advantage.opportunity_timeout_hours,
            )
            
            self._core_zone_calc = CoreZoneCalculator(
                zone_cover=self.config.advantage.zone_cover,
                T_zone_hours=self.config.advantage.T_zone_hours,
            )
        else:
            self._opportunity_window = OpportunityWindow()
            self._core_zone_calc = CoreZoneCalculator()
    
    @property
    def opportunity_valid(self) -> bool:
        """机会窗口是否有效"""
        if self._opportunity_window is None:
            return True
        return self._opportunity_window.is_valid
    
    @property
    def core_zone(self) -> Tuple[float, float]:
        """返回 (core_low, core_high)"""
        if self._core_zone_calc is None:
            return (self._outer_range_low, self._outer_range_high)
        
        low, high = self._core_zone_calc.core_zone
        if low is None or high is None:
            return (self._outer_range_low, self._outer_range_high)
        
        return (low, high)
    
    def on_control_loop(self, timestamp: datetime) -> None:
        """
        control_loop 调用
        
        4H/1D 更新一次
        """
        self._control_loop_count += 1
        
        # 更新 OpportunityWindow
        if self._opportunity_window is not None:
            self._opportunity_window.update(
                timestamp,
                self._inventory_ratio,
                self._breakeven_price,
                self._current_price,
            )
        
        # 更新 CoreZone
        if self._core_zone_calc is not None:
            inv_revert_score = 0.5
            breakeven_gain = 0.5
            
            if self._opportunity_window is not None:
                scores = self._opportunity_window.get_component_scores(
                    timestamp, self._current_price
                )
                inv_revert_score = scores.get("inv_reversion", 0.5)
                breakeven_gain = scores.get("breakeven_slope", 0.5)
            
            self._core_zone_calc.calculate_core_zone(
                timestamp,
                self._outer_range_low,
                self._outer_range_high,
                inv_revert_score,
                breakeven_gain,
            )
        
        # 写 PARAM_UPDATE 审计
        if self.audit_journal is not None:
            config_hash = compute_config_hash(self.config) if self.config else "unknown"
            
            event = AuditEvent.param_update(
                session_id=self.session_id,
                timestamp=timestamp,
                param_name="control_loop",
                old_value=self._control_loop_count - 1,
                new_value=self._control_loop_count,
                config_hash=config_hash,
                reason=f"control_loop #{self._control_loop_count}",
            )
            self.audit_journal.write(event)
    
    def record_fill(self, timestamp: datetime, price: float, qty: float, side: str) -> None:
        """记录成交"""
        if self._opportunity_window is not None:
            self._opportunity_window.record_fill(timestamp, side)
        
        if self._core_zone_calc is not None:
            self._core_zone_calc.record_fill(timestamp, price, qty)
    
    def record_round_trip(self, timestamp: datetime) -> None:
        """记录完整周期"""
        if self._opportunity_window is not None:
            self._opportunity_window.record_round_trip(timestamp)
    
    def update_state(
        self,
        current_price: float,
        inventory_ratio: float,
        breakeven_price: float,
    ) -> None:
        """更新状态"""
        self._current_price = current_price
        self._inventory_ratio = inventory_ratio
        self._breakeven_price = breakeven_price
    
    def update_outer_range(self, low: float, high: float) -> None:
        """更新 outer_range"""
        self._outer_range_low = low
        self._outer_range_high = high
    
    def get_adv_score(self, price: float, timestamp: datetime) -> float:
        """获取特定价格的优势分数"""
        if self._core_zone_calc is None:
            return 0.5
        
        inv_revert_score = 0.5
        breakeven_gain = 0.5
        
        if self._opportunity_window is not None:
            scores = self._opportunity_window.get_component_scores(
                timestamp, self._current_price
            )
            inv_revert_score = scores.get("inv_reversion", 0.5)
            breakeven_gain = scores.get("breakeven_slope", 0.5)
        
        return self._core_zone_calc.get_adv_score(
            price, timestamp, inv_revert_score, breakeven_gain
        )
    
    @property
    def opportunity_score(self) -> float:
        """机会窗口分数"""
        if self._opportunity_window is None:
            return 0.5
        return self._opportunity_window.score

