"""
网格层级与订单模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = auto()       # 待下单
    OPEN = auto()          # 已挂单
    PARTIALLY_FILLED = auto()  # 部分成交
    FILLED = auto()        # 完全成交
    CANCELLED = auto()     # 已撤销
    REJECTED = auto()      # 被拒绝
    STUCK = auto()         # 卡住（撤单失败）


@dataclass
class GridLevel:
    """
    网格层级
    
    描述一个网格价位的配置
    """
    level_id: int              # 层级 ID（从中心向外编号）
    price: float               # 价格
    side: OrderSide            # 方向
    base_size: float           # 基础 size
    actual_size: float         # 实际 size（经过边缘递减）
    is_in_core: bool = True    # 是否在 core zone 内
    decay_factor: float = 1.0  # 边缘递减系数
    
    @property
    def is_buy(self) -> bool:
        return self.side == OrderSide.BUY
    
    @property
    def is_sell(self) -> bool:
        return self.side == OrderSide.SELL


@dataclass
class GridOrder:
    """
    网格订单
    
    描述一个具体的挂单
    """
    # 订单标识
    client_order_id: str       # 客户端订单 ID: {session_id}_{level_id}_{side}_{seq}
    exchange_order_id: Optional[str] = None  # 交易所订单 ID
    
    # 订单参数
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    qty: float = 0.0
    reduce_only: bool = False
    
    # 关联
    grid_level: Optional[int] = None  # 关联的网格层级
    session_id: str = ""
    
    # 状态
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    avg_fill_price: float = 0.0
    
    # 时间
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # 元数据
    tags: dict = field(default_factory=dict)
    
    @property
    def is_open(self) -> bool:
        """是否是活跃订单"""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)
    
    @property
    def is_filled(self) -> bool:
        """是否已完全成交"""
        return self.status == OrderStatus.FILLED
    
    @property
    def notional(self) -> float:
        """名义价值"""
        return self.price * self.qty
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": self.price,
            "qty": self.qty,
            "reduce_only": self.reduce_only,
            "grid_level": self.grid_level,
            "session_id": self.session_id,
            "status": self.status.name,
            "filled_qty": self.filled_qty,
            "remaining_qty": self.remaining_qty,
            "avg_fill_price": self.avg_fill_price,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "tags": self.tags,
        }
    
    @classmethod
    def generate_client_order_id(
        cls,
        session_id: str,
        level_id: int,
        side: OrderSide,
        sequence: int,
    ) -> str:
        """
        生成客户端订单 ID
        
        格式: {session_id}_{level_id:02d}_{side}_{seq:03d}
        示例: s20250629_L05_buy_001
        """
        side_str = side.value
        return f"{session_id}_L{level_id:02d}_{side_str}_{sequence:03d}"

