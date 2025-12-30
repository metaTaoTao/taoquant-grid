"""
实盘执行器 (LiveBroker)

基于 Bitget 交易所实现 IExecutionAdapter 接口
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.models.events import FillEvent, EventType
from src.models.grid import GridOrder, OrderSide, OrderStatus
from src.interfaces import IExecutionAdapter
from src.utils.timeutils import generate_session_id

# 尝试导入 Bitget 客户端
try:
    from exchange.bitget import BitgetClient
    HAS_BITGET = True
except ImportError:
    HAS_BITGET = False


@dataclass
class LiveBrokerConfig:
    """实盘执行器配置"""
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    market_type: str = "swap"  # "spot" | "swap"
    
    # 重试配置
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    
    # 超时配置
    order_timeout_seconds: int = 30
    cancel_timeout_seconds: int = 10
    
    @classmethod
    def from_env(cls) -> "LiveBrokerConfig":
        """从环境变量加载配置"""
        return cls(
            api_key=os.environ.get("BITGET_API_KEY", ""),
            api_secret=os.environ.get("BITGET_API_SECRET", ""),
            passphrase=os.environ.get("BITGET_PASSPHRASE", ""),
            market_type=os.environ.get("BITGET_MARKET_TYPE", "swap"),
        )


@dataclass
class LiveBroker(IExecutionAdapter):
    """
    实盘执行器
    
    实现 IExecutionAdapter 接口，封装 Bitget 交易所 API
    """
    config: LiveBrokerConfig = field(default_factory=LiveBrokerConfig)
    session_id: str = ""
    
    # 内部状态
    _client: Optional[Any] = None  # BitgetClient
    _is_connected: bool = False
    _open_orders: Dict[str, GridOrder] = field(default_factory=dict)
    _fill_callback: Optional[Callable[[FillEvent], None]] = None
    _api_fault_count: int = 0
    
    def __post_init__(self):
        if not self.session_id:
            self.session_id = generate_session_id()
    
    def connect(self) -> bool:
        """
        连接到交易所
        
        Returns:
            是否成功连接
        """
        if not HAS_BITGET:
            print("[LiveBroker] BitgetClient not available")
            return False
        
        if not self.config.api_key or not self.config.api_secret:
            print("[LiveBroker] API credentials not configured")
            return False
        
        try:
            self._client = BitgetClient(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret,
                passphrase=self.config.passphrase,
                market_type=self.config.market_type,
            )
            self._is_connected = True
            self._api_fault_count = 0
            print(f"[LiveBroker] Connected to Bitget ({self.config.market_type})")
            return True
        except Exception as e:
            print(f"[LiveBroker] Connection failed: {e}")
            self._is_connected = False
            return False
    
    def disconnect(self) -> None:
        """断开连接"""
        self._client = None
        self._is_connected = False
    
    def place_order(self, order: GridOrder) -> str:
        """
        下单
        
        Returns:
            exchange_order_id
        """
        if not self._is_connected or self._client is None:
            raise RuntimeError("Not connected to exchange")
        
        try:
            result = self._client.place_limit_order(
                symbol=order.symbol,
                side=order.side.value,
                price=order.price,
                quantity=order.qty,
            )
            
            if result is None:
                self._api_fault_count += 1
                raise RuntimeError("Order placement failed")
            
            exchange_order_id = result.get("order_id", "")
            
            # 更新订单状态
            order.exchange_order_id = exchange_order_id
            order.status = OrderStatus.OPEN
            order.created_at = datetime.now()
            order.remaining_qty = order.qty
            
            # 记录订单
            self._open_orders[order.client_order_id] = order
            
            # 重置故障计数
            self._api_fault_count = 0
            
            return exchange_order_id
            
        except Exception as e:
            self._api_fault_count += 1
            raise RuntimeError(f"Order placement error: {e}")
    
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单
        
        Args:
            order_id: client_order_id 或 exchange_order_id
            
        Returns:
            是否成功
        """
        if not self._is_connected or self._client is None:
            return False
        
        # 查找订单
        order = self._open_orders.get(order_id)
        if order is None:
            # 可能是 exchange_order_id
            for o in self._open_orders.values():
                if o.exchange_order_id == order_id:
                    order = o
                    break
        
        if order is None:
            return False
        
        try:
            success = self._client.cancel_order(
                symbol=order.symbol,
                order_id=order.exchange_order_id or order_id,
            )
            
            if success:
                order.status = OrderStatus.CANCELLED
                self._open_orders.pop(order.client_order_id, None)
                self._api_fault_count = 0
            else:
                self._api_fault_count += 1
            
            return success
            
        except Exception as e:
            self._api_fault_count += 1
            print(f"[LiveBroker] Cancel error: {e}")
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
        # 同步订单状态
        self._sync_order_status(symbol)
        
        return [
            order for order in self._open_orders.values()
            if order.symbol == symbol and order.is_open
        ]
    
    def _sync_order_status(self, symbol: str) -> None:
        """同步订单状态"""
        if not self._is_connected or self._client is None:
            return
        
        for order in list(self._open_orders.values()):
            if order.symbol != symbol:
                continue
            
            if not order.exchange_order_id:
                continue
            
            try:
                status = self._client.get_order_status(
                    symbol=order.symbol,
                    order_id=order.exchange_order_id,
                )
                
                if status is None:
                    continue
                
                exchange_status = status.get("status", "")
                filled = status.get("filled", 0)
                avg_price = status.get("average_price", 0)
                
                # 更新订单状态
                if exchange_status == "closed":
                    order.status = OrderStatus.FILLED
                    order.filled_qty = filled
                    order.remaining_qty = 0
                    order.avg_fill_price = avg_price
                    
                    # 生成成交事件
                    self._emit_fill_event(order, filled, avg_price)
                    
                    # 移除已完成订单
                    self._open_orders.pop(order.client_order_id, None)
                    
                elif exchange_status == "canceled":
                    order.status = OrderStatus.CANCELLED
                    self._open_orders.pop(order.client_order_id, None)
                    
                elif filled > order.filled_qty:
                    # 部分成交
                    new_fill = filled - order.filled_qty
                    order.filled_qty = filled
                    order.remaining_qty = order.qty - filled
                    order.avg_fill_price = avg_price
                    order.status = OrderStatus.PARTIALLY_FILLED
                    
                    self._emit_fill_event(order, new_fill, avg_price)
                    
            except Exception as e:
                print(f"[LiveBroker] Status sync error: {e}")
    
    def _emit_fill_event(
        self,
        order: GridOrder,
        fill_qty: float,
        fill_price: float,
    ) -> None:
        """发送成交事件"""
        if self._fill_callback is None:
            return
        
        event = FillEvent(
            event_type=EventType.FILL,
            timestamp=datetime.now(),
            session_id=self.session_id,
            symbol=order.symbol,
            order_id=order.exchange_order_id or "",
            client_order_id=order.client_order_id,
            side=order.side.value,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee=0.0,  # 需要从交易所获取
            fee_currency="USDT",
            is_partial=order.remaining_qty > 0,
            remaining_qty=order.remaining_qty,
        )
        
        self._fill_callback(event)
    
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """
        获取持仓
        
        注意：需要扩展 BitgetClient 以支持持仓查询
        """
        # TODO: 实现持仓查询
        return {
            "position_qty": 0.0,
            "avg_price": 0.0,
            "unrealized_pnl": 0.0,
            "margin": 0.0,
        }
    
    def get_account(self) -> Dict[str, Any]:
        """
        获取账户信息
        
        注意：需要扩展 BitgetClient 以支持账户查询
        """
        # TODO: 实现账户查询
        return {
            "equity": 0.0,
            "available": 0.0,
            "margin_usage": 0.0,
        }
    
    def set_fill_callback(self, callback: Callable[[FillEvent], None]) -> None:
        """设置成交回调"""
        self._fill_callback = callback
    
    @property
    def supports_reduce_only(self) -> bool:
        """是否支持 reduce-only"""
        return self.config.market_type == "swap"
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected
    
    @property
    def api_fault_count(self) -> int:
        """API 故障计数"""
        return self._api_fault_count
    
    def reset_api_fault_count(self) -> None:
        """重置 API 故障计数"""
        self._api_fault_count = 0

