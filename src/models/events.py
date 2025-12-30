"""
事件类型定义

系统中所有事件的基类和具体事件类型。
事件驱动架构的核心，用于 trade_loop 和 control_loop 的事件处理。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Optional


class EventType(Enum):
    """
    系统事件类型枚举
    
    分类：
    - 行情事件：BAR_OPEN, BAR_CLOSE, PRICE_UPDATE
    - 成交事件：FILL
    - 参数更新：PARAM_UPDATE (control_loop 触发)
    - 故障事件：FAULT (API 异常、数据过期等)
    """
    # 行情事件
    BAR_OPEN = auto()          # K线开盘
    BAR_CLOSE = auto()         # K线收盘
    PRICE_UPDATE = auto()      # 价格更新（瞬时）
    
    # 成交事件
    FILL = auto()              # 订单成交
    ORDER_REJECTED = auto()    # 订单被拒绝
    ORDER_CANCELLED = auto()   # 订单被撤销
    
    # 参数更新事件 (control_loop)
    PARAM_UPDATE = auto()      # 参数更新（4H/1D）
    
    # 故障事件
    FAULT = auto()             # 故障事件（API 异常、数据过期等）
    
    # 系统事件
    STARTUP = auto()           # 系统启动
    SHUTDOWN = auto()          # 系统关闭


class FaultType(Enum):
    """
    故障类型枚举
    
    用于 EmergencyStop 触发判定
    """
    API_FAILURE = auto()       # API 调用失败
    DATA_STALE = auto()        # 数据过期
    PRICE_GAP = auto()         # 价格跳空
    LIQ_DISTANCE_LOW = auto()  # 强平距离过近
    UNKNOWN = auto()           # 未知故障


@dataclass(frozen=True)
class BaseEvent:
    """
    事件基类
    
    所有事件必须包含:
    - event_type: 事件类型
    - timestamp: 事件时间戳
    - session_id: 会话 ID
    """
    event_type: EventType
    timestamp: datetime
    session_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于序列化"""
        return {
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class BarOpenEvent(BaseEvent):
    """
    K线开盘事件
    
    触发时机：每根 K 线开始时
    用途：轻量级更新、日志记录
    """
    symbol: str
    bar_tf: str                # "1m", "5m", etc.
    open_price: float
    bar_time: datetime         # K线时间
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.BAR_OPEN)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "symbol": self.symbol,
            "bar_tf": self.bar_tf,
            "open_price": self.open_price,
            "bar_time": self.bar_time.isoformat(),
        })
        return d


@dataclass(frozen=True)
class BarCloseEvent(BaseEvent):
    """
    K线收盘事件
    
    触发时机：每根 K 线结束时
    用途：
    - 滚动统计更新
    - risk 检查
    - 轻量级更新
    - control_loop 累计判断
    """
    symbol: str
    bar_tf: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    mark_price: float          # 标记价格（用于风险计算）
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.BAR_CLOSE)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "symbol": self.symbol,
            "bar_tf": self.bar_tf,
            "bar_time": self.bar_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "mark_price": self.mark_price,
        })
        return d


@dataclass(frozen=True)
class PriceUpdateEvent(BaseEvent):
    """
    价格更新事件（瞬时）
    
    触发时机：价格变动时
    用途：
    - 价格触边判断（→ DEFENSIVE）
    - 订单差量计算
    """
    symbol: str
    mark_price: float
    last_price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.PRICE_UPDATE)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "last_price": self.last_price,
            "bid": self.bid,
            "ask": self.ask,
        })
        return d


@dataclass(frozen=True)
class FillEvent(BaseEvent):
    """
    订单成交事件
    
    触发时机：订单成交时
    用途：
    - 更新 inventory/breakeven
    - 触发 risk 检查
    - 状态迁移判定
    """
    symbol: str
    order_id: str
    client_order_id: str
    side: str                  # "buy" | "sell"
    fill_price: float
    fill_qty: float
    fee: float
    fee_currency: str
    is_partial: bool = False
    remaining_qty: float = 0.0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.FILL)
    
    @property
    def notional(self) -> float:
        """成交名义价值（quote currency）"""
        return self.fill_price * self.fill_qty
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "symbol": self.symbol,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "side": self.side,
            "fill_price": self.fill_price,
            "fill_qty": self.fill_qty,
            "fee": self.fee,
            "fee_currency": self.fee_currency,
            "is_partial": self.is_partial,
            "remaining_qty": self.remaining_qty,
            "notional": self.notional,
        })
        return d


@dataclass(frozen=True)
class ParamUpdateEvent(BaseEvent):
    """
    参数更新事件
    
    触发时机：control_loop (4H/1D)
    用途：
    - 更新 volatility
    - 更新 spacing
    - 更新 core_zone
    - 评估 derisk
    """
    param_name: str
    old_value: Any
    new_value: Any
    config_hash: str           # 当前配置哈希
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.PARAM_UPDATE)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "param_name": self.param_name,
            "old_value": str(self.old_value),
            "new_value": str(self.new_value),
            "config_hash": self.config_hash,
            "reason": self.reason,
        })
        return d


@dataclass(frozen=True)
class FaultEvent(BaseEvent):
    """
    故障事件
    
    触发时机：检测到故障时
    用途：
    - EmergencyStop 判定
    - 审计记录
    """
    fault_type: FaultType
    description: str
    severity: str = "error"    # "warning" | "error" | "critical"
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.FAULT)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "fault_type": self.fault_type.name,
            "description": self.description,
            "severity": self.severity,
            "details": self.details,
        })
        return d

