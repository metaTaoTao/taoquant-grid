"""
时间工具函数
"""

from datetime import datetime
from typing import Literal

from src.utils.types import SessionId


def generate_session_id(timestamp: datetime = None) -> SessionId:
    """
    生成会话 ID
    
    格式: s{YYYYMMDD}_{HHmmss}
    示例: s20250629_143000
    """
    if timestamp is None:
        timestamp = datetime.now()
    return SessionId(f"s{timestamp.strftime('%Y%m%d_%H%M%S')}")


def minutes_to_bars(minutes: int, bar_tf: str) -> int:
    """
    将分钟数转换为 bar 数
    
    Args:
        minutes: 分钟数
        bar_tf: K线周期 ("1m", "5m", "15m", "1h", "4h", "1d")
        
    Returns:
        bar 数量
    """
    tf_minutes = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    
    tf_min = tf_minutes.get(bar_tf.lower(), 1)
    return max(1, minutes // tf_min)


def bars_to_minutes(bars: int, bar_tf: str) -> int:
    """
    将 bar 数转换为分钟数
    
    Args:
        bars: bar 数量
        bar_tf: K线周期
        
    Returns:
        分钟数
    """
    tf_minutes = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    
    tf_min = tf_minutes.get(bar_tf.lower(), 1)
    return bars * tf_min


def control_loop_interval_bars(interval: str, bar_tf: str) -> int:
    """
    计算 control_loop 间隔的 bar 数
    
    Args:
        interval: "4h" 或 "1d"
        bar_tf: K线周期
        
    Returns:
        bar 数量
    """
    interval_minutes = {
        "4h": 240,
        "1d": 1440,
    }
    
    minutes = interval_minutes.get(interval.lower(), 240)
    return minutes_to_bars(minutes, bar_tf)

