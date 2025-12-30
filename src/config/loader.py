"""
配置加载器
"""

import hashlib
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from src.config.schema import (
    GridStrategyConfig,
    TraderInputConfig,
    RiskConfig,
    PriceBoundaryConfig,
    VolatilityConfig,
    StructuralStopConfig,
    ZoneConfig,
    GridConfig,
    SkewConfig,
    DeRiskConfig,
    HarvestConfig,
    ReanchorConfig,
    ControlLoopConfig,
    OrderManagementConfig,
    FeesConfig,
    SimBrokerConfig,
    PartialFillConfig,
    FillOrderConfig,
    FillPriceConfig,
    CancelSimulationConfig,
)
from src.utils.types import ConfigHash


def load_config(config_path: str) -> GridStrategyConfig:
    """
    从 YAML 文件加载配置
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        GridStrategyConfig 实例
    """
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return _parse_config(data)


def _parse_config(data: Dict[str, Any]) -> GridStrategyConfig:
    """解析配置字典"""
    
    # 解析各个子配置
    trader_input = _parse_section(data.get("trader_input", {}), TraderInputConfig)
    risk = _parse_section(data.get("risk", {}), RiskConfig)
    price_boundary = _parse_section(data.get("price_boundary", {}), PriceBoundaryConfig)
    volatility = _parse_section(data.get("volatility", {}), VolatilityConfig)
    structural_stop = _parse_section(data.get("structural_stop", {}), StructuralStopConfig)
    zone = _parse_section(data.get("zone", {}), ZoneConfig)
    grid = _parse_section(data.get("grid", {}), GridConfig)
    skew = _parse_section(data.get("skew", {}), SkewConfig)
    derisk = _parse_section(data.get("derisk", {}), DeRiskConfig)
    harvest = _parse_section(data.get("harvest", {}), HarvestConfig)
    reanchor = _parse_section(data.get("reanchor", {}), ReanchorConfig)
    control_loop = _parse_section(data.get("control_loop", {}), ControlLoopConfig)
    order_management = _parse_section(data.get("order_management", {}), OrderManagementConfig)
    fees = _parse_section(data.get("fees", {}), FeesConfig)
    
    # SimBroker 需要特殊处理
    sim_broker_data = data.get("sim_broker", {})
    sim_broker = SimBrokerConfig(
        partial_fill=_parse_section(sim_broker_data.get("partial_fill", {}), PartialFillConfig),
        fill_order=_parse_section(sim_broker_data.get("fill_order", {}), FillOrderConfig),
        fill_price=_parse_section(sim_broker_data.get("fill_price", {}), FillPriceConfig),
        fees=_parse_section(sim_broker_data.get("fees", {}), FeesConfig),
        cancel_simulation=_parse_section(sim_broker_data.get("cancel_simulation", {}), CancelSimulationConfig),
    )
    
    return GridStrategyConfig(
        symbol=data.get("symbol", "BTCUSDT"),
        exchange=data.get("exchange", "bitget"),
        market_type=data.get("market_type", "perp"),
        quote_currency=data.get("quote_currency", "USDT"),
        trader_input=trader_input,
        risk=risk,
        price_boundary=price_boundary,
        volatility=volatility,
        structural_stop=structural_stop,
        zone=zone,
        grid=grid,
        skew=skew,
        derisk=derisk,
        harvest=harvest,
        reanchor=reanchor,
        control_loop=control_loop,
        order_management=order_management,
        fees=fees,
        sim_broker=sim_broker,
    )


def _parse_section(data: Dict[str, Any], cls: type) -> Any:
    """解析配置段落"""
    if not data:
        return cls()
    
    # 过滤掉 cls 不接受的字段
    import inspect
    sig = inspect.signature(cls)
    valid_keys = set(sig.parameters.keys())
    filtered_data = {k: v for k, v in data.items() if k in valid_keys}
    
    return cls(**filtered_data)


def compute_config_hash(config: GridStrategyConfig) -> ConfigHash:
    """
    计算配置哈希
    
    用于审计，确保可以追踪配置变化
    
    Returns:
        SHA256 哈希的前 8 位
    """
    import json
    from dataclasses import asdict
    
    # 转换为 JSON 字符串
    config_dict = asdict(config)
    config_str = json.dumps(config_dict, sort_keys=True, default=str)
    
    # 计算 SHA256
    hash_obj = hashlib.sha256(config_str.encode())
    
    return ConfigHash(hash_obj.hexdigest()[:8])


def save_config_snapshot(config: GridStrategyConfig, output_path: str) -> None:
    """
    保存配置快照
    
    Args:
        config: 配置实例
        output_path: 输出路径
    """
    from dataclasses import asdict
    
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    config_dict = asdict(config)
    
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False)

