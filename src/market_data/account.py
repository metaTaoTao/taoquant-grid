"""
账户状态模型

包含:
- AccountState: equity, margin_usage, liq_distance
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class AccountState:
    """
    账户状态
    
    包含:
    - equity: 权益
    - margin_usage: 保证金使用率
    - liq_distance: 强平距离
    - available: 可用余额
    """
    # 核心字段
    equity: float = 0.0               # 总权益 (USDT)
    available: float = 0.0            # 可用余额 (USDT)
    
    # 保证金相关
    margin_used: float = 0.0          # 已用保证金
    margin_ratio: float = 0.0         # 保证金率
    maintenance_margin: float = 0.0   # 维持保证金
    
    # 风险相关
    mark_price: float = 0.0           # 标记价格
    liq_price: Optional[float] = None # 强平价格
    
    # PnL
    unrealized_pnl: float = 0.0       # 未实现盈亏
    realized_pnl: float = 0.0         # 已实现盈亏
    
    # 时间戳
    last_update: Optional[datetime] = None
    
    @property
    def margin_usage(self) -> float:
        """
        保证金使用率
        
        计算: margin_used / equity
        """
        if self.equity <= 0:
            return 1.0  # 安全保护
        return min(1.0, self.margin_used / self.equity)
    
    @property
    def liq_distance(self) -> Optional[float]:
        """
        强平距离
        
        计算: abs(mark_price - liq_price) / mark_price
        单位: percentage [0, 1]
        
        v1 规则:
        - 如果数据获取失败，假设最坏情况（返回 None 触发 DATA_UNAVAILABLE）
        """
        if self.liq_price is None or self.mark_price <= 0:
            return None
        
        return abs(self.mark_price - self.liq_price) / self.mark_price
    
    @property
    def is_liq_distance_safe(self) -> bool:
        """
        强平距离是否安全
        
        阈值: 3% (0.03)
        """
        dist = self.liq_distance
        if dist is None:
            return False  # 数据不可用时假设不安全
        return dist >= 0.03
    
    @property
    def is_margin_safe(self) -> bool:
        """
        保证金率是否安全
        
        阈值: margin_ratio >= 1.2 (120%)
        """
        return self.margin_ratio >= 1.2
    
    def update_from_exchange(self, data: Dict[str, Any]) -> None:
        """
        从交易所数据更新
        
        Args:
            data: 交易所返回的账户数据
        """
        self.equity = float(data.get('equity', self.equity))
        self.available = float(data.get('available', self.available))
        self.margin_used = float(data.get('margin_used', data.get('marginUsed', self.margin_used)))
        self.margin_ratio = float(data.get('margin_ratio', data.get('marginRatio', self.margin_ratio)))
        self.maintenance_margin = float(data.get('maintenance_margin', self.maintenance_margin))
        self.unrealized_pnl = float(data.get('unrealized_pnl', data.get('unrealizedPnl', self.unrealized_pnl)))
        self.realized_pnl = float(data.get('realized_pnl', data.get('realizedPnl', self.realized_pnl)))
        self.last_update = datetime.now()
    
    def update_prices(self, mark_price: float, liq_price: Optional[float] = None) -> None:
        """
        更新价格信息
        
        Args:
            mark_price: 标记价格
            liq_price: 强平价格
        """
        self.mark_price = mark_price
        if liq_price is not None:
            self.liq_price = liq_price
        self.last_update = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "equity": self.equity,
            "available": self.available,
            "margin_used": self.margin_used,
            "margin_usage": self.margin_usage,
            "margin_ratio": self.margin_ratio,
            "maintenance_margin": self.maintenance_margin,
            "mark_price": self.mark_price,
            "liq_price": self.liq_price,
            "liq_distance": self.liq_distance,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountState":
        """从字典创建"""
        state = cls()
        state.equity = data.get("equity", 0.0)
        state.available = data.get("available", 0.0)
        state.margin_used = data.get("margin_used", 0.0)
        state.margin_ratio = data.get("margin_ratio", 0.0)
        state.maintenance_margin = data.get("maintenance_margin", 0.0)
        state.mark_price = data.get("mark_price", 0.0)
        state.liq_price = data.get("liq_price")
        state.unrealized_pnl = data.get("unrealized_pnl", 0.0)
        state.realized_pnl = data.get("realized_pnl", 0.0)
        
        if data.get("last_update"):
            state.last_update = datetime.fromisoformat(data["last_update"])
        
        return state


@dataclass
class PositionState:
    """
    持仓状态
    
    用于跟踪单个交易对的持仓
    """
    symbol: str = ""
    
    # 持仓数量
    position_qty: float = 0.0         # base currency (BTC)
    position_side: str = "none"       # "long" | "short" | "none"
    
    # 成本与价格
    avg_entry_price: float = 0.0      # 平均开仓价
    mark_price: float = 0.0           # 标记价格
    liq_price: Optional[float] = None # 强平价格
    
    # 保证金
    margin: float = 0.0               # 占用保证金
    leverage: float = 1.0             # 杠杆倍数
    
    # PnL
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    # 时间戳
    last_update: Optional[datetime] = None
    
    @property
    def notional_value(self) -> float:
        """
        持仓名义价值 (quote currency)
        
        公式: abs(position_qty) * mark_price
        """
        return abs(self.position_qty) * self.mark_price
    
    @property
    def is_long(self) -> bool:
        """是否多头"""
        return self.position_qty > 0
    
    @property
    def is_short(self) -> bool:
        """是否空头"""
        return self.position_qty < 0
    
    @property
    def has_position(self) -> bool:
        """是否有持仓"""
        return abs(self.position_qty) > 1e-8
    
    def update_from_exchange(self, data: Dict[str, Any]) -> None:
        """从交易所数据更新"""
        self.position_qty = float(data.get('position_qty', data.get('size', self.position_qty)))
        self.position_side = data.get('position_side', data.get('side', self.position_side))
        self.avg_entry_price = float(data.get('avg_entry_price', data.get('avgPrice', self.avg_entry_price)))
        self.mark_price = float(data.get('mark_price', data.get('markPrice', self.mark_price)))
        self.liq_price = data.get('liq_price', data.get('liquidationPrice', self.liq_price))
        if self.liq_price is not None:
            self.liq_price = float(self.liq_price)
        self.margin = float(data.get('margin', self.margin))
        self.leverage = float(data.get('leverage', self.leverage))
        self.unrealized_pnl = float(data.get('unrealized_pnl', data.get('unrealizedPnl', self.unrealized_pnl)))
        self.realized_pnl = float(data.get('realized_pnl', data.get('realizedPnl', self.realized_pnl)))
        self.last_update = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "position_qty": self.position_qty,
            "position_side": self.position_side,
            "notional_value": self.notional_value,
            "avg_entry_price": self.avg_entry_price,
            "mark_price": self.mark_price,
            "liq_price": self.liq_price,
            "margin": self.margin,
            "leverage": self.leverage,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }

