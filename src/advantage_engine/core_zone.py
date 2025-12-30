"""
核心区域计算

计算 Adaptive Core Zone：
- 基于 fill_density 统计
- 计算 adv_score
- 选取覆盖 zone_cover% 成交的区域
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


@dataclass
class FillDensityCalculator:
    """成交密度计算器"""
    # 配置
    bin_size: float = 50.0  # 价格分箱大小
    T_zone_hours: int = 48  # 统计窗口
    
    # 成交记录：price_bin -> [(timestamp, qty)]
    _fill_records: Dict[int, List[Tuple[datetime, float]]] = field(default_factory=lambda: defaultdict(list))
    
    def record_fill(self, timestamp: datetime, price: float, qty: float) -> None:
        """记录成交"""
        bin_idx = int(price / self.bin_size)
        self._fill_records[bin_idx].append((timestamp, qty))
    
    def get_density(self, current_time: datetime) -> Dict[int, float]:
        """
        获取成交密度分布
        
        Returns:
            {bin_idx: total_qty}
        """
        cutoff = current_time.timestamp() - self.T_zone_hours * 3600
        
        density = {}
        for bin_idx, records in self._fill_records.items():
            # 过滤时间窗口内的记录
            recent = [qty for ts, qty in records if ts.timestamp() > cutoff]
            if recent:
                density[bin_idx] = sum(recent)
        
        return density
    
    def get_density_by_price(self, current_time: datetime) -> List[Tuple[float, float]]:
        """
        获取按价格排序的密度分布
        
        Returns:
            [(price, density), ...]
        """
        density = self.get_density(current_time)
        result = [
            (bin_idx * self.bin_size + self.bin_size / 2, qty)
            for bin_idx, qty in density.items()
        ]
        return sorted(result, key=lambda x: x[0])
    
    def cleanup_old_records(self, current_time: datetime) -> None:
        """清理过期记录"""
        cutoff = current_time.timestamp() - self.T_zone_hours * 3600
        
        for bin_idx in list(self._fill_records.keys()):
            self._fill_records[bin_idx] = [
                (ts, qty) for ts, qty in self._fill_records[bin_idx]
                if ts.timestamp() > cutoff
            ]
            if not self._fill_records[bin_idx]:
                del self._fill_records[bin_idx]


@dataclass
class CoreZoneCalculator:
    """
    核心区域计算器
    
    计算方法:
    1. 统计 fill_density
    2. 计算 adv_score = w1*fill_density + w2*inv_revert + w3*breakeven_gain
    3. 选取覆盖 zone_cover% 成交量的价格区间
    """
    # 配置
    zone_cover: float = 0.65  # 覆盖 65% 成交量
    zone_change_threshold: float = 0.10  # 变化 < 10% 保持不变
    bin_size: float = 50.0
    T_zone_hours: int = 48
    
    # 权重
    w1: float = 0.4  # fill_density
    w2: float = 0.3  # inv_revert_score
    w3: float = 0.3  # breakeven_gain
    
    # 密度计算器
    fill_density: FillDensityCalculator = field(default_factory=FillDensityCalculator)
    
    # 当前 core zone
    _core_low: Optional[float] = None
    _core_high: Optional[float] = None
    
    def __post_init__(self):
        self.fill_density = FillDensityCalculator(
            bin_size=self.bin_size,
            T_zone_hours=self.T_zone_hours,
        )
    
    def record_fill(self, timestamp: datetime, price: float, qty: float) -> None:
        """记录成交"""
        self.fill_density.record_fill(timestamp, price, qty)
    
    def calculate_core_zone(
        self,
        current_time: datetime,
        outer_range_low: float,
        outer_range_high: float,
        inv_revert_score: float = 0.5,
        breakeven_gain: float = 0.5,
    ) -> Tuple[float, float]:
        """
        计算核心区域
        
        Args:
            current_time: 当前时间
            outer_range_low: 外部区间下限
            outer_range_high: 外部区间上限
            inv_revert_score: 库存回中分数 [0, 1]
            breakeven_gain: breakeven 改善分数 [0, 1]
            
        Returns:
            (core_low, core_high)
        """
        # 获取密度分布
        density = self.fill_density.get_density(current_time)
        
        if not density:
            # 无数据，返回 outer_range
            return (outer_range_low, outer_range_high)
        
        # 计算总成交量
        total_qty = sum(density.values())
        
        if total_qty <= 0:
            return (outer_range_low, outer_range_high)
        
        # 按密度排序 bin
        sorted_bins = sorted(density.items(), key=lambda x: x[1], reverse=True)
        
        # 选取覆盖 zone_cover% 成交量的 bins
        covered_qty = 0
        selected_bins = []
        
        for bin_idx, qty in sorted_bins:
            selected_bins.append(bin_idx)
            covered_qty += qty
            
            if covered_qty / total_qty >= self.zone_cover:
                break
        
        if not selected_bins:
            return (outer_range_low, outer_range_high)
        
        # 计算 core zone 边界
        min_bin = min(selected_bins)
        max_bin = max(selected_bins)
        
        new_core_low = max(outer_range_low, min_bin * self.bin_size)
        new_core_high = min(outer_range_high, (max_bin + 1) * self.bin_size)
        
        # 检查变化是否显著
        if self._core_low is not None and self._core_high is not None:
            old_range = self._core_high - self._core_low
            new_range = new_core_high - new_core_low
            
            if old_range > 0:
                change_ratio = abs(new_range - old_range) / old_range
                
                # 变化不显著，保持原来的
                if change_ratio < self.zone_change_threshold:
                    return (self._core_low, self._core_high)
        
        # 更新 core zone
        self._core_low = new_core_low
        self._core_high = new_core_high
        
        return (new_core_low, new_core_high)
    
    def get_adv_score(
        self,
        price: float,
        current_time: datetime,
        inv_revert_score: float,
        breakeven_gain: float,
    ) -> float:
        """
        计算特定价格的优势分数
        
        Args:
            price: 价格
            current_time: 当前时间
            inv_revert_score: 库存回中分数
            breakeven_gain: breakeven 改善分数
            
        Returns:
            adv_score [0, 1]
        """
        # 获取该价格的密度分数
        density = self.fill_density.get_density(current_time)
        total_qty = sum(density.values()) or 1
        
        bin_idx = int(price / self.bin_size)
        bin_qty = density.get(bin_idx, 0)
        
        density_score = min(1.0, bin_qty / (total_qty * 0.1))  # 归一化
        
        # 综合分数
        return (
            self.w1 * density_score +
            self.w2 * inv_revert_score +
            self.w3 * breakeven_gain
        )
    
    @property
    def core_zone(self) -> Tuple[Optional[float], Optional[float]]:
        """当前 core zone"""
        return (self._core_low, self._core_high)
    
    def reset(self) -> None:
        """重置"""
        self._core_low = None
        self._core_high = None
        self.fill_density = FillDensityCalculator(
            bin_size=self.bin_size,
            T_zone_hours=self.T_zone_hours,
        )

