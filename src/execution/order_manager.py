"""
订单管理器

实现:
- 订单模式管理 (FULL/NO_NEW_BUYS/REDUCE_ONLY/KILL_SWITCH)
- 差量计算 (desired vs current)
- 订单节流/去抖
- 幂等性保护
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from src.models.state import OrderMode
from src.models.grid import GridOrder, OrderSide, OrderStatus
from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal


@dataclass
class OrderThrottleConfig:
    """订单节流配置"""
    min_order_lifetime_seconds: int = 30
    price_change_threshold_atr_mult: float = 0.1
    cancel_rate_limit_per_minute: int = 10
    freeze_duration_seconds: int = 60


@dataclass
class OrderManager:
    """
    订单管理器
    
    职责:
    - 管理订单模式
    - 差量计算
    - 订单节流/去抖
    - 幂等性保护
    - 写入 ORDER_BLOCKED 审计
    """
    session_id: str = ""
    audit_journal: Optional[IAuditJournal] = None
    throttle_config: OrderThrottleConfig = field(default_factory=OrderThrottleConfig)
    
    # 订单模式
    _order_mode: OrderMode = OrderMode.FULL
    
    # 订单跟踪
    _active_orders: Dict[str, GridOrder] = field(default_factory=dict)  # client_order_id -> order
    _order_created_at: Dict[str, datetime] = field(default_factory=dict)
    _processed_order_ids: Set[str] = field(default_factory=set)
    
    # 节流状态
    _cancel_timestamps: List[datetime] = field(default_factory=list)
    _is_frozen: bool = False
    _freeze_until: Optional[datetime] = None
    _current_atr: float = 0.0
    
    # 订单序列
    _order_sequence: int = 0
    
    @property
    def order_mode(self) -> str:
        """当前订单模式"""
        return self._order_mode.name
    
    @order_mode.setter
    def order_mode(self, mode: str) -> None:
        """设置订单模式"""
        self._order_mode = OrderMode[mode]
    
    def set_mode(self, mode: OrderMode) -> None:
        """设置订单模式（枚举版）"""
        self._order_mode = mode
    
    def can_place_order(
        self,
        order: GridOrder,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        检查是否可以下单
        
        检查项:
        - 订单模式限制
        - 节流限制
        - 幂等性检查
        
        Returns:
            (是否可以, 原因)
        """
        # 检查冻结状态
        if self._is_frozen:
            if self._freeze_until and timestamp >= self._freeze_until:
                self._is_frozen = False
                self._freeze_until = None
            else:
                return (False, "order_manager_frozen")
        
        # 检查订单模式
        mode_check = self._check_mode_allows_order(order)
        if not mode_check[0]:
            # 写入 ORDER_BLOCKED 审计
            self._write_order_blocked(order, mode_check[1], timestamp)
            return mode_check
        
        # 检查幂等性
        if order.client_order_id in self._processed_order_ids:
            self._write_duplicate_blocked(order, timestamp)
            return (False, "duplicate_order")
        
        return (True, "")
    
    def _check_mode_allows_order(self, order: GridOrder) -> Tuple[bool, str]:
        """检查订单模式是否允许该订单"""
        if self._order_mode == OrderMode.KILL_SWITCH:
            return (False, "kill_switch_active")
        
        if self._order_mode == OrderMode.REDUCE_ONLY:
            if not order.reduce_only:
                return (False, "reduce_only_mode")
        
        if self._order_mode == OrderMode.NO_NEW_BUYS:
            if order.side == OrderSide.BUY and not order.reduce_only:
                return (False, "no_new_buys_mode")
        
        return (True, "")
    
    def _write_order_blocked(
        self,
        order: GridOrder,
        reason: str,
        timestamp: datetime,
    ) -> None:
        """写入 ORDER_BLOCKED 审计"""
        if self.audit_journal is None:
            return
        
        event = AuditEvent.order_blocked(
            session_id=self.session_id,
            timestamp=timestamp,
            order_type=f"{order.side.value}_{order.grid_level}",
            reason=reason,
            state=self._order_mode.name,
        )
        self.audit_journal.write(event)
    
    def _write_duplicate_blocked(
        self,
        order: GridOrder,
        timestamp: datetime,
    ) -> None:
        """写入重复订单阻止审计"""
        if self.audit_journal is None:
            return
        
        event = AuditEvent(
            session_id=self.session_id,
            timestamp=timestamp,
            event_type=AuditEventType.ORDER_DUPLICATE_BLOCKED,
            reason="duplicate_order",
            order_id=order.client_order_id,
        )
        self.audit_journal.write(event)
    
    def sync_orders(
        self,
        desired_orders: List[GridOrder],
        current_orders: List[GridOrder],
        timestamp: datetime,
    ) -> Tuple[List[GridOrder], List[str]]:
        """
        同步订单（差量计算）
        
        规则:
        - add: desired 中有，current 中无 → 下单
        - remove: current 中有，desired 中无 → 撤单
        - modify: price_diff > threshold → 撤旧下新
        - keep: price_diff <= threshold → 不动
        
        Returns:
            (需要下的新订单, 需要撤销的订单 ID)
        """
        orders_to_place = []
        orders_to_cancel = []
        
        # 构建当前订单的字典（按层级和方向）
        current_by_key = {}
        for order in current_orders:
            key = (order.grid_level, order.side)
            current_by_key[key] = order
        
        # 构建期望订单的字典
        desired_by_key = {}
        for order in desired_orders:
            key = (order.grid_level, order.side)
            desired_by_key[key] = order
        
        # 检查需要撤销的订单
        for key, current_order in current_by_key.items():
            if key not in desired_by_key:
                # 订单不再需要，撤销
                if self._can_cancel(current_order, timestamp):
                    orders_to_cancel.append(current_order.client_order_id)
            else:
                # 检查是否需要修改
                desired_order = desired_by_key[key]
                if self._should_modify(current_order, desired_order):
                    if self._can_cancel(current_order, timestamp):
                        orders_to_cancel.append(current_order.client_order_id)
                        orders_to_place.append(desired_order)
        
        # 检查需要新增的订单
        for key, desired_order in desired_by_key.items():
            if key not in current_by_key:
                # 新订单
                can_place, _ = self.can_place_order(desired_order, timestamp)
                if can_place:
                    orders_to_place.append(desired_order)
        
        # 检查撤单频率
        if len(orders_to_cancel) > 0:
            if not self._check_cancel_rate(len(orders_to_cancel), timestamp):
                # 超过撤单频率限制，冻结
                self._freeze(timestamp)
                return ([], [])
        
        return (orders_to_place, orders_to_cancel)
    
    def _can_cancel(self, order: GridOrder, timestamp: datetime) -> bool:
        """检查是否可以撤销订单（最小生命周期）"""
        created_at = self._order_created_at.get(order.client_order_id)
        if created_at is None:
            return True
        
        age_seconds = (timestamp - created_at).total_seconds()
        return age_seconds >= self.throttle_config.min_order_lifetime_seconds
    
    def _should_modify(self, current: GridOrder, desired: GridOrder) -> bool:
        """检查是否需要修改订单"""
        if self._current_atr <= 0:
            # 无 ATR 数据，使用固定阈值
            threshold = current.price * 0.0005  # 5 bps
        else:
            threshold = self._current_atr * self.throttle_config.price_change_threshold_atr_mult
        
        price_diff = abs(current.price - desired.price)
        return price_diff > threshold
    
    def _check_cancel_rate(self, cancel_count: int, timestamp: datetime) -> bool:
        """检查撤单频率"""
        # 清理过期的撤单记录
        cutoff = timestamp.timestamp() - 60
        self._cancel_timestamps = [
            ts for ts in self._cancel_timestamps
            if ts.timestamp() > cutoff
        ]
        
        # 检查是否超过限制
        if len(self._cancel_timestamps) + cancel_count > self.throttle_config.cancel_rate_limit_per_minute:
            # 写审计
            if self.audit_journal is not None:
                event = AuditEvent(
                    session_id=self.session_id,
                    timestamp=timestamp,
                    event_type=AuditEventType.CANCEL_RATE_EXCEEDED,
                    reason=f"cancel_rate_limit: {len(self._cancel_timestamps)} + {cancel_count} > {self.throttle_config.cancel_rate_limit_per_minute}",
                )
                self.audit_journal.write(event)
            return False
        
        # 记录撤单
        for _ in range(cancel_count):
            self._cancel_timestamps.append(timestamp)
        
        return True
    
    def _freeze(self, timestamp: datetime) -> None:
        """冻结订单管理器"""
        self._is_frozen = True
        freeze_seconds = self.throttle_config.freeze_duration_seconds
        self._freeze_until = datetime.fromtimestamp(
            timestamp.timestamp() + freeze_seconds
        )
    
    def register_order(self, order: GridOrder, timestamp: datetime) -> None:
        """注册已下单的订单"""
        self._active_orders[order.client_order_id] = order
        self._order_created_at[order.client_order_id] = timestamp
        self._processed_order_ids.add(order.client_order_id)
    
    def unregister_order(self, client_order_id: str) -> None:
        """注销订单"""
        self._active_orders.pop(client_order_id, None)
        self._order_created_at.pop(client_order_id, None)
    
    def update_atr(self, atr: float) -> None:
        """更新 ATR（用于价格变化阈值计算）"""
        self._current_atr = atr
    
    def get_next_sequence(self) -> int:
        """获取下一个订单序列号"""
        self._order_sequence += 1
        return self._order_sequence
    
    def get_active_orders(self) -> List[GridOrder]:
        """获取所有活跃订单"""
        return list(self._active_orders.values())
    
    def get_risky_buy_orders(self, core_zone_low: float, core_zone_high: float) -> List[str]:
        """
        获取高风险 buy 订单（用于 ENTER_DEFENSIVE）
        
        高风险定义: core zone 外的 buy + 任何会增加 inventory 的挂单
        
        Returns:
            需要撤销的订单 ID 列表
        """
        risky_ids = []
        for order in self._active_orders.values():
            if order.side == OrderSide.BUY and not order.reduce_only:
                # core zone 外的 buy
                if order.price < core_zone_low or order.price > core_zone_high:
                    risky_ids.append(order.client_order_id)
        return risky_ids
    
    def get_non_reduce_only_orders(self) -> List[str]:
        """
        获取所有非 reduce-only 订单（用于 ENTER_DAMAGE_CONTROL）
        
        Returns:
            需要撤销的订单 ID 列表
        """
        return [
            order.client_order_id
            for order in self._active_orders.values()
            if not order.reduce_only
        ]
    
    def get_all_order_ids(self) -> List[str]:
        """
        获取所有订单 ID（用于 ENTER_EMERGENCY_STOP）
        
        Returns:
            所有订单 ID 列表
        """
        return list(self._active_orders.keys())
    
    @property
    def is_frozen(self) -> bool:
        """是否被冻结"""
        return self._is_frozen
    
    @property
    def active_order_count(self) -> int:
        """活跃订单数量"""
        return len(self._active_orders)

