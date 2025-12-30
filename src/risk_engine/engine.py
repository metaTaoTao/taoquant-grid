"""
风控引擎主体

整合所有风控触发器，评估风险并触发状态迁移
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.models.state import StrategyState
from src.models.events import BarCloseEvent, FillEvent
from src.models.snapshot import Snapshot
from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal
from src.config.schema import GridStrategyConfig
from src.state_machine.transitions import TransitionResult
from src.utils.volatility import ATRCalculator, VolSpikeDetector
from src.risk_engine.triggers import (
    InventoryTrigger,
    RiskBudgetTrigger,
    StructuralTrigger,
    EmergencyTrigger,
    PriceBoundaryTrigger,
)


@dataclass
class RiskEngine:
    """
    风控引擎
    
    职责:
    - 整合所有风控触发器
    - 评估风险（on_fill / on_bar_close）
    - 返回状态迁移建议
    - 记录风控审计事件
    """
    # 配置
    config: GridStrategyConfig = None
    session_id: str = ""
    audit_journal: Optional[IAuditJournal] = None
    
    # 触发器
    inventory_trigger: InventoryTrigger = field(default_factory=InventoryTrigger)
    risk_budget_trigger: RiskBudgetTrigger = field(default_factory=RiskBudgetTrigger)
    structural_trigger: StructuralTrigger = field(default_factory=StructuralTrigger)
    emergency_trigger: EmergencyTrigger = field(default_factory=EmergencyTrigger)
    price_boundary_trigger: PriceBoundaryTrigger = field(default_factory=PriceBoundaryTrigger)
    
    # 波动率检测器
    vol_spike_detector: VolSpikeDetector = field(default_factory=VolSpikeDetector)
    atr_calculator: ATRCalculator = field(default_factory=lambda: ATRCalculator(period=14))
    
    # 当前状态（由外部更新）
    current_state: StrategyState = StrategyState.NORMAL
    state_since: Optional[datetime] = None
    
    def __post_init__(self):
        """初始化触发器配置"""
        if self.config is not None:
            self._configure_triggers()
    
    def _configure_triggers(self) -> None:
        """根据配置初始化触发器"""
        risk = self.config.risk
        
        # 配置库存触发器
        self.inventory_trigger = InventoryTrigger(
            inv_warn=risk.inv_warn,
            inv_damage=risk.inv_damage,
            inv_stop=risk.inv_stop,
            inv_back_to_normal=risk.inv_back_to_normal,
        )
        
        # 配置风险预算触发器
        self.risk_budget_trigger = RiskBudgetTrigger(
            margin_cap=risk.margin_cap,
            max_dd=risk.max_dd,
        )
        
        # 配置结构性触发器
        self.structural_trigger = StructuralTrigger(
            confirm_minutes=self.config.structural_stop.confirm_minutes,
        )
        
        # 配置紧急触发器
        self.emergency_trigger = EmergencyTrigger(
            liq_distance_threshold=risk.liq_distance_threshold,
            api_fault_max_consecutive=risk.api_fault_max_consecutive,
            data_stale_seconds=risk.data_stale_seconds,
        )
        
        # 配置价格边界触发器
        self.price_boundary_trigger = PriceBoundaryTrigger(
            buffer_atr_mult=self.config.price_boundary.buffer_atr_mult,
            min_state_hold_minutes=self.config.price_boundary.min_state_hold_minutes,
        )
        
        # 配置波动率检测器
        self.vol_spike_detector = VolSpikeDetector(
            atr_len=self.config.volatility.atr_len,
            atr_ma_len=self.config.get_atr_ma_len(),
            spike_mult=self.config.volatility.spike_mult,
            clear_mult=self.config.volatility.clear_mult,
            cooldown_minutes=self.config.volatility.cooldown_minutes,
        )
    
    def evaluate_on_fill(
        self,
        fill: FillEvent,
        inventory_ratio: float,
        margin_usage: float,
        drawdown: float,
        snapshot: Optional[Snapshot] = None,
    ) -> Optional[Tuple[StrategyState, str]]:
        """
        成交后评估风险
        
        检查点: on_fill
        检查项:
        - InventoryTrigger
        - RiskBudgetTrigger
        - EmergencyTrigger
        
        Returns:
            (目标状态, 原因) 或 None
        """
        timestamp = fill.timestamp
        
        # 更新触发器状态
        self.inventory_trigger.update(inventory_ratio, self.current_state)
        self.risk_budget_trigger.update(margin_usage, drawdown, self.current_state)
        
        # 检查紧急触发（最高优先级）
        emergency_result = self.emergency_trigger.check(timestamp)
        if emergency_result.triggered:
            self._write_risk_trigger(timestamp, emergency_result, snapshot)
            return (emergency_result.target_state, emergency_result.reason)
        
        # 检查库存触发
        inv_result = self.inventory_trigger.check(timestamp)
        if inv_result.triggered:
            self._write_risk_trigger(timestamp, inv_result, snapshot)
            return (inv_result.target_state, inv_result.reason)
        
        # 检查风险预算触发
        budget_result = self.risk_budget_trigger.check(timestamp)
        if budget_result.triggered:
            self._write_risk_trigger(timestamp, budget_result, snapshot)
            return (budget_result.target_state, budget_result.reason)
        
        return None
    
    def evaluate_on_bar_close(
        self,
        bar: BarCloseEvent,
        inventory_ratio: float,
        margin_usage: float,
        drawdown: float,
        mark_price: float,
        outer_range_low: float,
        outer_range_high: float,
        snapshot: Optional[Snapshot] = None,
    ) -> Optional[Tuple[StrategyState, str]]:
        """
        K线收盘评估风险
        
        检查点: on_bar_close
        检查项:
        - InventoryTrigger
        - RiskBudgetTrigger
        - StructuralTrigger
        - VolSpikeDetector
        - PriceBoundaryTrigger (recovery)
        
        Returns:
            (目标状态, 原因) 或 None
        """
        timestamp = bar.timestamp
        
        # 更新 ATR
        current_atr = self.atr_calculator.update(bar.high, bar.low, bar.close)
        atr_buffer = current_atr * self.config.structural_stop.atr_buffer_mult if self.config else current_atr
        
        # 更新触发器状态
        self.inventory_trigger.update(inventory_ratio, self.current_state)
        self.risk_budget_trigger.update(margin_usage, drawdown, self.current_state)
        self.structural_trigger.update(
            mark_price,
            self.current_state,
            outer_range_low,
            outer_range_high,
            atr_buffer,
        )
        self.price_boundary_trigger.update(
            mark_price,
            current_atr,
            self.current_state,
            outer_range_low,
            outer_range_high,
            self.state_since,
        )
        
        # 更新波动率检测器
        vol_spike, vol_reason = self.vol_spike_detector.update(
            bar.high, bar.low, bar.close, timestamp
        )
        
        # 检查紧急触发（最高优先级）
        emergency_result = self.emergency_trigger.check(timestamp)
        if emergency_result.triggered:
            self._write_risk_trigger(timestamp, emergency_result, snapshot)
            return (emergency_result.target_state, emergency_result.reason)
        
        # 检查结构性破位（只在 bar_close 检查）
        structural_result = self.structural_trigger.check(timestamp)
        if structural_result.triggered:
            self._write_risk_trigger(timestamp, structural_result, snapshot)
            return (structural_result.target_state, structural_result.reason)
        
        # 检查库存触发
        inv_result = self.inventory_trigger.check(timestamp)
        if inv_result.triggered:
            self._write_risk_trigger(timestamp, inv_result, snapshot)
            return (inv_result.target_state, inv_result.reason)
        
        # 检查风险预算触发
        budget_result = self.risk_budget_trigger.check(timestamp)
        if budget_result.triggered:
            self._write_risk_trigger(timestamp, budget_result, snapshot)
            return (budget_result.target_state, budget_result.reason)
        
        # 检查波动率冲击（NORMAL → DEFENSIVE）
        if vol_spike and self.current_state == StrategyState.NORMAL:
            from src.state_machine.transitions import TransitionTrigger
            result = TransitionResult.to_defensive(
                trigger=TransitionTrigger.VOL_SPIKE,
                reason=vol_reason,
                value=self.vol_spike_detector.spike_ratio,
                threshold=self.vol_spike_detector.spike_mult,
            )
            self._write_risk_trigger(timestamp, result, snapshot)
            return (result.target_state, result.reason)
        
        # 检查恢复条件
        recovery_result = self._check_recovery(timestamp)
        if recovery_result is not None:
            return recovery_result
        
        return None
    
    def evaluate_immediate(
        self,
        timestamp: datetime,
        mark_price: float,
        liq_distance: Optional[float],
        margin_ratio: float,
        api_fault_count: int,
        data_age_seconds: float,
        outer_range_low: float,
        outer_range_high: float,
        snapshot: Optional[Snapshot] = None,
    ) -> Optional[Tuple[StrategyState, str]]:
        """
        即时评估风险（瞬时判断）
        
        检查点: immediate
        检查项:
        - EmergencyTrigger
        - PriceBoundaryTrigger
        
        Returns:
            (目标状态, 原因) 或 None
        """
        current_atr = self.atr_calculator.value
        
        # 更新紧急触发器
        self.emergency_trigger.update(
            liq_distance=liq_distance,
            margin_ratio=margin_ratio,
            api_fault_count=api_fault_count,
            data_age_seconds=data_age_seconds,
            atr=current_atr,
        )
        
        # 更新价格边界触发器
        self.price_boundary_trigger.update(
            mark_price,
            current_atr,
            self.current_state,
            outer_range_low,
            outer_range_high,
            self.state_since,
        )
        
        # 检查紧急触发
        emergency_result = self.emergency_trigger.check(timestamp)
        if emergency_result.triggered:
            self._write_risk_trigger(timestamp, emergency_result, snapshot)
            return (emergency_result.target_state, emergency_result.reason)
        
        # 检查价格触边（NORMAL → DEFENSIVE）
        if self.current_state == StrategyState.NORMAL:
            boundary_result = self.price_boundary_trigger.check(timestamp)
            if boundary_result.triggered:
                self._write_risk_trigger(timestamp, boundary_result, snapshot)
                return (boundary_result.target_state, boundary_result.reason)
        
        return None
    
    def _check_recovery(self, timestamp: datetime) -> Optional[Tuple[StrategyState, str]]:
        """检查恢复条件"""
        # 检查库存恢复
        inv_result = self.inventory_trigger.check(timestamp)
        if inv_result.triggered and inv_result.target_state == StrategyState.NORMAL:
            return (inv_result.target_state, inv_result.reason)
        
        # 检查价格边界恢复
        boundary_recovery = self.price_boundary_trigger.check_recovery(timestamp)
        if boundary_recovery.triggered:
            return (boundary_recovery.target_state, boundary_recovery.reason)
        
        # 检查波动率恢复
        if not self.vol_spike_detector.is_spike and self.current_state == StrategyState.DEFENSIVE:
            # 还需要检查其他条件都已恢复
            if self.inventory_trigger.current_inventory_ratio <= self.inventory_trigger.inv_back_to_normal:
                if not self.structural_trigger.is_outside:
                    return (
                        StrategyState.NORMAL,
                        "all_conditions_recovered"
                    )
        
        return None
    
    def _write_risk_trigger(
        self,
        timestamp: datetime,
        result: TransitionResult,
        snapshot: Optional[Snapshot],
    ) -> None:
        """写入风控触发审计事件"""
        if self.audit_journal is None:
            return
        
        event = AuditEvent.risk_trigger(
            session_id=self.session_id,
            timestamp=timestamp,
            trigger_type=result.trigger.name if result.trigger else "unknown",
            value=result.value or 0.0,
            threshold=result.threshold or 0.0,
            reason=result.reason,
            snapshot=snapshot,
        )
        self.audit_journal.write(event)
    
    def update_state(self, state: StrategyState, since: datetime) -> None:
        """更新当前状态"""
        self.current_state = state
        self.state_since = since
    
    def check_emergency(self) -> bool:
        """快速检查是否需要紧急停止"""
        result = self.emergency_trigger.check(datetime.now())
        return result.triggered
    
    def update_indicators(self, bar: BarCloseEvent) -> None:
        """更新风控指标"""
        self.atr_calculator.update(bar.high, bar.low, bar.close)
        self.vol_spike_detector.update(bar.high, bar.low, bar.close, bar.timestamp)
    
    @property
    def current_atr(self) -> float:
        """当前 ATR"""
        return self.atr_calculator.value
    
    @property
    def is_vol_spike(self) -> bool:
        """是否处于波动率冲击状态"""
        return self.vol_spike_detector.is_spike
    
    @property
    def structural_confirmed(self) -> bool:
        """结构性破位是否已确认"""
        return self.structural_trigger.confirmed
    
    def reset_api_fault_count(self) -> None:
        """重置 API 故障计数"""
        self.emergency_trigger.reset_api_fault_count()
    
    def increment_api_fault_count(self) -> None:
        """增加 API 故障计数"""
        self.emergency_trigger.increment_api_fault_count()

