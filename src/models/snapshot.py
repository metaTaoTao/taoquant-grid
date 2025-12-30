"""
状态快照模型

用于审计事件的完整状态记录
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.state import StrategyState


@dataclass
class OrdersSummary:
    """活跃订单摘要"""
    total_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    reduce_only_count: int = 0
    max_buy_distance: float = 0.0   # 最远 buy 距离当前价
    max_sell_distance: float = 0.0  # 最远 sell 距离当前价
    total_buy_notional: float = 0.0
    total_sell_notional: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "total_count": self.total_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "reduce_only_count": self.reduce_only_count,
            "max_buy_distance": self.max_buy_distance,
            "max_sell_distance": self.max_sell_distance,
            "total_buy_notional": self.total_buy_notional,
            "total_sell_notional": self.total_sell_notional,
        }


@dataclass
class Snapshot:
    """
    完整状态快照
    
    用于审计事件记录，确保可以完整还原决策时的状态
    """
    # 时间
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 价格
    mark_price: float = 0.0
    last_price: float = 0.0
    
    # 状态
    state: StrategyState = StrategyState.NORMAL
    
    # 库存
    inventory_ratio: float = 0.0
    position_qty: float = 0.0
    
    # 成本
    breakeven_price: float = 0.0
    
    # PnL
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float = 0.0
    
    # 保证金
    margin_usage: float = 0.0
    liq_distance: Optional[float] = None
    
    # 区间
    outer_range_low: float = 0.0
    outer_range_high: float = 0.0
    core_zone_low: Optional[float] = None
    core_zone_high: Optional[float] = None
    
    # 订单
    active_orders_summary: OrdersSummary = field(default_factory=OrdersSummary)
    
    # 波动率
    atr: float = 0.0
    rv: float = 0.0
    vol_spike: bool = False
    
    # 风控状态
    structural_break_confirmed: bool = False
    outside_since: Optional[datetime] = None
    
    # 配置
    config_hash: str = ""
    session_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "mark_price": self.mark_price,
            "last_price": self.last_price,
            "state": self.state.name,
            "inventory_ratio": self.inventory_ratio,
            "position_qty": self.position_qty,
            "breakeven_price": self.breakeven_price,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "equity": self.equity,
            "margin_usage": self.margin_usage,
            "liq_distance": self.liq_distance,
            "outer_range": {
                "low": self.outer_range_low,
                "high": self.outer_range_high,
            },
            "core_zone": {
                "low": self.core_zone_low,
                "high": self.core_zone_high,
            } if self.core_zone_low is not None else None,
            "active_orders_summary": self.active_orders_summary.to_dict(),
            "atr": self.atr,
            "rv": self.rv,
            "vol_spike": self.vol_spike,
            "structural_break_confirmed": self.structural_break_confirmed,
            "outside_since": self.outside_since.isoformat() if self.outside_since else None,
            "config_hash": self.config_hash,
            "session_id": self.session_id,
        }

