"""
回测撮合器 (SimBroker)

实现保守撮合模型:
- 部分成交 (partial fill)
- 滑点模拟
- 手续费（默认 taker）
- 撤单失败/延迟模拟
- 成交顺序（先内层后外层）
"""

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any

from src.models.events import FillEvent, EventType
from src.models.grid import GridOrder, OrderSide, OrderStatus
from src.interfaces import IExecutionAdapter
from src.config.schema import SimBrokerConfig
from src.utils.timeutils import generate_session_id


@dataclass
class SimBrokerState:
    """SimBroker 内部状态"""
    position_qty: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    equity: float = 10000.0
    margin_used: float = 0.0


@dataclass
class SimBroker(IExecutionAdapter):
    """
    回测撮合器
    
    特点（保守撮合）:
    - partial_fill: 随机部分成交
    - fill_order: 先内层后外层，每 bar 限制成交次数
    - fill_price: 限价 + 滑点
    - fees: 默认 taker
    - cancel_simulation: 允许失败和延迟
    """
    config: SimBrokerConfig = field(default_factory=SimBrokerConfig)
    session_id: str = ""
    symbol: str = ""
    
    # 内部状态
    _state: SimBrokerState = field(default_factory=SimBrokerState)
    _open_orders: Dict[str, GridOrder] = field(default_factory=dict)
    _pending_cancels: Dict[str, int] = field(default_factory=dict)  # order_id -> delay_bars
    _fill_callback: Optional[Callable[[FillEvent], None]] = None
    
    # 当前 bar 状态
    _current_bar_fills: int = 0
    _current_high: float = 0.0
    _current_low: float = 0.0
    _current_close: float = 0.0
    
    def __post_init__(self):
        if not self.session_id:
            self.session_id = generate_session_id()
    
    def place_order(self, order: GridOrder) -> str:
        """
        下单
        
        Returns:
            exchange_order_id
        """
        # 生成交易所订单 ID
        exchange_order_id = f"sim_{order.client_order_id}"
        order.exchange_order_id = exchange_order_id
        order.status = OrderStatus.OPEN
        order.created_at = datetime.now()
        order.remaining_qty = order.qty
        
        self._open_orders[order.client_order_id] = order
        
        return exchange_order_id
    
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单
        
        Returns:
            是否成功
        """
        if order_id not in self._open_orders:
            return False
        
        # 模拟撤单失败
        if self.config.cancel_simulation.allow_fail:
            if random.random() < self.config.cancel_simulation.fail_probability:
                # 标记为 stuck
                order = self._open_orders[order_id]
                order.status = OrderStatus.STUCK
                return False
        
        # 模拟撤单延迟
        if self.config.cancel_simulation.delay_bars_max > 0:
            delay = random.randint(
                self.config.cancel_simulation.delay_bars_min,
                self.config.cancel_simulation.delay_bars_max,
            )
            if delay > 0:
                self._pending_cancels[order_id] = delay
                return True
        
        # 立即撤单
        order = self._open_orders.pop(order_id, None)
        if order:
            order.status = OrderStatus.CANCELLED
            return True
        
        return False
    
    def cancel_all_orders(self, symbol: str) -> int:
        """
        撤销所有订单
        
        Returns:
            撤销数量
        """
        cancelled_count = 0
        order_ids = list(self._open_orders.keys())
        
        for order_id in order_ids:
            order = self._open_orders.get(order_id)
            if order and order.symbol == symbol:
                if self.cancel_order(order_id):
                    cancelled_count += 1
        
        return cancelled_count
    
    def get_open_orders(self, symbol: str) -> List[GridOrder]:
        """获取活跃订单"""
        return [
            order for order in self._open_orders.values()
            if order.symbol == symbol and order.is_open
        ]
    
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """获取持仓"""
        return {
            "position_qty": self._state.position_qty,
            "avg_price": self._state.avg_entry_price,
            "unrealized_pnl": self._state.unrealized_pnl,
            "margin": self._state.margin_used,
        }
    
    def get_account(self) -> Dict[str, Any]:
        """获取账户信息"""
        return {
            "equity": self._state.equity,
            "available": self._state.equity - self._state.margin_used,
            "margin_usage": self._state.margin_used / self._state.equity if self._state.equity > 0 else 0,
            "realized_pnl": self._state.realized_pnl,
            "total_fees": self._state.total_fees,
        }
    
    def set_fill_callback(self, callback: Callable[[FillEvent], None]) -> None:
        """设置成交回调"""
        self._fill_callback = callback
    
    @property
    def supports_reduce_only(self) -> bool:
        """是否支持 reduce-only"""
        return True
    
    def on_bar(
        self,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> List[FillEvent]:
        """
        处理新 bar
        
        检查订单是否触发成交
        
        Args:
            high: 最高价
            low: 最低价
            close: 收盘价
            timestamp: 时间戳
            
        Returns:
            成交事件列表
        """
        self._current_high = high
        self._current_low = low
        self._current_close = close
        self._current_bar_fills = 0
        
        fills = []
        
        # 处理延迟撤单
        self._process_pending_cancels()
        
        # 获取可能触发的订单并按距离排序（先内层后外层）
        triggered_orders = self._get_triggered_orders(high, low)
        
        # 按配置限制成交次数
        max_fills = self.config.fill_order.max_fills_per_bar
        
        for order in triggered_orders:
            if self._current_bar_fills >= max_fills:
                break
            
            fill_event = self._try_fill_order(order, timestamp)
            if fill_event:
                fills.append(fill_event)
                self._current_bar_fills += 1
                
                # 触发回调
                if self._fill_callback:
                    self._fill_callback(fill_event)
        
        # 更新未实现盈亏
        self._update_unrealized_pnl(close)
        
        return fills
    
    def _get_triggered_orders(self, high: float, low: float) -> List[GridOrder]:
        """
        获取触发的订单
        
        规则：先内层后外层
        """
        triggered = []
        
        for order in self._open_orders.values():
            if not order.is_open:
                continue
            
            # 检查是否触发
            if order.side == OrderSide.BUY:
                if low <= order.price:
                    triggered.append(order)
            else:  # SELL
                if high >= order.price:
                    triggered.append(order)
        
        # 按与当前价格的距离排序（先内层）
        mid_price = (high + low) / 2
        triggered.sort(key=lambda o: abs(o.price - mid_price))
        
        return triggered
    
    def _try_fill_order(
        self,
        order: GridOrder,
        timestamp: datetime,
    ) -> Optional[FillEvent]:
        """
        尝试成交订单
        
        包含：部分成交、滑点、手续费
        """
        # 计算成交数量（部分成交）
        fill_qty = self._calculate_fill_qty(order)
        
        if fill_qty <= 0:
            return None
        
        # 计算成交价格（含滑点）
        fill_price = self._calculate_fill_price(order)
        
        # 计算手续费
        fee = self._calculate_fee(fill_price, fill_qty)
        
        # 更新订单状态
        order.filled_qty += fill_qty
        order.remaining_qty -= fill_qty
        order.avg_fill_price = fill_price  # 简化：假设单次成交
        
        is_partial = order.remaining_qty > 1e-8
        
        if is_partial:
            order.status = OrderStatus.PARTIALLY_FILLED
        else:
            order.status = OrderStatus.FILLED
            self._open_orders.pop(order.client_order_id, None)
        
        order.updated_at = datetime.now()
        
        # 更新持仓
        self._update_position(order.side, fill_price, fill_qty, fee)
        
        # 创建成交事件
        return FillEvent(
            event_type=EventType.FILL,
            timestamp=timestamp,
            session_id=self.session_id,
            symbol=order.symbol,
            order_id=order.exchange_order_id or "",
            client_order_id=order.client_order_id,
            side=order.side.value,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee=fee,
            fee_currency="USDT",
            is_partial=is_partial,
            remaining_qty=order.remaining_qty,
        )
    
    def _calculate_fill_qty(self, order: GridOrder) -> float:
        """计算成交数量（支持部分成交）"""
        if not self.config.partial_fill.enabled:
            return order.remaining_qty
        
        if self.config.partial_fill.mode == "fixed":
            ratio = (self.config.partial_fill.ratio_min + self.config.partial_fill.ratio_max) / 2
        else:
            ratio = random.uniform(
                self.config.partial_fill.ratio_min,
                self.config.partial_fill.ratio_max,
            )
        
        return order.remaining_qty * ratio
    
    def _calculate_fill_price(self, order: GridOrder) -> float:
        """
        计算成交价格
        
        规则：限价 + 滑点（对交易者不利）
        """
        slippage_bps = self.config.fill_price.slippage_bps
        slippage_ratio = slippage_bps / 10000
        
        if order.side == OrderSide.BUY:
            # 买单：成交价略高于限价
            return order.price * (1 + slippage_ratio)
        else:
            # 卖单：成交价略低于限价
            return order.price * (1 - slippage_ratio)
    
    def _calculate_fee(self, price: float, qty: float) -> float:
        """
        计算手续费
        
        默认使用 taker 费率
        """
        notional = price * qty
        
        if self.config.fees.default_side == "taker":
            fee_bps = self.config.fees.taker_fee_bps
        else:
            fee_bps = self.config.fees.maker_fee_bps
        
        return notional * fee_bps / 10000
    
    def _update_position(
        self,
        side: OrderSide,
        price: float,
        qty: float,
        fee: float,
    ) -> None:
        """更新持仓"""
        if side == OrderSide.BUY:
            # 买入：增加多头
            old_value = self._state.position_qty * self._state.avg_entry_price
            new_value = qty * price
            new_qty = self._state.position_qty + qty
            
            if new_qty > 0:
                self._state.avg_entry_price = (old_value + new_value) / new_qty
            
            self._state.position_qty = new_qty
        else:
            # 卖出：减少多头或增加空头
            if self._state.position_qty > 0:
                # 计算已实现盈亏
                realized = (price - self._state.avg_entry_price) * min(qty, self._state.position_qty)
                self._state.realized_pnl += realized
            
            self._state.position_qty -= qty
        
        self._state.total_fees += fee
        
        # 简单的保证金计算（10 倍杠杆）
        self._state.margin_used = abs(self._state.position_qty * self._current_close) / 10
    
    def _update_unrealized_pnl(self, price: float) -> None:
        """更新未实现盈亏"""
        if self._state.position_qty != 0:
            self._state.unrealized_pnl = (price - self._state.avg_entry_price) * self._state.position_qty
        else:
            self._state.unrealized_pnl = 0.0
    
    def _process_pending_cancels(self) -> None:
        """处理延迟撤单"""
        completed = []
        
        for order_id, delay in self._pending_cancels.items():
            if delay <= 1:
                # 执行撤单
                order = self._open_orders.pop(order_id, None)
                if order:
                    order.status = OrderStatus.CANCELLED
                completed.append(order_id)
            else:
                self._pending_cancels[order_id] = delay - 1
        
        for order_id in completed:
            self._pending_cancels.pop(order_id, None)
    
    def set_initial_equity(self, equity: float) -> None:
        """设置初始权益"""
        self._state.equity = equity
    
    def reset(self) -> None:
        """重置状态"""
        self._state = SimBrokerState()
        self._open_orders.clear()
        self._pending_cancels.clear()
        self._current_bar_fills = 0

