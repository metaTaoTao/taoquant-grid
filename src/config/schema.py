"""
配置数据结构定义
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


@dataclass
class TraderInputConfig:
    """交易员输入配置"""
    outer_range_low: float
    outer_range_high: float
    trend_gate: bool = True
    allow_mild_bias: bool = True
    mild_bias_cap: float = 0.20


@dataclass
class RiskConfig:
    """风控配置"""
    inv_warn: float = 0.55
    inv_damage: float = 0.70
    inv_stop: float = 0.85
    inv_back_to_normal: float = 0.40
    
    inv_cap_pct: float = 0.30
    max_inventory_notional: Optional[float] = None
    
    margin_cap: float = 0.80
    max_dd: float = 0.15
    
    liq_distance_threshold: float = 0.03
    api_fault_max_consecutive: int = 3
    data_stale_seconds: int = 30


@dataclass
class PriceBoundaryConfig:
    """价格触边配置"""
    price_type: str = "mark_price"
    buffer_atr_mult: float = 0.5
    check_timing: str = "instant"
    min_state_hold_minutes: int = 15


@dataclass
class VolatilityConfig:
    """波动率配置"""
    atr_len: int = 14
    atr_ma_len_1m: int = 480
    atr_ma_len_5m: int = 96
    spike_mult: float = 2.0
    clear_mult: float = 1.3
    cooldown_minutes: int = 60


@dataclass
class StructuralStopConfig:
    """结构止损配置"""
    atr_buffer_mult: float = 1.0
    confirm_minutes: int = 240
    timing_method: str = "timestamp_diff"
    accumulation: str = "continuous_only"
    reset_on_return: str = "immediate"


@dataclass
class ZoneConfig:
    """Zone 配置"""
    T_zone_hours: int = 48
    T_window_hours: int = 48
    bin_size: float = 50.0
    zone_cover: float = 0.65
    zone_change_threshold: float = 0.10
    w1: float = 0.4
    w2: float = 0.3
    w3: float = 0.3


@dataclass
class GridConfig:
    """网格配置"""
    bar_tf: str = "1m"
    base_step_method: str = "atr"
    core_compress_factor: float = 0.7
    buffer_expand_factor: float = 1.3
    N_buy_active: int = 5
    M_sell_active: int = 5
    edge_band_atr_mult: float = 1.5
    edge_decay_factor: float = 0.7
    refresh_delay_ms: int = 500
    refresh_delay_ms_defensive: int = 2000


@dataclass
class SkewConfig:
    """Skew 配置"""
    inv_skew_max: float = 0.40
    skew_max: float = 0.25


@dataclass
class DeRiskConfig:
    """DeRisk 配置"""
    cycle_efficiency_drop_threshold: float = 0.30
    breakeven_flat_threshold: float = 0.001
    opportunity_timeout_hours: int = 72
    N_fail: int = 3


@dataclass
class HarvestConfig:
    """Harvest 配置"""
    exit_inventory_ratio: float = 0.35
    require_opportunity_valid_minutes: int = 60


@dataclass
class ReanchorConfig:
    """Re-anchor 配置"""
    offset_atr_mult: float = 1.0
    cooldown_hours: int = 24
    max_per_day: int = 2
    range_shrink_ratio: float = 0.8
    spacing_expand_ratio: float = 1.2
    inventory_shrink_ratio: float = 0.8


@dataclass
class ControlLoopConfig:
    """Control Loop 配置"""
    interval: str = "4h"


@dataclass
class OrderManagementConfig:
    """订单管理配置"""
    min_order_lifetime_seconds: int = 30
    price_change_threshold_atr_mult: float = 0.1
    cancel_rate_limit_per_minute: int = 10
    freeze_duration_seconds: int = 60


@dataclass
class FeesConfig:
    """费用配置"""
    maker_fee_bps: int = 2
    taker_fee_bps: int = 6
    default_side: str = "maker"


@dataclass
class PartialFillConfig:
    """部分成交配置"""
    enabled: bool = True
    ratio_min: float = 0.3
    ratio_max: float = 0.7
    mode: str = "random"


@dataclass
class FillOrderConfig:
    """成交顺序配置"""
    rule: str = "inner_first"
    max_fills_per_bar: int = 2


@dataclass
class FillPriceConfig:
    """成交价格配置"""
    rule: str = "limit_price_plus_slippage"
    slippage_bps: int = 5
    slippage_mode: str = "fixed"


@dataclass
class CancelSimulationConfig:
    """撤单模拟配置"""
    allow_fail: bool = True
    fail_probability: float = 0.05
    delay_bars_min: int = 0
    delay_bars_max: int = 1


@dataclass
class SimBrokerConfig:
    """SimBroker 配置"""
    partial_fill: PartialFillConfig = field(default_factory=PartialFillConfig)
    fill_order: FillOrderConfig = field(default_factory=FillOrderConfig)
    fill_price: FillPriceConfig = field(default_factory=FillPriceConfig)
    fees: FeesConfig = field(default_factory=lambda: FeesConfig(default_side="taker"))
    cancel_simulation: CancelSimulationConfig = field(default_factory=CancelSimulationConfig)


@dataclass
class GridStrategyConfig:
    """
    完整策略配置
    
    所有配置都必须参数化，不能写死在代码中
    """
    # 基础
    symbol: str = "BTCUSDT"
    exchange: str = "bitget"
    market_type: str = "perp"
    quote_currency: str = "USDT"
    
    # 子配置
    trader_input: TraderInputConfig = field(default_factory=lambda: TraderInputConfig(80000, 90000))
    risk: RiskConfig = field(default_factory=RiskConfig)
    price_boundary: PriceBoundaryConfig = field(default_factory=PriceBoundaryConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    structural_stop: StructuralStopConfig = field(default_factory=StructuralStopConfig)
    zone: ZoneConfig = field(default_factory=ZoneConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    skew: SkewConfig = field(default_factory=SkewConfig)
    derisk: DeRiskConfig = field(default_factory=DeRiskConfig)
    harvest: HarvestConfig = field(default_factory=HarvestConfig)
    reanchor: ReanchorConfig = field(default_factory=ReanchorConfig)
    control_loop: ControlLoopConfig = field(default_factory=ControlLoopConfig)
    order_management: OrderManagementConfig = field(default_factory=OrderManagementConfig)
    fees: FeesConfig = field(default_factory=FeesConfig)
    sim_broker: SimBrokerConfig = field(default_factory=SimBrokerConfig)
    
    def get_atr_ma_len(self) -> int:
        """根据 bar_tf 返回正确的 atr_ma_len"""
        if self.grid.bar_tf == "1m":
            return self.volatility.atr_ma_len_1m
        elif self.grid.bar_tf == "5m":
            return self.volatility.atr_ma_len_5m
        else:
            # 默认用 1m 的参数
            return self.volatility.atr_ma_len_1m

