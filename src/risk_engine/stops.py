"""
各类 Stop 实现

按照绑定表实现:
| Stop | Trigger | State Transition | Order Actions | Position Actions | Audit | Enforce Point |
|------|---------|------------------|---------------|------------------|-------|---------------|
| InventoryStop | inventory_ratio >= 0.85 | → DAMAGE_CONTROL | cancel_all_non_reduce_only() | reduce_to(0.45) | INVENTORY_STOP | both |
| RiskBudgetStop | margin >= cap OR dd >= max | → DAMAGE_CONTROL | cancel_all_non_reduce_only() | forced_reduce() | RISK_BUDGET_STOP | both |
| StructuralStop | break_confirmed | → DAMAGE_CONTROL | cancel_all() | prepare_reanchor_or_exit() | STRUCTURAL_STOP | on_bar_close |
| EmergencyStop | liq_gap/api_fault/liq_dist | → EMERGENCY_STOP | kill_switch + cancel_all() | emergency_exit() | EMERGENCY_STOP | immediate |
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.models.state import StrategyState
from src.models.snapshot import Snapshot
from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal
from src.state_machine.transitions import TransitionResult


class IStop(ABC):
    """Stop 接口"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Stop 名称"""
        pass
    
    @abstractmethod
    def evaluate(self, timestamp: datetime) -> Optional[TransitionResult]:
        """
        评估是否触发
        
        Returns:
            TransitionResult 或 None
        """
        pass
    
    @abstractmethod
    def execute_actions(
        self,
        timestamp: datetime,
        session_id: str,
        audit_journal: IAuditJournal,
        snapshot: Optional[Snapshot] = None,
    ) -> None:
        """
        执行触发后的动作
        
        包括:
        - 订单动作
        - 持仓动作
        - 审计事件
        """
        pass
    
    @property
    @abstractmethod
    def enforce_point(self) -> str:
        """触发检查点"""
        pass


@dataclass
class InventoryStop(IStop):
    """
    库存止损
    
    触发: inventory_ratio >= 0.85
    动作:
    - State: → DAMAGE_CONTROL
    - Order: cancel_all_non_reduce_only()
    - Position: reduce_to(target=0.45)
    - Audit: INVENTORY_STOP + reason + snapshot
    """
    threshold: float = 0.85
    target_ratio: float = 0.45
    
    # 当前值
    current_ratio: float = 0.0
    
    # 动作回调（由外部注入）
    on_cancel_non_reduce_only: Optional[Callable[[], int]] = None
    on_reduce_to: Optional[Callable[[float], None]] = None
    
    @property
    def name(self) -> str:
        return "InventoryStop"
    
    @property
    def enforce_point(self) -> str:
        return "both"  # on_fill AND on_bar_close
    
    def evaluate(self, timestamp: datetime) -> Optional[TransitionResult]:
        """评估是否触发"""
        if self.current_ratio >= self.threshold:
            return TransitionResult.to_damage_control(
                trigger=None,  # 使用通用触发器
                reason=f"inventory_stop: ratio={self.current_ratio:.2%} >= {self.threshold:.2%}",
                value=self.current_ratio,
                threshold=self.threshold,
            )
        return None
    
    def execute_actions(
        self,
        timestamp: datetime,
        session_id: str,
        audit_journal: IAuditJournal,
        snapshot: Optional[Snapshot] = None,
    ) -> None:
        """执行触发后的动作"""
        # 1. 撤销所有非 reduce-only 订单
        cancelled_count = 0
        if self.on_cancel_non_reduce_only is not None:
            cancelled_count = self.on_cancel_non_reduce_only()
        
        # 2. 触发减仓
        if self.on_reduce_to is not None:
            self.on_reduce_to(self.target_ratio)
        
        # 3. 写审计
        event = AuditEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.INVENTORY_STOP,
            reason=f"inventory_stop: ratio={self.current_ratio:.2%} >= {self.threshold:.2%}",
            trigger_type="inventory_ratio",
            trigger_value=self.current_ratio,
            threshold=self.threshold,
            snapshot=snapshot,
            details={
                "cancelled_orders": cancelled_count,
                "target_ratio": self.target_ratio,
            },
        )
        audit_journal.write(event)
    
    def update(self, ratio: float) -> None:
        """更新当前值"""
        self.current_ratio = ratio


@dataclass
class RiskBudgetStop(IStop):
    """
    风险预算止损
    
    触发: margin_usage >= margin_cap OR drawdown >= max_dd
    动作:
    - State: → DAMAGE_CONTROL
    - Order: cancel_all_non_reduce_only()
    - Position: forced_reduce()
    - Audit: RISK_BUDGET_STOP + reason + snapshot
    """
    margin_cap: float = 0.80
    max_dd: float = 0.15
    
    # 当前值
    current_margin_usage: float = 0.0
    current_drawdown: float = 0.0
    
    # 动作回调
    on_cancel_non_reduce_only: Optional[Callable[[], int]] = None
    on_forced_reduce: Optional[Callable[[], None]] = None
    
    @property
    def name(self) -> str:
        return "RiskBudgetStop"
    
    @property
    def enforce_point(self) -> str:
        return "both"
    
    def evaluate(self, timestamp: datetime) -> Optional[TransitionResult]:
        """评估是否触发"""
        if self.current_margin_usage >= self.margin_cap:
            return TransitionResult.to_damage_control(
                trigger=None,
                reason=f"margin_cap_exceeded: usage={self.current_margin_usage:.2%} >= {self.margin_cap:.2%}",
                value=self.current_margin_usage,
                threshold=self.margin_cap,
            )
        
        if self.current_drawdown >= self.max_dd:
            return TransitionResult.to_damage_control(
                trigger=None,
                reason=f"max_dd_exceeded: dd={self.current_drawdown:.2%} >= {self.max_dd:.2%}",
                value=self.current_drawdown,
                threshold=self.max_dd,
            )
        
        return None
    
    def execute_actions(
        self,
        timestamp: datetime,
        session_id: str,
        audit_journal: IAuditJournal,
        snapshot: Optional[Snapshot] = None,
    ) -> None:
        """执行触发后的动作"""
        # 1. 撤销所有非 reduce-only 订单
        cancelled_count = 0
        if self.on_cancel_non_reduce_only is not None:
            cancelled_count = self.on_cancel_non_reduce_only()
        
        # 2. 强制减仓
        if self.on_forced_reduce is not None:
            self.on_forced_reduce()
        
        # 3. 确定触发原因
        if self.current_margin_usage >= self.margin_cap:
            reason = f"margin_cap_exceeded: usage={self.current_margin_usage:.2%}"
            trigger_type = "margin_usage"
            trigger_value = self.current_margin_usage
            threshold = self.margin_cap
        else:
            reason = f"max_dd_exceeded: dd={self.current_drawdown:.2%}"
            trigger_type = "drawdown"
            trigger_value = self.current_drawdown
            threshold = self.max_dd
        
        # 4. 写审计
        event = AuditEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.RISK_BUDGET_STOP,
            reason=reason,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            threshold=threshold,
            snapshot=snapshot,
            details={"cancelled_orders": cancelled_count},
        )
        audit_journal.write(event)
    
    def update(self, margin_usage: float, drawdown: float) -> None:
        """更新当前值"""
        self.current_margin_usage = margin_usage
        self.current_drawdown = drawdown


@dataclass
class StructuralStop(IStop):
    """
    结构性止损
    
    触发: structural_break_confirmed (B+C 口径)
    动作:
    - State: → DAMAGE_CONTROL
    - Order: cancel_all()
    - Position: prepare_reanchor_or_exit()
    - Audit: STRUCTURAL_STOP + reason + snapshot
    """
    # 当前状态
    is_confirmed: bool = False
    outside_duration_minutes: float = 0.0
    confirm_threshold_minutes: float = 240.0  # 4H
    
    # 动作回调
    on_cancel_all: Optional[Callable[[], int]] = None
    on_prepare_reanchor: Optional[Callable[[], None]] = None
    
    @property
    def name(self) -> str:
        return "StructuralStop"
    
    @property
    def enforce_point(self) -> str:
        return "on_bar_close"
    
    def evaluate(self, timestamp: datetime) -> Optional[TransitionResult]:
        """评估是否触发"""
        if self.is_confirmed:
            return TransitionResult.to_damage_control(
                trigger=None,
                reason=f"structural_break_confirmed: outside for {self.outside_duration_minutes:.0f}min",
                value=self.outside_duration_minutes,
                threshold=self.confirm_threshold_minutes,
            )
        return None
    
    def execute_actions(
        self,
        timestamp: datetime,
        session_id: str,
        audit_journal: IAuditJournal,
        snapshot: Optional[Snapshot] = None,
    ) -> None:
        """执行触发后的动作"""
        # 1. 撤销所有订单
        cancelled_count = 0
        if self.on_cancel_all is not None:
            cancelled_count = self.on_cancel_all()
        
        # 2. 准备 re-anchor 或退出
        if self.on_prepare_reanchor is not None:
            self.on_prepare_reanchor()
        
        # 3. 写审计
        event = AuditEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.STRUCTURAL_STOP,
            reason=f"structural_break_confirmed: outside for {self.outside_duration_minutes:.0f}min",
            trigger_type="outside_duration",
            trigger_value=self.outside_duration_minutes,
            threshold=self.confirm_threshold_minutes,
            snapshot=snapshot,
            details={"cancelled_orders": cancelled_count},
        )
        audit_journal.write(event)
    
    def update(self, is_confirmed: bool, outside_duration_minutes: float) -> None:
        """更新当前值"""
        self.is_confirmed = is_confirmed
        self.outside_duration_minutes = outside_duration_minutes


@dataclass
class EmergencyStopAction(IStop):
    """
    紧急止损
    
    触发: liq_gap / api_fault / liq_distance < threshold
    动作:
    - State: → EMERGENCY_STOP
    - Order: kill_switch() + cancel_all()
    - Position: emergency_exit(IOC_LAYERED)
    - Audit: EMERGENCY_STOP + reason + snapshot
    """
    # 触发原因
    trigger_reason: str = ""
    trigger_type: str = ""
    trigger_value: float = 0.0
    trigger_threshold: float = 0.0
    
    # 动作回调
    on_kill_switch: Optional[Callable[[], None]] = None
    on_cancel_all: Optional[Callable[[], int]] = None
    on_emergency_exit: Optional[Callable[[], str]] = None  # 返回退出结果
    
    @property
    def name(self) -> str:
        return "EmergencyStop"
    
    @property
    def enforce_point(self) -> str:
        return "immediate"
    
    def evaluate(self, timestamp: datetime) -> Optional[TransitionResult]:
        """评估是否触发（由 EmergencyTrigger 判断，这里只返回结果）"""
        if self.trigger_reason:
            return TransitionResult.to_emergency_stop(
                trigger=None,
                reason=self.trigger_reason,
                value=self.trigger_value,
                threshold=self.trigger_threshold,
            )
        return None
    
    def execute_actions(
        self,
        timestamp: datetime,
        session_id: str,
        audit_journal: IAuditJournal,
        snapshot: Optional[Snapshot] = None,
    ) -> None:
        """执行触发后的动作"""
        # 1. Kill switch
        if self.on_kill_switch is not None:
            self.on_kill_switch()
        
        # 2. 撤销所有订单
        cancelled_count = 0
        if self.on_cancel_all is not None:
            cancelled_count = self.on_cancel_all()
        
        # 3. 紧急退出
        exit_result = "not_executed"
        if self.on_emergency_exit is not None:
            exit_result = self.on_emergency_exit()
        
        # 4. 写审计
        event = AuditEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.EMERGENCY_STOP,
            reason=self.trigger_reason,
            trigger_type=self.trigger_type,
            trigger_value=self.trigger_value,
            threshold=self.trigger_threshold,
            exit_method="IOC_LAYERED",
            exit_result=exit_result,
            snapshot=snapshot,
            details={"cancelled_orders": cancelled_count},
        )
        audit_journal.write(event)
    
    def set_trigger(
        self,
        reason: str,
        trigger_type: str,
        value: float,
        threshold: float,
    ) -> None:
        """设置触发信息"""
        self.trigger_reason = reason
        self.trigger_type = trigger_type
        self.trigger_value = value
        self.trigger_threshold = threshold
    
    def clear_trigger(self) -> None:
        """清除触发信息"""
        self.trigger_reason = ""
        self.trigger_type = ""
        self.trigger_value = 0.0
        self.trigger_threshold = 0.0

