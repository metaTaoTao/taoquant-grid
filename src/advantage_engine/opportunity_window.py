"""
机会窗口评估

评估当前是否处于有效机会窗口：
- cycle_activity: 震荡循环活跃度
- inv_reversion_speed: 库存回中速度
- breakeven_slope: 成本改善速度
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional, Tuple


@dataclass
class CycleActivityMetrics:
    """震荡循环活跃度指标"""
    # 最近 N 个周期的成交
    recent_fill_count: int = 0
    recent_round_trip_count: int = 0  # 完整买卖周期
    
    # 时间窗口
    lookback_minutes: int = 480  # 8 小时
    
    # 历史记录
    _fill_timestamps: Deque[datetime] = field(default_factory=lambda: deque(maxlen=1000))
    _round_trip_timestamps: Deque[datetime] = field(default_factory=lambda: deque(maxlen=500))
    
    def record_fill(self, timestamp: datetime, side: str) -> None:
        """记录成交"""
        self._fill_timestamps.append(timestamp)
    
    def record_round_trip(self, timestamp: datetime) -> None:
        """记录完整周期"""
        self._round_trip_timestamps.append(timestamp)
    
    def get_activity_score(self, current_time: datetime) -> float:
        """
        计算活跃度分数 [0, 1]
        
        基于最近时间窗口内的成交频率
        """
        cutoff = current_time.timestamp() - self.lookback_minutes * 60
        
        # 计算窗口内成交数
        recent_fills = sum(1 for ts in self._fill_timestamps if ts.timestamp() > cutoff)
        recent_trips = sum(1 for ts in self._round_trip_timestamps if ts.timestamp() > cutoff)
        
        # 归一化：假设每小时 10 笔成交为满分
        expected_fills = self.lookback_minutes / 60 * 10
        fill_score = min(1.0, recent_fills / expected_fills)
        
        # 完整周期加分
        trip_bonus = min(0.3, recent_trips * 0.05)
        
        return min(1.0, fill_score + trip_bonus)


@dataclass
class InventoryReversionMetrics:
    """库存回中速度指标"""
    # 历史记录
    _ratio_history: Deque[Tuple[datetime, float]] = field(default_factory=lambda: deque(maxlen=500))
    
    # 配置
    lookback_minutes: int = 60
    target_ratio: float = 0.0  # 目标库存比率（中性）
    
    def record_ratio(self, timestamp: datetime, ratio: float) -> None:
        """记录库存比率"""
        self._ratio_history.append((timestamp, ratio))
    
    def get_reversion_score(self, current_time: datetime) -> float:
        """
        计算回中速度分数 [0, 1]
        
        越快回到中性越高分
        """
        if len(self._ratio_history) < 2:
            return 0.5  # 默认中等
        
        cutoff = current_time.timestamp() - self.lookback_minutes * 60
        
        # 获取窗口内的数据
        window_data = [
            (ts, r) for ts, r in self._ratio_history
            if ts.timestamp() > cutoff
        ]
        
        if len(window_data) < 2:
            return 0.5
        
        # 计算回中趋势
        start_ratio = window_data[0][1]
        end_ratio = window_data[-1][1]
        
        # 距离目标的变化
        start_dist = abs(start_ratio - self.target_ratio)
        end_dist = abs(end_ratio - self.target_ratio)
        
        if start_dist < 0.01:
            return 1.0  # 已经在中性附近
        
        # 回中比例
        improvement = (start_dist - end_dist) / start_dist
        
        # 转换为 [0, 1] 分数
        return max(0.0, min(1.0, 0.5 + improvement * 0.5))


@dataclass
class BreakevenSlopeMetrics:
    """成本改善速度指标"""
    # 历史记录
    _breakeven_history: Deque[Tuple[datetime, float]] = field(default_factory=lambda: deque(maxlen=500))
    
    # 配置
    lookback_minutes: int = 240  # 4 小时
    improvement_threshold: float = 0.001  # 0.1% 改善为显著
    
    def record_breakeven(self, timestamp: datetime, price: float) -> None:
        """记录盈亏平衡价"""
        if price > 0:
            self._breakeven_history.append((timestamp, price))
    
    def get_slope_score(self, current_time: datetime, current_price: float) -> float:
        """
        计算成本改善速度分数 [0, 1]
        
        breakeven 向有利方向移动越快越高分
        """
        if len(self._breakeven_history) < 2:
            return 0.5
        
        cutoff = current_time.timestamp() - self.lookback_minutes * 60
        
        # 获取窗口内的数据
        window_data = [
            (ts, be) for ts, be in self._breakeven_history
            if ts.timestamp() > cutoff
        ]
        
        if len(window_data) < 2:
            return 0.5
        
        # 计算 breakeven 变化
        start_be = window_data[0][1]
        end_be = window_data[-1][1]
        
        if start_be <= 0:
            return 0.5
        
        # 相对于当前价格的改善
        # 如果 breakeven 降低（对多头有利）或升高（对空头有利）
        be_change = (end_be - start_be) / start_be
        
        # 相对于当前价格的距离改善
        start_dist = abs(start_be - current_price) / current_price
        end_dist = abs(end_be - current_price) / current_price
        
        # 距离缩小为正面
        if end_dist < start_dist:
            improvement = (start_dist - end_dist) / start_dist
            return min(1.0, 0.5 + improvement * 0.5)
        else:
            deterioration = (end_dist - start_dist) / start_dist
            return max(0.0, 0.5 - deterioration * 0.5)


@dataclass
class OpportunityWindow:
    """
    机会窗口评估器
    
    综合评估：
    - cycle_activity: 震荡循环活跃度
    - inv_reversion_speed: 库存回中速度
    - breakeven_slope: 成本改善速度
    
    配置权重:
    - w1: cycle_activity (0.4)
    - w2: inv_reversion (0.3)
    - w3: breakeven_slope (0.3)
    """
    # 权重配置
    w1: float = 0.4  # cycle_activity
    w2: float = 0.3  # inv_reversion
    w3: float = 0.3  # breakeven_slope
    
    # 阈值
    valid_threshold: float = 0.4  # 综合分数 >= 0.4 为有效
    invalid_threshold: float = 0.25  # 综合分数 < 0.25 为无效
    
    # 超时
    timeout_hours: int = 72  # 72 小时无改善则超时
    
    # 子指标
    cycle_metrics: CycleActivityMetrics = field(default_factory=CycleActivityMetrics)
    reversion_metrics: InventoryReversionMetrics = field(default_factory=InventoryReversionMetrics)
    breakeven_metrics: BreakevenSlopeMetrics = field(default_factory=BreakevenSlopeMetrics)
    
    # 状态
    _is_valid: bool = True
    _last_valid_time: Optional[datetime] = None
    _current_score: float = 0.5
    
    def update(
        self,
        timestamp: datetime,
        inventory_ratio: float,
        breakeven_price: float,
        current_price: float,
    ) -> None:
        """更新指标"""
        self.reversion_metrics.record_ratio(timestamp, inventory_ratio)
        self.breakeven_metrics.record_breakeven(timestamp, breakeven_price)
        
        # 重新计算综合分数
        self._current_score = self._calculate_score(timestamp, current_price)
        
        # 更新有效状态
        if self._current_score >= self.valid_threshold:
            self._is_valid = True
            self._last_valid_time = timestamp
        elif self._current_score < self.invalid_threshold:
            self._is_valid = False
        
        # 检查超时
        if self._last_valid_time is not None:
            hours_since_valid = (timestamp - self._last_valid_time).total_seconds() / 3600
            if hours_since_valid >= self.timeout_hours:
                self._is_valid = False
    
    def record_fill(self, timestamp: datetime, side: str) -> None:
        """记录成交"""
        self.cycle_metrics.record_fill(timestamp, side)
    
    def record_round_trip(self, timestamp: datetime) -> None:
        """记录完整周期"""
        self.cycle_metrics.record_round_trip(timestamp)
    
    def _calculate_score(self, timestamp: datetime, current_price: float) -> float:
        """计算综合分数"""
        cycle_score = self.cycle_metrics.get_activity_score(timestamp)
        reversion_score = self.reversion_metrics.get_reversion_score(timestamp)
        breakeven_score = self.breakeven_metrics.get_slope_score(timestamp, current_price)
        
        return (
            self.w1 * cycle_score +
            self.w2 * reversion_score +
            self.w3 * breakeven_score
        )
    
    @property
    def is_valid(self) -> bool:
        """机会窗口是否有效"""
        return self._is_valid
    
    @property
    def score(self) -> float:
        """当前综合分数"""
        return self._current_score
    
    def get_component_scores(self, timestamp: datetime, current_price: float) -> dict:
        """获取各组件分数"""
        return {
            "cycle_activity": self.cycle_metrics.get_activity_score(timestamp),
            "inv_reversion": self.reversion_metrics.get_reversion_score(timestamp),
            "breakeven_slope": self.breakeven_metrics.get_slope_score(timestamp, current_price),
            "total": self._current_score,
        }

