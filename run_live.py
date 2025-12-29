#!/usr/bin/env python3
"""
TaoQuant Grid Trading - Live Trading Runner

Simple, clean, production-ready grid trading bot.

Usage:
    python run_live.py --balance 100 --leverage 10
"""

import os
import sys
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
import numpy as np
from dotenv import load_dotenv

from grid.core import StandardGridV2, GridOrder, GridOrderStatus
from grid.config import GridConfig
from exchange.bitget import BitgetClient
from utils.indicators import calculate_atr, auto_calculate_grid_count


class GridTrader:
    """Grid trading orchestrator."""

    def __init__(
        self,
        config: GridConfig,
        client: BitgetClient,
        symbol: str = "BTCUSDT",
        dry_run: bool = False,
    ):
        self.config = config
        self.client = client
        self.symbol = symbol
        self.dry_run = dry_run

        self.grid: Optional[StandardGridV2] = None
        self.grid_to_order_id: Dict[tuple, str] = {}
        self.shutdown = False

        # Detect market type from client
        market_type = getattr(client.exchange, 'options', {}).get('defaultType', 'unknown') if hasattr(client, 'exchange') else 'unknown'

        print(f"\n{'=' * 80}")
        print(f"TaoQuant Grid Trader - {'DRY RUN' if dry_run else 'LIVE TRADING'}")
        print(f"{'=' * 80}")
        print(f"Market: {market_type.upper()}")
        print(f"Symbol: {symbol}")
        print(f"Range: ${config.support:,.0f} - ${config.resistance:,.0f}")
        print(f"Balance: ${config.initial_cash:,.2f}")
        print(f"Leverage: {config.leverage}X")
        print(f"{'=' * 80}\n")

    def initialize(self):
        """Initialize grid."""
        print("Initializing grid...")

        # Fetch market data
        data = self.client.get_klines(self.symbol, timeframe="15m", limit=500)
        print(f"Loaded {len(data)} bars")

        # Calculate ATR for grid spacing
        atr = calculate_atr(data['high'], data['low'], data['close'], period=self.config.atr_period)
        atr_pct = atr / data['close']
        avg_spacing = (self.config.min_return + 2 * self.config.maker_fee +
                      self.config.volatility_k * atr_pct.mean())

        print(f"Average spacing: {avg_spacing:.4%}")

        # Auto-calculate grid count
        grid_count = auto_calculate_grid_count(
            self.config.support,
            self.config.resistance,
            avg_spacing
        )
        print(f"Auto-calculated grid count: {grid_count}")

        # Create grid
        total_investment = self.config.initial_cash * self.config.leverage
        self.grid = StandardGridV2(
            lower_price=self.config.support,
            upper_price=self.config.resistance,
            grid_count=grid_count,
            mode=self.config.mode,
            total_investment=total_investment,
            leverage=self.config.leverage,
            maker_fee=self.config.maker_fee,
        )

        # Initialize grid
        current_price = data['close'].iloc[-1]
        print(f"Current price: ${current_price:,.2f}")
        self.grid.initialize_grid(current_price=current_price)

        stats = self.grid.get_statistics()
        print(f"\nGrid initialized:")
        print(f"  Active buy orders: {stats['active_buy_orders']}")
        print(f"  Total grids: {stats['grid_count']}")

    def sync_orders_to_exchange(self):
        """Sync grid orders to exchange."""
        if self.grid is None:
            return

        print("\n[SYNC] Syncing orders to exchange...")

        # Cancel existing orders
        for order_id in list(self.grid_to_order_id.values()):
            self.client.cancel_order(self.symbol, order_id)
        self.grid_to_order_id.clear()

        # Place new orders
        for grid_level in self.grid.grid_levels:
            if grid_level.buy_order:
                if self.dry_run:
                    print(f"  [DRY RUN] Would place BUY: {grid_level.buy_order.size:.6f} @ ${grid_level.price:,.2f}")
                else:
                    result = self.client.place_limit_order(
                        symbol=self.symbol,
                        side="buy",
                        price=grid_level.price,
                        quantity=grid_level.buy_order.size,
                    )
                    if result:
                        self.grid_to_order_id[(grid_level.index, "buy")] = result['order_id']

            if grid_level.sell_order:
                if self.dry_run:
                    print(f"  [DRY RUN] Would place SELL: {grid_level.sell_order.size:.6f} @ ${grid_level.price:,.2f}")
                else:
                    result = self.client.place_limit_order(
                        symbol=self.symbol,
                        side="sell",
                        price=grid_level.price,
                        quantity=grid_level.sell_order.size,
                    )
                    if result:
                        self.grid_to_order_id[(grid_level.index, "sell")] = result['order_id']

        print(f"[SYNC] Placed {len(self.grid_to_order_id)} orders")

    def check_fills(self) -> List[GridOrder]:
        """Check for filled orders."""
        if self.grid is None:
            return []

        filled_orders = []

        if self.dry_run:
            # Simulate fills
            data = self.client.get_klines(self.symbol, timeframe="15m", limit=1)
            current_price = data['close'].iloc[-1]
            timestamp = datetime.now(timezone.utc)

            for grid_level in self.grid.grid_levels:
                if grid_level.buy_order and current_price <= grid_level.price:
                    order = grid_level.buy_order
                    order.status = GridOrderStatus.FILLED
                    order.filled_time = timestamp
                    filled_orders.append(order)
                    self.grid._on_buy_filled(grid_level.index, order, timestamp)

                if grid_level.sell_order and current_price >= grid_level.price:
                    order = grid_level.sell_order
                    order.status = GridOrderStatus.FILLED
                    order.filled_time = timestamp
                    filled_orders.append(order)
                    self.grid._on_sell_filled(grid_level.index, order, timestamp)

        else:
            # Check real orders
            to_remove = []
            for (grid_idx, direction), order_id in list(self.grid_to_order_id.items()):
                status = self.client.get_order_status(self.symbol, order_id)
                if status and status['status'] in ['closed', 'filled']:
                    grid_level = self.grid.grid_levels[grid_idx]
                    timestamp = datetime.now(timezone.utc)

                    if direction == "buy" and grid_level.buy_order:
                        order = grid_level.buy_order
                        order.status = GridOrderStatus.FILLED
                        order.filled_time = timestamp
                        filled_orders.append(order)
                        self.grid._on_buy_filled(grid_idx, order, timestamp)
                        to_remove.append((grid_idx, direction))

                    elif direction == "sell" and grid_level.sell_order:
                        order = grid_level.sell_order
                        order.status = GridOrderStatus.FILLED
                        order.filled_time = timestamp
                        filled_orders.append(order)
                        self.grid._on_sell_filled(grid_idx, order, timestamp)
                        to_remove.append((grid_idx, direction))

            for key in to_remove:
                del self.grid_to_order_id[key]

        return filled_orders

    def print_status(self):
        """Print current status."""
        if self.grid is None:
            return

        stats = self.grid.get_statistics()
        current_equity = self.config.initial_cash + stats['net_pnl']
        pnl_pct = stats['net_pnl'] / self.config.initial_cash

        print(f"\n{'=' * 80}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Status")
        print(f"{'=' * 80}")
        print(f"Equity: ${current_equity:,.2f} ({pnl_pct:+.2%})")
        print(f"Net PnL: ${stats['net_pnl']:,.2f}")
        print(f"Total Trades: {stats['total_trades']}")
        print(f"Position: {stats['net_position_btc']:.6f} BTC")
        print(f"Active Orders: {stats['active_buy_orders']} buy, {stats['active_sell_orders']} sell")
        print(f"{'=' * 80}\n")

    def run(self):
        """Run trading loop."""
        try:
            self.initialize()
            self.sync_orders_to_exchange()

            print(f"\n[LIVE] Starting trading loop (poll every {self.config.poll_interval_seconds}s)...")
            iteration = 0

            while not self.shutdown:
                iteration += 1

                # Check fills
                filled_orders = self.check_fills()
                if filled_orders:
                    print(f"\n[FILL] {len(filled_orders)} orders filled!")
                    self.sync_orders_to_exchange()

                # Print status every 10 iterations
                if iteration % 10 == 0:
                    self.print_status()

                time.sleep(self.config.poll_interval_seconds)

        except KeyboardInterrupt:
            print("\n[STOP] Interrupted by user")

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()

        finally:
            print("\n[CLEANUP] Cancelling all orders...")
            for order_id in list(self.grid_to_order_id.values()):
                self.client.cancel_order(self.symbol, order_id)

            if self.grid:
                self.print_status()


def main():
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()

    parser = argparse.ArgumentParser(description="TaoQuant Grid Trading")
    parser.add_argument("--support", type=float, default=76000.0, help="Support level")
    parser.add_argument("--resistance", type=float, default=97000.0, help="Resistance level")
    parser.add_argument("--balance", type=float, default=100.0, help="Initial balance")
    parser.add_argument("--leverage", type=float, default=10.0, help="Leverage")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading symbol")
    parser.add_argument("--market-type", type=str, default="swap", choices=["spot", "swap"], help="Market type (spot or swap/futures)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")

    args = parser.parse_args()

    # Load API credentials from environment
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    passphrase = os.getenv("BITGET_PASSPHRASE")

    if not all([api_key, api_secret, passphrase]):
        print("\n[ERROR] Missing API credentials!")
        print("Please check your .env file contains:")
        print("  BITGET_API_KEY")
        print("  BITGET_API_SECRET")
        print("  BITGET_PASSPHRASE")
        sys.exit(1)

    # Create configuration
    config = GridConfig(
        support=args.support,
        resistance=args.resistance,
        initial_cash=args.balance,
        leverage=args.leverage,
    )
    config.validate()

    # Create client
    client = BitgetClient(api_key, api_secret, passphrase, market_type=args.market_type)

    # Create trader
    trader = GridTrader(config, client, symbol=args.symbol, dry_run=args.dry_run)

    # Run
    trader.run()


if __name__ == "__main__":
    main()
