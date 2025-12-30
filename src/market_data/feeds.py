"""
行情数据源

包含:
- BarFeed: 支持 API 拉取 + 本地 Parquet 缓存
- ReplayMarketData: 回测数据回放
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.models.events import (
    BaseEvent,
    EventType,
    BarOpenEvent,
    BarCloseEvent,
    PriceUpdateEvent,
)
from src.interfaces import IMarketDataSource
from src.utils.timeutils import generate_session_id


class BarFeed:
    """
    K线数据源
    
    支持:
    - API 拉取历史数据
    - 本地 Parquet 缓存
    - 增量更新
    """
    
    def __init__(
        self,
        cache_dir: str = "data/cache",
        api_client: Optional[object] = None,
    ):
        """
        初始化 BarFeed
        
        Args:
            cache_dir: 缓存目录
            api_client: API 客户端（可选，用于拉取数据）
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_client = api_client
        
        # 内存缓存
        self._bars_cache: Dict[str, pd.DataFrame] = {}
    
    def _cache_path(self, symbol: str, bar_tf: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{symbol}_{bar_tf}.parquet"
    
    def load_bars(
        self,
        symbol: str,
        bar_tf: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """
        加载 K 线数据
        
        优先从缓存加载，缺失部分从 API 拉取
        
        Args:
            symbol: 交易对
            bar_tf: K线周期
            start: 开始时间
            end: 结束时间
            
        Returns:
            DataFrame with columns: [timestamp, open, high, low, close, volume]
        """
        cache_key = f"{symbol}_{bar_tf}"
        cache_path = self._cache_path(symbol, bar_tf)
        
        # 尝试从缓存加载
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # 检查是否覆盖请求范围
            cached_start = df['timestamp'].min()
            cached_end = df['timestamp'].max()
            
            if cached_start <= start and cached_end >= end:
                # 缓存完全覆盖
                mask = (df['timestamp'] >= start) & (df['timestamp'] <= end)
                return df[mask].copy()
            
            # 需要增量拉取
            if self.api_client is not None:
                # 拉取缺失数据并合并
                df = self._fetch_and_merge(df, symbol, bar_tf, start, end)
        else:
            # 无缓存，从 API 拉取
            if self.api_client is not None:
                df = self._fetch_from_api(symbol, bar_tf, start, end)
            else:
                # 无 API 客户端，返回空 DataFrame
                df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 过滤时间范围
        if not df.empty:
            mask = (df['timestamp'] >= start) & (df['timestamp'] <= end)
            df = df[mask].copy()
        
        return df
    
    def _fetch_from_api(
        self,
        symbol: str,
        bar_tf: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """从 API 拉取数据"""
        if self.api_client is None:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 调用 API 客户端的方法获取历史数据
        # 这里假设 api_client 有 get_historical_klines 方法
        try:
            if hasattr(self.api_client, 'get_historical_klines'):
                bars = self.api_client.get_historical_klines(
                    symbol=symbol,
                    interval=bar_tf,
                    start_time=int(start.timestamp() * 1000),
                    end_time=int(end.timestamp() * 1000),
                )
                
                if bars:
                    df = pd.DataFrame(bars)
                    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    
                    # 保存到缓存
                    self._save_to_cache(symbol, bar_tf, df)
                    
                    return df
        except Exception as e:
            print(f"[BarFeed] API fetch failed: {e}")
        
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    def _fetch_and_merge(
        self,
        existing_df: pd.DataFrame,
        symbol: str,
        bar_tf: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """拉取缺失数据并合并"""
        cached_start = existing_df['timestamp'].min()
        cached_end = existing_df['timestamp'].max()
        
        dfs_to_merge = [existing_df]
        
        # 拉取前面缺失的数据
        if start < cached_start:
            df_before = self._fetch_from_api(symbol, bar_tf, start, cached_start)
            if not df_before.empty:
                dfs_to_merge.append(df_before)
        
        # 拉取后面缺失的数据
        if end > cached_end:
            df_after = self._fetch_from_api(symbol, bar_tf, cached_end, end)
            if not df_after.empty:
                dfs_to_merge.append(df_after)
        
        # 合并并去重
        if len(dfs_to_merge) > 1:
            df = pd.concat(dfs_to_merge, ignore_index=True)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            # 更新缓存
            self._save_to_cache(symbol, bar_tf, df)
            
            return df
        
        return existing_df
    
    def _save_to_cache(self, symbol: str, bar_tf: str, df: pd.DataFrame) -> None:
        """保存到缓存"""
        cache_path = self._cache_path(symbol, bar_tf)
        df.to_parquet(cache_path, index=False)
    
    def load_from_csv(
        self,
        csv_path: str,
        symbol: str,
        bar_tf: str,
    ) -> pd.DataFrame:
        """
        从 CSV 文件加载数据
        
        用于本地测试数据
        
        Args:
            csv_path: CSV 文件路径
            symbol: 交易对
            bar_tf: K线周期
            
        Returns:
            DataFrame
        """
        df = pd.read_csv(csv_path)
        
        # 标准化列名
        column_mapping = {
            'time': 'timestamp',
            'date': 'timestamp',
            'datetime': 'timestamp',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }
        df = df.rename(columns=column_mapping)
        
        # 确保时间列是 datetime 类型
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # 保存到缓存
        self._save_to_cache(symbol, bar_tf, df)
        
        return df


class ReplayMarketData(IMarketDataSource):
    """
    回测数据回放器
    
    实现 IMarketDataSource 接口，用于回测模式
    """
    
    def __init__(
        self,
        bar_feed: BarFeed,
        session_id: Optional[str] = None,
    ):
        """
        初始化回放器
        
        Args:
            bar_feed: K线数据源
            session_id: 会话 ID
        """
        self.bar_feed = bar_feed
        self.session_id = session_id or generate_session_id()
        
        # 回放状态
        self._symbol: Optional[str] = None
        self._bar_tf: Optional[str] = None
        self._bars: Optional[pd.DataFrame] = None
        self._current_idx: int = 0
        self._is_running: bool = False
        
        # 当前价格
        self._current_mark_price: float = 0.0
        self._current_last_price: float = 0.0
        
        # 事件回调
        self._event_callback: Optional[Callable[[BaseEvent], None]] = None
    
    def subscribe(self, symbol: str, bar_tf: str) -> None:
        """订阅行情"""
        self._symbol = symbol
        self._bar_tf = bar_tf
    
    def unsubscribe(self, symbol: str) -> None:
        """取消订阅"""
        if self._symbol == symbol:
            self._symbol = None
            self._bars = None
    
    def get_current_price(self, symbol: str) -> Tuple[float, float]:
        """获取当前价格"""
        return (self._current_mark_price, self._current_last_price)
    
    def get_latest_bar(self, symbol: str) -> Optional[BarCloseEvent]:
        """获取最新 K 线"""
        if self._bars is None or self._current_idx == 0:
            return None
        
        row = self._bars.iloc[self._current_idx - 1]
        return self._row_to_bar_close_event(row)
    
    def set_event_callback(self, callback: Callable[[BaseEvent], None]) -> None:
        """设置事件回调"""
        self._event_callback = callback
    
    def start(self) -> None:
        """启动数据源"""
        self._is_running = True
    
    def stop(self) -> None:
        """停止数据源"""
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running
    
    def load_data(
        self,
        start: datetime,
        end: datetime,
    ) -> int:
        """
        加载回测数据
        
        Args:
            start: 开始时间
            end: 结束时间
            
        Returns:
            加载的 bar 数量
        """
        if self._symbol is None or self._bar_tf is None:
            raise ValueError("Must subscribe before loading data")
        
        self._bars = self.bar_feed.load_bars(
            self._symbol,
            self._bar_tf,
            start,
            end,
        )
        self._current_idx = 0
        
        return len(self._bars)
    
    def load_from_dataframe(self, df: pd.DataFrame) -> int:
        """
        从 DataFrame 加载数据
        
        Args:
            df: 数据 DataFrame
            
        Returns:
            加载的 bar 数量
        """
        self._bars = df.copy()
        self._current_idx = 0
        return len(self._bars)
    
    def has_next(self) -> bool:
        """是否还有下一根 bar"""
        if self._bars is None:
            return False
        return self._current_idx < len(self._bars)
    
    def next_bar(self) -> Optional[BarCloseEvent]:
        """
        推进到下一根 bar
        
        Returns:
            BarCloseEvent 或 None
        """
        if not self.has_next():
            return None
        
        row = self._bars.iloc[self._current_idx]
        self._current_idx += 1
        
        # 更新当前价格
        self._current_mark_price = float(row['close'])
        self._current_last_price = float(row['close'])
        
        # 创建事件
        event = self._row_to_bar_close_event(row)
        
        # 触发回调
        if self._event_callback is not None:
            self._event_callback(event)
        
        return event
    
    def _row_to_bar_close_event(self, row: pd.Series) -> BarCloseEvent:
        """将 DataFrame 行转换为 BarCloseEvent"""
        timestamp = row['timestamp']
        if isinstance(timestamp, str):
            timestamp = pd.to_datetime(timestamp)
        
        return BarCloseEvent(
            event_type=EventType.BAR_CLOSE,
            timestamp=datetime.now(),  # 事件处理时间
            session_id=self.session_id,
            symbol=self._symbol or "",
            bar_tf=self._bar_tf or "1m",
            bar_time=timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row.get('volume', 0)),
            mark_price=float(row['close']),  # 回测中 mark_price = close
        )
    
    def replay_all(self) -> List[BarCloseEvent]:
        """
        回放所有 bar
        
        Returns:
            所有 BarCloseEvent 列表
        """
        events = []
        while self.has_next():
            event = self.next_bar()
            if event:
                events.append(event)
        return events
    
    @property
    def total_bars(self) -> int:
        """总 bar 数"""
        return len(self._bars) if self._bars is not None else 0
    
    @property
    def current_bar_index(self) -> int:
        """当前 bar 索引"""
        return self._current_idx
    
    @property
    def progress(self) -> float:
        """回放进度 [0, 1]"""
        if self.total_bars == 0:
            return 0.0
        return self._current_idx / self.total_bars

