"""
库存与成本模型

核心概念：
- Inventory: 持仓状态（第一风险变量）
- Breakeven: 盈亏平衡价格（含费用，不含 funding）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Breakeven:
    """
    盈亏平衡价格计算
    
    公式：
    breakeven = (sum(fill_price * fill_qty) + total_fees + total_slippage) / total_qty
    
    用途边界：
    - risk 判定: 是
    - harvest 触发: 是
    - de-risk 评估: 是
    - re-anchor 约束: 是
    
    不含：
    - funding (单独核算，进入 PnL 报表与 risk budget)
    """
    # 累计成本
    total_cost: float = 0.0       # sum(fill_price * fill_qty)
    total_qty: float = 0.0        # 累计数量
    total_fees: float = 0.0       # 累计手续费
    total_slippage: float = 0.0   # 累计滑点
    
    @property
    def price(self) -> float:
        """盈亏平衡价格"""
        if self.total_qty == 0:
            return 0.0
        return (self.total_cost + self.total_fees + self.total_slippage) / self.total_qty
    
    @property
    def avg_cost_price(self) -> float:
        """平均成本价（不含费用）"""
        if self.total_qty == 0:
            return 0.0
        return self.total_cost / self.total_qty
    
    def update_on_fill(
        self,
        fill_price: float,
        fill_qty: float,
        fee: float,
        side: str,
        slippage: float = 0.0,
    ) -> None:
        """
        成交时更新盈亏平衡
        
        Args:
            fill_price: 成交价格
            fill_qty: 成交数量（正数）
            fee: 手续费
            side: "buy" | "sell"
            slippage: 滑点
        """
        if side == "buy":
            # 买入：增加持仓，更新成本
            self.total_cost += fill_price * fill_qty
            self.total_qty += fill_qty
            self.total_fees += fee
            self.total_slippage += slippage
        elif side == "sell":
            # 卖出：减少持仓，按比例减少成本
            if self.total_qty > 0:
                ratio = fill_qty / self.total_qty
                self.total_cost *= (1 - ratio)
                self.total_qty -= fill_qty
                # 费用和滑点按比例减少
                self.total_fees *= (1 - ratio)
                self.total_slippage *= (1 - ratio)
                # 新增的费用
                self.total_fees += fee
                self.total_slippage += slippage
    
    def reset(self) -> None:
        """重置"""
        self.total_cost = 0.0
        self.total_qty = 0.0
        self.total_fees = 0.0
        self.total_slippage = 0.0


@dataclass
class Inventory:
    """
    库存状态
    
    重要：
    - position_qty: base currency (BTC)
    - notional_value: quote currency (USDT)
    - inventory_ratio: [0, 1]，分子分母都是 quote notional
    
    单位体系：
    - position_qty: BTC
    - max_inventory_notional: USDT
    - inventory_ratio = abs(position_qty * mark_price) / max_inventory_notional
    """
    # 当前持仓
    position_qty: float = 0.0     # base currency (BTC)
    
    # 配置
    max_inventory_notional: float = 10000.0  # quote currency (USDT)
    
    # 计算用
    _last_mark_price: float = 0.0
    _last_update: Optional[datetime] = None
    
    # 历史记录（用于计算 slope）
    _ratio_history: List[tuple] = field(default_factory=list)
    
    @property
    def notional_value(self) -> float:
        """持仓名义价值（quote currency）"""
        return abs(self.position_qty) * self._last_mark_price
    
    @property
    def inventory_ratio(self) -> float:
        """库存比率 [0, 1]"""
        if self.max_inventory_notional <= 0:
            return 1.0  # 安全保护
        return min(1.0, self.notional_value / self.max_inventory_notional)
    
    @property
    def is_long(self) -> bool:
        """是否多头"""
        return self.position_qty > 0
    
    @property
    def is_short(self) -> bool:
        """是否空头"""
        return self.position_qty < 0
    
    def update_price(self, mark_price: float, timestamp: datetime) -> None:
        """更新标记价格"""
        self._last_mark_price = mark_price
        self._last_update = timestamp
        
        # 记录历史（用于计算 slope）
        self._ratio_history.append((timestamp, self.inventory_ratio))
        # 只保留最近 100 条
        if len(self._ratio_history) > 100:
            self._ratio_history = self._ratio_history[-100:]
    
    def update_on_fill(
        self,
        fill_qty: float,
        side: str,
        mark_price: float,
        timestamp: datetime,
    ) -> None:
        """
        成交时更新库存
        
        Args:
            fill_qty: 成交数量（正数）
            side: "buy" | "sell"
            mark_price: 标记价格
            timestamp: 时间戳
        """
        if side == "buy":
            self.position_qty += fill_qty
        elif side == "sell":
            self.position_qty -= fill_qty
        
        self.update_price(mark_price, timestamp)
    
    def inventory_slope(self, lookback_minutes: int = 60) -> float:
        """
        计算库存变化速度
        
        Args:
            lookback_minutes: 回望时间（分钟）
            
        Returns:
            ratio 变化速度（每分钟）
        """
        if len(self._ratio_history) < 2:
            return 0.0
        
        now = self._ratio_history[-1][0]
        cutoff = now.timestamp() - lookback_minutes * 60
        
        # 找到 lookback 范围内的第一个点
        for i, (ts, ratio) in enumerate(self._ratio_history):
            if ts.timestamp() >= cutoff:
                if i == len(self._ratio_history) - 1:
                    return 0.0
                start_ratio = ratio
                start_time = ts
                end_ratio = self._ratio_history[-1][1]
                end_time = self._ratio_history[-1][0]
                
                time_diff = (end_time.timestamp() - start_time.timestamp()) / 60
                if time_diff <= 0:
                    return 0.0
                return (end_ratio - start_ratio) / time_diff
        
        return 0.0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "position_qty": self.position_qty,
            "notional_value": self.notional_value,
            "inventory_ratio": self.inventory_ratio,
            "max_inventory_notional": self.max_inventory_notional,
            "last_mark_price": self._last_mark_price,
            "is_long": self.is_long,
        }

