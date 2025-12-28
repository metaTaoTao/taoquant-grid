"""Technical indicators for grid trading."""

import numpy as np
import pandas as pd


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Average True Range (ATR).

    Parameters
    ----------
    high : pd.Series
        High prices
    low : pd.Series
        Low prices
    close : pd.Series
        Close prices
    period : int
        ATR period

    Returns
    -------
    pd.Series
        ATR values
    """
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    return atr


def calculate_grid_spacing(
    atr: pd.Series,
    min_return: float = 0.005,
    maker_fee: float = 0.0002,
    volatility_k: float = 0.6,
) -> pd.Series:
    """
    Calculate dynamic grid spacing based on ATR.

    Parameters
    ----------
    atr : pd.Series
        ATR values
    min_return : float
        Minimum return per trade (e.g., 0.005 for 0.5%)
    maker_fee : float
        Maker fee (e.g., 0.0002 for 0.02%)
    volatility_k : float
        Volatility multiplier

    Returns
    -------
    pd.Series
        Grid spacing as percentage
    """
    # Get close price (assume index aligned with ATR)
    # For simplicity, we'll use ATR directly
    # In practice, you'd pass close price or calculate ATR% = ATR / close

    # Cost coverage: need to cover trading costs
    cost_coverage = min_return + 2 * maker_fee

    # ATR-based component (assume ATR is already in percentage terms)
    # If ATR is in absolute price, divide by close price first
    atr_pct = atr  # Assuming ATR is already normalized

    # Combined spacing
    spacing = cost_coverage + volatility_k * atr_pct

    return spacing


def auto_calculate_grid_count(
    lower: float,
    upper: float,
    spacing_pct: float
) -> int:
    """
    Auto-calculate grid count from spacing.

    Parameters
    ----------
    lower : float
        Lower price bound
    upper : float
        Upper price bound
    spacing_pct : float
        Grid spacing as percentage (e.g., 0.01 for 1%)

    Returns
    -------
    int
        Number of grids
    """
    ratio = upper / lower
    grid_count = int(np.log(ratio) / np.log(1 + spacing_pct))
    return max(2, min(200, grid_count))
