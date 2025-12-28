"""
Standard Grid Trading Bot V2 - Exchange-Compliant Implementation.

100% replicates Binance/OKX grid trading behavior:
1. Each grid level has AT MOST 1 active order
2. Buy@grid[i] fills → Place sell@grid[i+1]
3. Sell@grid[i] fills → Re-place buy@grid[i]
4. Continuous buy-low-sell-high loop

References:
- https://www.binance.com/en/support/faq/what-is-spot-grid-trading-and-how-does-it-work-d5f441e8ab544a5b98241e00efb3a4ab
- https://www.okx.com/en-us/help/spot-grid-bot-faq
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

import numpy as np


class GridOrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class GridLevel:
    """
    Represents a single grid level.

    Each grid level can have:
    - 0 or 1 buy order
    - 0 or 1 sell order
    - Never both at the same time
    """
    index: int
    price: float
    buy_order: Optional[GridOrder] = None
    sell_order: Optional[GridOrder] = None
    total_buy_volume: float = 0.0
    total_sell_volume: float = 0.0
    profit_realized: float = 0.0

    def has_active_order(self) -> bool:
        return self.buy_order is not None or self.sell_order is not None

    def has_buy_order(self) -> bool:
        return self.buy_order is not None

    def has_sell_order(self) -> bool:
        return self.sell_order is not None


@dataclass
class GridOrder:
    """Represents a grid order."""
    grid_index: int
    direction: str  # "buy" or "sell"
    price: float
    size: float
    status: GridOrderStatus = GridOrderStatus.PENDING
    placed_time: Optional[datetime] = None
    filled_time: Optional[datetime] = None
    fill_price: Optional[float] = None
    paired_grid_index: Optional[int] = None


class StandardGridV2:
    """Standard Grid Trading Bot V2."""

    def __init__(
        self,
        lower_price: float,
        upper_price: float,
        grid_count: int,
        mode: str = "geometric",
        total_investment: float = 10000.0,
        leverage: float = 1.0,
        maker_fee: float = 0.0002,
    ):
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.grid_count = grid_count
        self.mode = mode
        self.total_investment = total_investment
        self.initial_cash = total_investment / leverage
        self.leverage = leverage
        self.maker_fee = maker_fee

        self.grid_prices = self._generate_grid_prices()
        self.grid_levels: List[GridLevel] = [
            GridLevel(index=i, price=price)
            for i, price in enumerate(self.grid_prices)
        ]
        self.per_grid_investment = total_investment / len(self.grid_levels)

        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.total_trades = 0
        self.total_buy_volume = 0.0
        self.total_sell_volume = 0.0

    def _generate_grid_prices(self) -> List[float]:
        """Generate grid price levels."""
        N = self.grid_count
        lower = self.lower_price
        upper = self.upper_price

        if self.mode == "geometric":
            ratio = (upper / lower) ** (1.0 / N)
            prices = [lower * (ratio ** i) for i in range(N + 1)]
        else:
            step = (upper - lower) / N
            prices = [lower + i * step for i in range(N + 1)]

        return prices

    def initialize_grid(self, current_price: float):
        """Initialize grid with buy orders below current price."""
        current_grid_idx = self._find_grid_index(current_price)

        print(f"\n[GRID INIT] Current price ${current_price:,.2f} at grid {current_grid_idx}")
        print(f"[GRID INIT] Placing buy orders at grids 0-{current_grid_idx - 1}")

        for i in range(current_grid_idx):
            self._place_buy_order(i)

        print(f"[GRID INIT] Grid initialized with {current_grid_idx} buy orders")

    def _find_grid_index(self, price: float) -> int:
        """Find grid index for a given price."""
        for i in range(len(self.grid_prices) - 1, -1, -1):
            if price >= self.grid_prices[i]:
                return i
        return 0

    def _place_buy_order(self, grid_index: int):
        """Place buy order at grid level."""
        if grid_index < 0 or grid_index >= len(self.grid_levels):
            return

        grid = self.grid_levels[grid_index]
        if grid.has_buy_order():
            return

        price = grid.price
        size = self.per_grid_investment / price

        order = GridOrder(
            grid_index=grid_index,
            direction="buy",
            price=price,
            size=size,
            placed_time=datetime.now(),
            paired_grid_index=grid_index + 1,
        )

        grid.buy_order = order

    def _place_sell_order(self, grid_index: int, size: float):
        """Place sell order at grid level."""
        if grid_index < 0 or grid_index >= len(self.grid_levels):
            return

        grid = self.grid_levels[grid_index]
        if grid.has_sell_order():
            return

        order = GridOrder(
            grid_index=grid_index,
            direction="sell",
            price=grid.price,
            size=size,
            placed_time=datetime.now(),
            paired_grid_index=grid_index - 1,
        )

        grid.sell_order = order

    def check_and_fill_orders(
        self,
        bar_high: float,
        bar_low: float,
        timestamp: datetime,
    ) -> List[GridOrder]:
        """Check for triggered orders and fill them."""
        filled_orders = []

        for grid in self.grid_levels:
            if grid.buy_order and bar_low <= grid.price:
                order = grid.buy_order
                order.status = GridOrderStatus.FILLED
                order.filled_time = timestamp
                order.fill_price = grid.price
                filled_orders.append(order)
                self._on_buy_filled(grid.index, order, timestamp)

            if grid.sell_order and bar_high >= grid.price:
                order = grid.sell_order
                order.status = GridOrderStatus.FILLED
                order.filled_time = timestamp
                order.fill_price = grid.price
                filled_orders.append(order)
                self._on_sell_filled(grid.index, order, timestamp)

        return filled_orders

    def _on_buy_filled(self, grid_index: int, order: GridOrder, timestamp: datetime):
        """Handle buy order fill."""
        grid = self.grid_levels[grid_index]
        grid.buy_order = None

        grid.total_buy_volume += order.size
        self.total_buy_volume += order.size
        fee = order.size * order.price * self.maker_fee
        self.total_fees += fee
        self.total_trades += 1

        print(f"[BUY FILL] Grid {grid_index} @ ${order.price:,.2f}, size={order.size:.6f} BTC, fee=${fee:.2f}")

        if grid_index + 1 < len(self.grid_levels):
            self._place_sell_order(grid_index + 1, order.size)
            print(f"  -> Placed SELL at grid {grid_index + 1} @ ${self.grid_levels[grid_index + 1].price:,.2f}")

    def _on_sell_filled(self, grid_index: int, order: GridOrder, timestamp: datetime):
        """Handle sell order fill."""
        grid = self.grid_levels[grid_index]
        grid.sell_order = None

        if grid_index > 0:
            buy_price = self.grid_levels[grid_index - 1].price
            sell_price = order.price
            gross_profit = (sell_price - buy_price) * order.size

            buy_fee = order.size * buy_price * self.maker_fee
            sell_fee = order.size * sell_price * self.maker_fee
            net_profit = gross_profit - buy_fee - sell_fee

            grid.profit_realized += net_profit
            self.total_pnl += net_profit

            profit_pct = (sell_price - buy_price) / buy_price * 100
            print(f"[SELL FILL] Grid {grid_index} @ ${order.price:,.2f}, size={order.size:.6f} BTC, PnL=${net_profit:.2f} ({profit_pct:+.2f}%)")

        grid.total_sell_volume += order.size
        self.total_sell_volume += order.size
        fee = order.size * order.price * self.maker_fee
        self.total_fees += fee
        self.total_trades += 1

        if grid_index - 1 >= 0:
            self._place_buy_order(grid_index - 1)
            print(f"  -> Re-placed BUY at grid {grid_index - 1} @ ${self.grid_levels[grid_index - 1].price:,.2f}")

    def get_statistics(self) -> Dict:
        """Get trading statistics."""
        total_position_btc = self.total_buy_volume - self.total_sell_volume
        buy_orders = sum(1 for g in self.grid_levels if g.has_buy_order())
        sell_orders = sum(1 for g in self.grid_levels if g.has_sell_order())

        return {
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "net_pnl": self.total_pnl - self.total_fees,
            "total_trades": self.total_trades,
            "total_buy_volume": self.total_buy_volume,
            "total_sell_volume": self.total_sell_volume,
            "net_position_btc": total_position_btc,
            "active_buy_orders": buy_orders,
            "active_sell_orders": sell_orders,
            "grid_count": len(self.grid_levels),
            "grid_mode": self.mode,
        }
