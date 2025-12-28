"""Grid trading configuration."""

from dataclasses import dataclass


@dataclass
class GridConfig:
    """Grid trading configuration."""

    # Grid range
    support: float
    resistance: float

    # Capital
    initial_cash: float = 100.0
    leverage: float = 10.0

    # Grid parameters
    mode: str = "geometric"  # "geometric" or "arithmetic"
    grid_count: int = None  # Auto-calculated if None

    # ATR spacing parameters
    min_return: float = 0.005
    maker_fee: float = 0.0002
    volatility_k: float = 0.6
    atr_period: int = 14

    # Safety limits
    max_position_usd: float = 10000.0
    max_drawdown_pct: float = 0.20

    # Runtime
    poll_interval_seconds: int = 10

    def validate(self):
        """Validate configuration."""
        if self.support >= self.resistance:
            raise ValueError("support must be < resistance")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        if not (1 <= self.leverage <= 100):
            raise ValueError("leverage must be in [1, 100]")
        if self.mode not in ["geometric", "arithmetic"]:
            raise ValueError("mode must be 'geometric' or 'arithmetic'")
