"""
Bitget 市场数据接口

提供:
- 无需 API Key 的公共数据获取
- 历史 K 线批量下载
- 数据缓存到 Parquet
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import ccxt
import pandas as pd


class BitgetMarketData:
    """
    Bitget 公共市场数据接口
    
    无需 API Key，只获取公共数据
    """
    
    def __init__(
        self,
        market_type: str = "swap",
        cache_dir: str = "data/cache",
    ):
        """
        初始化
        
        Args:
            market_type: "spot" | "swap"
            cache_dir: 缓存目录
        """
        self.market_type = market_type
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化 CCXT（无需 API Key）
        self.exchange = ccxt.bitget({
            'enableRateLimit': True,
            'options': {'defaultType': market_type},
        })
        
        # 加载市场信息
        print(f"[BitgetMarketData] Initializing ({market_type})...")
        self.exchange.load_markets()
        print(f"[BitgetMarketData] Loaded {len(self.exchange.markets)} markets")
    
    def _convert_symbol(self, symbol: str) -> str:
        """转换交易对格式"""
        if '/' in symbol:
            return symbol
        
        if self.market_type == 'swap':
            base_symbol = symbol.replace('USDT', '/USDT')
            return f"{base_symbol}:USDT"
        else:
            return symbol.replace('USDT', '/USDT')
    
    def get_klines(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        获取 K 线数据
        
        Args:
            symbol: 交易对 (BTCUSDT)
            timeframe: 时间周期 (1m, 5m, 15m, 1h, 4h, 1d)
            limit: 数量限制 (最大 1000)
            since: 开始时间戳 (毫秒)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                ccxt_symbol,
                timeframe=timeframe,
                limit=min(limit, 1000),
                since=since,
            )
            
            if not ohlcv:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            
            return df
            
        except Exception as e:
            print(f"[BitgetMarketData] Error fetching klines: {e}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    def fetch_historical_klines(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        progress: bool = True,
    ) -> pd.DataFrame:
        """
        批量获取历史 K 线数据
        
        自动分批请求，处理 API 限制
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            start: 开始时间
            end: 结束时间
            progress: 是否显示进度
            
        Returns:
            完整的 DataFrame
        """
        # 计算时间间隔（毫秒）
        tf_minutes = self._timeframe_to_minutes(timeframe)
        interval_ms = tf_minutes * 60 * 1000
        
        # 每次请求 500 根 K 线
        batch_size = 500
        batch_ms = batch_size * interval_ms
        
        all_data = []
        current_start = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        
        total_batches = (end_ms - current_start) // batch_ms + 1
        batch_count = 0
        
        if progress:
            print(f"[BitgetMarketData] Fetching {symbol} {timeframe} from {start} to {end}")
            print(f"[BitgetMarketData] Estimated {total_batches} batches...")
        
        while current_start < end_ms:
            batch_count += 1
            
            if progress and batch_count % 10 == 0:
                pct = min(100, batch_count / total_batches * 100)
                print(f"[BitgetMarketData] Progress: {pct:.1f}% ({batch_count}/{total_batches})")
            
            df = self.get_klines(
                symbol=symbol,
                timeframe=timeframe,
                limit=batch_size,
                since=current_start,
            )
            
            if df.empty:
                break
            
            all_data.append(df)
            
            # 移动到下一批
            last_ts = df['timestamp'].iloc[-1]
            if hasattr(last_ts, 'timestamp'):
                current_start = int(last_ts.timestamp() * 1000) + interval_ms
            else:
                current_start = int(last_ts / 1e6) + interval_ms
            
            # 尊重 API 限制
            time.sleep(0.1)
        
        if not all_data:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 合并所有数据
        result = pd.concat(all_data, ignore_index=True)
        
        # 去重并排序
        result = result.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        
        # 过滤时间范围
        result = result[
            (result['timestamp'] >= pd.Timestamp(start, tz='UTC')) &
            (result['timestamp'] <= pd.Timestamp(end, tz='UTC'))
        ]
        
        if progress:
            print(f"[BitgetMarketData] Fetched {len(result)} bars")
        
        return result.reset_index(drop=True)
    
    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """将时间周期转换为分钟"""
        mapping = {
            '1m': 1,
            '3m': 3,
            '5m': 5,
            '15m': 15,
            '30m': 30,
            '1h': 60,
            '2h': 120,
            '4h': 240,
            '6h': 360,
            '12h': 720,
            '1d': 1440,
            '1w': 10080,
        }
        return mapping.get(timeframe, 1)
    
    def download_and_cache(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        下载数据并缓存到 Parquet
        
        如果缓存存在且覆盖请求范围，直接返回缓存
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            start: 开始时间
            end: 结束时间
            force_refresh: 强制刷新缓存
            
        Returns:
            DataFrame
        """
        cache_file = self.cache_dir / f"{symbol}_{timeframe}_{self.market_type}.parquet"
        
        # 检查缓存
        if cache_file.exists() and not force_refresh:
            print(f"[BitgetMarketData] Loading from cache: {cache_file}")
            cached_df = pd.read_parquet(cache_file)
            cached_df['timestamp'] = pd.to_datetime(cached_df['timestamp'], utc=True)
            
            # 检查是否覆盖请求范围
            cached_start = cached_df['timestamp'].min()
            cached_end = cached_df['timestamp'].max()
            
            start_tz = pd.Timestamp(start, tz='UTC')
            end_tz = pd.Timestamp(end, tz='UTC')
            
            if cached_start <= start_tz and cached_end >= end_tz:
                # 缓存完全覆盖
                result = cached_df[
                    (cached_df['timestamp'] >= start_tz) &
                    (cached_df['timestamp'] <= end_tz)
                ]
                print(f"[BitgetMarketData] Cache hit: {len(result)} bars")
                return result.reset_index(drop=True)
            else:
                print(f"[BitgetMarketData] Cache partial, need to fetch more data")
        
        # 下载数据
        df = self.fetch_historical_klines(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            progress=True,
        )
        
        if df.empty:
            return df
        
        # 合并缓存（如果存在）
        if cache_file.exists():
            cached_df = pd.read_parquet(cache_file)
            cached_df['timestamp'] = pd.to_datetime(cached_df['timestamp'], utc=True)
            df = pd.concat([cached_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        
        # 保存缓存
        df.to_parquet(cache_file, index=False)
        print(f"[BitgetMarketData] Saved to cache: {cache_file}")
        
        # 过滤并返回
        start_tz = pd.Timestamp(start, tz='UTC')
        end_tz = pd.Timestamp(end, tz='UTC')
        
        result = df[
            (df['timestamp'] >= start_tz) &
            (df['timestamp'] <= end_tz)
        ]
        
        return result.reset_index(drop=True)
    
    def get_ticker(self, symbol: str) -> dict:
        """
        获取当前行情
        
        Returns:
            {last, bid, ask, high, low, volume, ...}
        """
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            return {
                'symbol': symbol,
                'last': ticker.get('last', 0),
                'bid': ticker.get('bid', 0),
                'ask': ticker.get('ask', 0),
                'high': ticker.get('high', 0),
                'low': ticker.get('low', 0),
                'volume': ticker.get('baseVolume', 0),
                'timestamp': datetime.now(),
            }
        except Exception as e:
            print(f"[BitgetMarketData] Error fetching ticker: {e}")
            return {}
    
    def get_mark_price(self, symbol: str) -> Optional[float]:
        """
        获取标记价格（仅合约）
        """
        if self.market_type != 'swap':
            return None
        
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            # 尝试获取标记价格
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            # 标记价格通常在 info 中
            info = ticker.get('info', {})
            mark_price = info.get('markPrice') or info.get('mark_price')
            
            if mark_price:
                return float(mark_price)
            
            # fallback 到 last price
            return ticker.get('last', 0)
            
        except Exception as e:
            print(f"[BitgetMarketData] Error fetching mark price: {e}")
            return None


def download_data_for_replay(
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    days: int = 7,
    market_type: str = "swap",
    cache_dir: str = "data/cache",
) -> pd.DataFrame:
    """
    便捷函数：下载回测数据
    
    Args:
        symbol: 交易对
        timeframe: 时间周期
        days: 天数
        market_type: 市场类型
        cache_dir: 缓存目录
        
    Returns:
        DataFrame
    """
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    
    client = BitgetMarketData(market_type=market_type, cache_dir=cache_dir)
    
    return client.download_and_cache(
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
    )


if __name__ == "__main__":
    # 测试
    print("Testing BitgetMarketData...")
    
    client = BitgetMarketData(market_type="swap")
    
    # 获取最近 100 根 1m K 线
    df = client.get_klines("BTCUSDT", "1m", limit=100)
    print(f"\nRecent klines: {len(df)} bars")
    print(df.tail())
    
    # 获取当前行情
    ticker = client.get_ticker("BTCUSDT")
    print(f"\nTicker: {ticker}")
    
    # 下载 1 天数据
    end = datetime.utcnow()
    start = end - timedelta(days=1)
    
    df = client.download_and_cache("BTCUSDT", "1m", start, end)
    print(f"\nDownloaded: {len(df)} bars")
    print(df.head())

