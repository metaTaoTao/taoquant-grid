"""Bitget exchange client using CCXT."""

import ccxt
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime


class BitgetClient:
    """Bitget exchange client."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        market_type: str = "spot",
    ):
        """
        Initialize Bitget client.

        Parameters
        ----------
        api_key : str
            API key
        api_secret : str
            API secret
        passphrase : str
            API passphrase
        market_type : str
            Market type ("spot", "swap", etc.)
        """
        self.exchange = ccxt.bitget({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': market_type},
        })
        self.exchange.load_markets()

    def get_klines(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "BTCUSDT")
        timeframe : str
            Timeframe (e.g., "15m", "1h")
        limit : int
            Number of candles

        Returns
        -------
        pd.DataFrame
            OHLCV data
        """
        # Convert symbol format
        ccxt_symbol = self._convert_symbol(symbol)

        # Fetch OHLCV
        ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, limit=limit)

        # Convert to DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)

        return df

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
    ) -> Optional[Dict]:
        """
        Place limit order.

        Parameters
        ----------
        symbol : str
            Trading symbol
        side : str
            "buy" or "sell"
        price : float
            Order price
        quantity : float
            Order quantity

        Returns
        -------
        dict or None
            Order info
        """
        try:
            ccxt_symbol = self._convert_symbol(symbol)
            order = self.exchange.create_order(
                ccxt_symbol,
                'limit',
                side.lower(),
                quantity,
                price
            )
            return {
                'order_id': str(order.get('id', '')),
                'symbol': symbol,
                'side': side,
                'price': price,
                'quantity': quantity,
                'status': order.get('status', 'open'),
            }
        except Exception as e:
            print(f"[ERROR] Failed to place {side} order: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel order."""
        try:
            ccxt_symbol = self._convert_symbol(symbol)
            self.exchange.cancel_order(order_id, ccxt_symbol)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to cancel order {order_id}: {e}")
            return False

    def get_order_status(self, symbol: str, order_id: str) -> Optional[Dict]:
        """Get order status."""
        try:
            ccxt_symbol = self._convert_symbol(symbol)
            order = self.exchange.fetch_order(order_id, ccxt_symbol)
            return {
                'order_id': str(order.get('id', '')),
                'status': order.get('status', 'unknown'),
                'filled': float(order.get('filled', 0)),
                'average_price': float(order.get('average', 0)),
            }
        except Exception as e:
            print(f"[ERROR] Failed to get order status: {e}")
            return None

    def _convert_symbol(self, symbol: str) -> str:
        """Convert symbol format (BTCUSDT -> BTC/USDT)."""
        if '/' in symbol:
            return symbol
        # Simple conversion for common pairs
        return symbol.replace('USDT', '/USDT')
