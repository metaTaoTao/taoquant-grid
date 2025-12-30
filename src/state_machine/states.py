"""
状态机实现

实现四态状态机的核心逻辑，包括：
- 状态迁移
- 进入动作执行（硬绑定）
- 权限检查
"""

from datetime import datetime
from typing import Callable, List, Optional, TYPE_CHECKING

from src.models.state import (
    StrategyState,
    StatePermissions,
    OrderMode,
    STATE_PERMISSIONS,
    is_valid_transition,
    get_permissions,
)
from src.models.snapshot import Snapshot
from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal

if TYPE_CHECKING:
    from src.execution.order_manager import OrderManager
    from src.interfaces import IExecutionAdapter


class StateMachine:
    """
    策略状态机
    
    管理四态迁移和进入动作执行
    """
    
    def __init__(
        self,
        session_id: str,
        audit_journal: IAuditJournal,
        order_manager: Optional["OrderManager"] = None,
        execution_adapter: Optional["IExecutionAdapter"] = None,
        initial_state: StrategyState = StrategyState.NORMAL,
        symbol: str = "",
        core_zone_low: float = 0.0,
        core_zone_high: float = 0.0,
    ):
        """
        初始化状态机
        
        Args:
            session_id: 会话 ID
            audit_journal: 审计日志
            order_manager: 订单管理器（用于执行进入动作）
            execution_adapter: 执行适配器（用于撤单）
            initial_state: 初始状态
            symbol: 交易对
            core_zone_low: core zone 下限
            core_zone_high: core zone 上限
        """
        self._session_id = session_id
        self._audit_journal = audit_journal
        self._order_manager = order_manager
        self._execution_adapter = execution_adapter
        self._current_state = initial_state
        self._state_since: Optional[datetime] = None
        self._transition_history: List[tuple] = []
        self._symbol = symbol
        self._core_zone_low = core_zone_low
        self._core_zone_high = core_zone_high
        
        # 紧急退出回调
        self._on_emergency_exit: Optional[Callable[[], str]] = None
    
    @property
    def current_state(self) -> StrategyState:
        """当前状态"""
        return self._current_state
    
    @property
    def permissions(self) -> StatePermissions:
        """当前状态的权限"""
        return get_permissions(self._current_state)
    
    @property
    def state_since(self) -> Optional[datetime]:
        """当前状态开始时间"""
        return self._state_since
    
    def can_transition_to(self, new_state: StrategyState) -> bool:
        """检查是否可以迁移到目标状态"""
        return is_valid_transition(self._current_state, new_state)
    
    def transition_to(
        self,
        new_state: StrategyState,
        reason: str,
        timestamp: datetime,
        snapshot: Optional[Snapshot] = None,
    ) -> bool:
        """
        执行状态迁移
        
        Args:
            new_state: 目标状态
            reason: 迁移原因
            timestamp: 时间戳
            snapshot: 状态快照（可选）
            
        Returns:
            是否成功迁移
        """
        if self._current_state == new_state:
            return True  # 已经在目标状态
        
        if not self.can_transition_to(new_state):
            # 非法迁移
            return False
        
        old_state = self._current_state
        
        # 执行迁移
        self._current_state = new_state
        self._state_since = timestamp
        
        # 记录历史
        self._transition_history.append((timestamp, old_state, new_state, reason))
        
        # 执行进入动作
        self._execute_entry_actions(new_state, timestamp)
        
        # 写入审计日志
        event = AuditEvent.state_change(
            session_id=self._session_id,
            timestamp=timestamp,
            from_state=old_state.name,
            to_state=new_state.name,
            reason=reason,
            snapshot=snapshot,
        )
        self._audit_journal.write(event)
        
        return True
    
    def _execute_entry_actions(
        self,
        new_state: StrategyState,
        timestamp: datetime,
    ) -> None:
        """
        执行进入状态的强制动作
        
        这些动作是硬绑定的，必须执行
        """
        if new_state == StrategyState.DEFENSIVE:
            self._enter_defensive(timestamp)
        elif new_state == StrategyState.DAMAGE_CONTROL:
            self._enter_damage_control(timestamp)
        elif new_state == StrategyState.EMERGENCY_STOP:
            self._enter_emergency_stop(timestamp)
        elif new_state == StrategyState.NORMAL:
            self._enter_normal(timestamp)
    
    def _enter_defensive(self, timestamp: datetime) -> None:
        """
        进入 DEFENSIVE 状态的强制动作：
        
        1. 撤销所有会扩大风险的 buy（core 外所有 buy + 任何会增加 inventory_ratio 的挂单）
        2. OrderManager 进入 NO_NEW_BUYS 模式
        """
        cancelled_count = 0
        
        # 1. 设置订单模式
        if self._order_manager is not None:
            self._order_manager.set_mode(OrderMode.NO_NEW_BUYS)
            
            # 2. 获取需要撤销的高风险 buy 订单
            risky_order_ids = self._order_manager.get_risky_buy_orders(
                self._core_zone_low,
                self._core_zone_high,
            )
            
            # 3. 撤销订单
            if self._execution_adapter is not None and risky_order_ids:
                for order_id in risky_order_ids:
                    try:
                        if self._execution_adapter.cancel_order(order_id):
                            self._order_manager.unregister_order(order_id)
                            cancelled_count += 1
                    except Exception:
                        pass  # 撤单失败会在 OrderManager 中标记为 stuck
        
        # 记录进入动作
        self._log_entry_action("DEFENSIVE", {
            "cancelled_orders": cancelled_count,
            "mode": "NO_NEW_BUYS",
        })
    
    def _enter_damage_control(self, timestamp: datetime) -> None:
        """
        进入 DAMAGE_CONTROL 状态的强制动作：
        
        1. 撤销所有非 reduce-only 订单
        2. 强制 reduce_only = True
        3. OrderManager 进入 REDUCE_ONLY 模式
        """
        cancelled_count = 0
        
        # 1. 设置订单模式
        if self._order_manager is not None:
            self._order_manager.set_mode(OrderMode.REDUCE_ONLY)
            
            # 2. 获取所有非 reduce-only 订单
            non_reduce_only_ids = self._order_manager.get_non_reduce_only_orders()
            
            # 3. 撤销订单
            if self._execution_adapter is not None and non_reduce_only_ids:
                for order_id in non_reduce_only_ids:
                    try:
                        if self._execution_adapter.cancel_order(order_id):
                            self._order_manager.unregister_order(order_id)
                            cancelled_count += 1
                    except Exception:
                        pass
        
        # 记录进入动作
        self._log_entry_action("DAMAGE_CONTROL", {
            "cancelled_orders": cancelled_count,
            "mode": "REDUCE_ONLY",
        })
    
    def _enter_emergency_stop(self, timestamp: datetime) -> None:
        """
        进入 EMERGENCY_STOP 状态的强制动作：
        
        1. kill_switch（停止新单、停止网格生成）
        2. 撤销所有挂单
        3. 执行紧急退出（IOC 分层 → fallback 市价）
        """
        cancelled_count = 0
        exit_result = "not_executed"
        
        # 1. Kill switch
        if self._order_manager is not None:
            self._order_manager.set_mode(OrderMode.KILL_SWITCH)
            
            # 获取所有订单
            all_order_ids = self._order_manager.get_all_order_ids()
        else:
            all_order_ids = []
        
        # 2. 撤销所有挂单
        if self._execution_adapter is not None:
            if self._symbol:
                cancelled_count = self._execution_adapter.cancel_all_orders(self._symbol)
            elif all_order_ids:
                for order_id in all_order_ids:
                    try:
                        if self._execution_adapter.cancel_order(order_id):
                            cancelled_count += 1
                    except Exception:
                        pass
            
            # 清理订单管理器
            if self._order_manager is not None:
                for order_id in all_order_ids:
                    self._order_manager.unregister_order(order_id)
        
        # 3. 执行紧急退出
        if self._on_emergency_exit is not None:
            exit_result = self._on_emergency_exit()
        
        # 记录进入动作
        self._log_entry_action("EMERGENCY_STOP", {
            "cancelled_orders": cancelled_count,
            "mode": "KILL_SWITCH",
            "exit_result": exit_result,
        })
    
    def _enter_normal(self, timestamp: datetime) -> None:
        """
        进入 NORMAL 状态的动作：
        
        恢复正常订单模式
        """
        if self._order_manager is not None:
            self._order_manager.set_mode(OrderMode.FULL)
        
        # 记录进入动作
        self._log_entry_action("NORMAL", {
            "mode": "FULL",
        })
    
    def _log_entry_action(self, state: str, details: dict) -> None:
        """记录进入动作到日志"""
        # 这里可以写入更详细的日志
        pass
    
    def set_emergency_exit_callback(self, callback: Callable[[], str]) -> None:
        """设置紧急退出回调"""
        self._on_emergency_exit = callback
    
    def update_core_zone(self, low: float, high: float) -> None:
        """更新 core zone"""
        self._core_zone_low = low
        self._core_zone_high = high
    
    def set_symbol(self, symbol: str) -> None:
        """设置交易对"""
        self._symbol = symbol
    
    def check_order_allowed(
        self,
        order_type: str,  # "new_buy" | "refill_buy" | "sell" | "reduce_only"
        timestamp: datetime,
    ) -> tuple:
        """
        检查订单是否被允许
        
        Args:
            order_type: 订单类型
            timestamp: 时间戳
            
        Returns:
            (是否允许, 原因)
        """
        perms = self.permissions
        
        if order_type == "new_buy":
            if not perms.allow_new_buy:
                # 写入 ORDER_BLOCKED 审计
                event = AuditEvent.order_blocked(
                    session_id=self._session_id,
                    timestamp=timestamp,
                    order_type="new_buy",
                    reason="no_new_buys",
                    state=self._current_state.name,
                )
                self._audit_journal.write(event)
                return (False, "New buy orders not allowed in current state")
        
        elif order_type == "refill_buy":
            if not perms.allow_refill_buy:
                event = AuditEvent.order_blocked(
                    session_id=self._session_id,
                    timestamp=timestamp,
                    order_type="refill_buy",
                    reason="no_refill_buys",
                    state=self._current_state.name,
                )
                self._audit_journal.write(event)
                return (False, "Refill buy orders not allowed in current state")
        
        elif order_type == "sell":
            if not perms.allow_sell:
                return (False, "Sell orders not allowed in current state")
        
        return (True, "")
    
    def get_state_duration_minutes(self, timestamp: datetime) -> float:
        """获取当前状态持续时间（分钟）"""
        if self._state_since is None:
            return 0.0
        
        delta = timestamp - self._state_since
        return delta.total_seconds() / 60

