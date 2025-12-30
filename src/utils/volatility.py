"""
波动率计算模块

包含:
- ATRCalculator: 执行层波动率 (用于 spacing/buffer)
- RVCalculator: 判断层波动率 (用于 regime filter)
- VolSpikeDetector: vol_spike 信号生成
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional, Tuple

import numpy as np


@dataclass
class ATRCalculator:
    """
    ATR (Average True Range) 计算器
    
    用途（执行层）:
    - grid spacing
    - core zone 宽度
    - stop buffer
    - re-anchor 偏移
    
    公式:
    TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
    ATR = SMA(TR, period)
    """
    period: int = 14
    
    # 内部状态
    _tr_history: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    _prev_close: Optional[float] = None
    _current_atr: float = 0.0
    
    def __post_init__(self):
        self._tr_history = deque(maxlen=max(500, self.period * 10))
    
    def update(self, high: float, low: float, close: float) -> float:
        """
        更新 ATR
        
        Args:
            high: 最高价
            low: 最低价
            close: 收盘价
            
        Returns:
            当前 ATR 值
        """
        # 计算 True Range
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
        
        self._tr_history.append(tr)
        self._prev_close = close
        
        # 计算 ATR (SMA)
        if len(self._tr_history) >= self.period:
            recent_tr = list(self._tr_history)[-self.period:]
            self._current_atr = sum(recent_tr) / self.period
        elif len(self._tr_history) > 0:
            # 数据不足时使用已有数据
            self._current_atr = sum(self._tr_history) / len(self._tr_history)
        
        return self._current_atr
    
    @property
    def value(self) -> float:
        """当前 ATR 值"""
        return self._current_atr
    
    @property
    def ready(self) -> bool:
        """是否有足够数据"""
        return len(self._tr_history) >= self.period
    
    def reset(self) -> None:
        """重置计算器"""
        self._tr_history.clear()
        self._prev_close = None
        self._current_atr = 0.0


@dataclass
class RVCalculator:
    """
    RV (Realized Volatility) 计算器
    
    用途（判断层）:
    - regime filter (是否允许 grid 开启)
    - DEFENSIVE 触发
    - 参数组切换 (low-vol / high-vol preset)
    
    公式:
    returns = log(close / prev_close)
    RV = std(returns, period) * sqrt(annualization_factor)
    """
    period: int = 20
    annualization_factor: float = 365 * 24 * 60  # 1m bars per year
    
    # 内部状态
    _returns_history: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    _prev_close: Optional[float] = None
    _current_rv: float = 0.0
    
    def __post_init__(self):
        self._returns_history = deque(maxlen=max(500, self.period * 10))
    
    def update(self, close: float) -> float:
        """
        更新 RV
        
        Args:
            close: 收盘价
            
        Returns:
            当前 RV 值 (年化)
        """
        if self._prev_close is not None and self._prev_close > 0:
            # 计算对数收益率
            log_return = np.log(close / self._prev_close)
            self._returns_history.append(log_return)
            
            # 计算 RV
            if len(self._returns_history) >= self.period:
                recent_returns = list(self._returns_history)[-self.period:]
                std = np.std(recent_returns)
                self._current_rv = std * np.sqrt(self.annualization_factor)
        
        self._prev_close = close
        return self._current_rv
    
    @property
    def value(self) -> float:
        """当前 RV 值 (年化)"""
        return self._current_rv
    
    @property
    def ready(self) -> bool:
        """是否有足够数据"""
        return len(self._returns_history) >= self.period
    
    def reset(self) -> None:
        """重置计算器"""
        self._returns_history.clear()
        self._prev_close = None
        self._current_rv = 0.0


@dataclass
class VolSpikeDetector:
    """
    波动率冲击检测器
    
    触发条件 (NORMAL → DEFENSIVE):
    ATR(now) > ATR_MA * spike_mult
    
    恢复条件:
    ATR(now) < ATR_MA * clear_mult
    
    参数 (1m 回测默认):
    - atr_len: 14
    - atr_ma_len: 480 (= 8 小时)
    - spike_mult: 2.0
    - clear_mult: 1.3
    - cooldown_minutes: 60
    """
    atr_len: int = 14
    atr_ma_len: int = 480      # 1m: 480 = 8h, 5m: 96 = 8h
    spike_mult: float = 2.0
    clear_mult: float = 1.3
    cooldown_minutes: int = 60
    
    # 内部状态
    _atr_calculator: ATRCalculator = field(default_factory=lambda: ATRCalculator(period=14))
    _atr_history: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    _is_spike: bool = False
    _spike_since: Optional[datetime] = None
    _last_clear: Optional[datetime] = None
    
    def __post_init__(self):
        self._atr_calculator = ATRCalculator(period=self.atr_len)
        self._atr_history = deque(maxlen=max(1000, self.atr_ma_len * 2))
    
    def update(
        self,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        更新检测器状态
        
        Args:
            high: 最高价
            low: 最低价
            close: 收盘价
            timestamp: 时间戳
            
        Returns:
            (is_spike, reason)
        """
        # 更新 ATR
        current_atr = self._atr_calculator.update(high, low, close)
        self._atr_history.append(current_atr)
        
        # 计算 ATR 均线
        atr_ma = self._calculate_atr_ma()
        
        if atr_ma <= 0:
            return (self._is_spike, "insufficient_data")
        
        # 检查冷却期
        if self._last_clear is not None:
            cooldown_end = self._last_clear.timestamp() + self.cooldown_minutes * 60
            if timestamp.timestamp() < cooldown_end:
                return (self._is_spike, "in_cooldown")
        
        # 检测 spike
        if not self._is_spike:
            if current_atr > atr_ma * self.spike_mult:
                self._is_spike = True
                self._spike_since = timestamp
                return (True, f"vol_spike: ATR={current_atr:.2f} > MA*{self.spike_mult}={atr_ma * self.spike_mult:.2f}")
        else:
            # 检测恢复
            if current_atr < atr_ma * self.clear_mult:
                self._is_spike = False
                self._last_clear = timestamp
                return (False, f"vol_clear: ATR={current_atr:.2f} < MA*{self.clear_mult}={atr_ma * self.clear_mult:.2f}")
        
        return (self._is_spike, "no_change")
    
    def _calculate_atr_ma(self) -> float:
        """计算 ATR 均线"""
        if len(self._atr_history) < self.atr_ma_len:
            if len(self._atr_history) > 0:
                return sum(self._atr_history) / len(self._atr_history)
            return 0.0
        
        recent_atr = list(self._atr_history)[-self.atr_ma_len:]
        return sum(recent_atr) / self.atr_ma_len
    
    @property
    def is_spike(self) -> bool:
        """当前是否处于 spike 状态"""
        return self._is_spike
    
    @property
    def current_atr(self) -> float:
        """当前 ATR"""
        return self._atr_calculator.value
    
    @property
    def atr_ma(self) -> float:
        """ATR 均线"""
        return self._calculate_atr_ma()
    
    @property
    def spike_ratio(self) -> float:
        """当前 ATR / ATR_MA 比率"""
        ma = self.atr_ma
        if ma <= 0:
            return 0.0
        return self.current_atr / ma
    
    @property
    def ready(self) -> bool:
        """是否有足够数据"""
        return len(self._atr_history) >= self.atr_ma_len
    
    def reset(self) -> None:
        """重置检测器"""
        self._atr_calculator.reset()
        self._atr_history.clear()
        self._is_spike = False
        self._spike_since = None
        self._last_clear = None


def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    """
    计算 ATR (静态函数)
    
    Args:
        highs: 最高价列表
        lows: 最低价列表
        closes: 收盘价列表
        period: 周期
        
    Returns:
        ATR 值
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 0.0
    
    tr_list = []
    
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else 0.0
    
    return sum(tr_list[-period:]) / period

