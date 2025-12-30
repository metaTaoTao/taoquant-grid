"""
配置校验器

实现：
- 系统不变量检查
- 允许调参范围检查
- 危险组合检测
- 拒绝无效配置启动
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from src.audit.events import AuditEvent, AuditEventType
from src.config.schema import GridStrategyConfig


class ConfigValidationError(Exception):
    """配置校验错误"""
    
    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__(f"Config validation failed: {violations}")


@dataclass
class ValidationResult:
    """校验结果"""
    is_valid: bool
    violations: List[str]
    warnings: List[str]


class ConfigValidator:
    """
    配置校验器
    
    三层校验：
    1. 系统不变量（违反则拒绝启动）
    2. 允许调参范围（超出则警告或拒绝）
    3. 危险组合检测（检测到则拒绝）
    """
    
    # 允许调参的范围
    CONFIGURABLE_RANGES = {
        "inv_warn": (0.40, 0.70),
        "inv_damage": (0.50, 0.85),
        "inv_stop": (0.70, 0.95),
        "inv_back_to_normal": (0.20, 0.50),
        "skew_max": (0.0, 0.25),
        "zone_cover": (0.50, 0.90),
        "T_zone_hours": (24, 168),
    }
    
    def validate(self, config: GridStrategyConfig) -> ValidationResult:
        """
        执行完整校验
        
        Args:
            config: 配置实例
            
        Returns:
            ValidationResult
        """
        violations = []
        warnings = []
        
        # 1. 系统不变量
        inv_violations = self._check_invariants(config)
        violations.extend(inv_violations)
        
        # 2. 允许调参范围
        range_warnings = self._check_ranges(config)
        warnings.extend(range_warnings)
        
        # 3. 危险组合检测
        dangerous_violations = self._check_dangerous_combinations(config)
        violations.extend(dangerous_violations)
        
        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )
    
    def validate_or_raise(self, config: GridStrategyConfig) -> None:
        """
        校验配置，失败则抛出异常
        
        Args:
            config: 配置实例
            
        Raises:
            ConfigValidationError: 配置无效
        """
        result = self.validate(config)
        
        if not result.is_valid:
            raise ConfigValidationError(result.violations)
        
        # 打印警告
        for warning in result.warnings:
            print(f"[CONFIG WARNING] {warning}")
    
    def _check_invariants(self, config: GridStrategyConfig) -> List[str]:
        """检查系统不变量"""
        violations = []
        
        risk = config.risk
        
        # inv_warn < inv_damage < inv_stop
        if not (risk.inv_warn < risk.inv_damage < risk.inv_stop):
            violations.append(
                f"Invariant violated: inv_warn ({risk.inv_warn}) < "
                f"inv_damage ({risk.inv_damage}) < inv_stop ({risk.inv_stop})"
            )
        
        # inv_back_to_normal < inv_warn
        if not (risk.inv_back_to_normal < risk.inv_warn):
            violations.append(
                f"Invariant violated: inv_back_to_normal ({risk.inv_back_to_normal}) < "
                f"inv_warn ({risk.inv_warn})"
            )
        
        # skew_max <= 0.25
        if config.skew.skew_max > 0.25:
            violations.append(
                f"Invariant violated: skew_max ({config.skew.skew_max}) <= 0.25"
            )
        
        # edge_decay_factor in (0, 1)
        edf = config.grid.edge_decay_factor
        if not (0 < edf < 1):
            violations.append(
                f"Invariant violated: edge_decay_factor ({edf}) must be in (0, 1)"
            )
        
        # outer_range_low < outer_range_high
        ti = config.trader_input
        if not (ti.outer_range_low < ti.outer_range_high):
            violations.append(
                f"Invariant violated: outer_range_low ({ti.outer_range_low}) < "
                f"outer_range_high ({ti.outer_range_high})"
            )
        
        return violations
    
    def _check_ranges(self, config: GridStrategyConfig) -> List[str]:
        """检查参数范围"""
        warnings = []
        
        risk = config.risk
        
        # 检查 inv 阈值范围
        for name, (min_val, max_val) in [
            ("inv_warn", (0.40, 0.70)),
            ("inv_damage", (0.50, 0.85)),
            ("inv_stop", (0.70, 0.95)),
            ("inv_back_to_normal", (0.20, 0.50)),
        ]:
            value = getattr(risk, name)
            if not (min_val <= value <= max_val):
                warnings.append(
                    f"Parameter {name} ({value}) is outside recommended range [{min_val}, {max_val}]"
                )
        
        # 检查 skew_max 范围
        if not (0.0 <= config.skew.skew_max <= 0.25):
            warnings.append(
                f"Parameter skew_max ({config.skew.skew_max}) is outside range [0, 0.25]"
            )
        
        # 检查 zone_cover 范围
        if not (0.50 <= config.zone.zone_cover <= 0.90):
            warnings.append(
                f"Parameter zone_cover ({config.zone.zone_cover}) is outside range [0.50, 0.90]"
            )
        
        # 检查 T_zone_hours 范围
        if not (24 <= config.zone.T_zone_hours <= 168):
            warnings.append(
                f"Parameter T_zone_hours ({config.zone.T_zone_hours}) is outside range [24, 168]"
            )
        
        return warnings
    
    def _check_dangerous_combinations(self, config: GridStrategyConfig) -> List[str]:
        """检查危险组合"""
        violations = []
        
        risk = config.risk
        
        # inv_stop - inv_damage < 0.10
        if risk.inv_stop - risk.inv_damage < 0.10:
            violations.append(
                f"Dangerous combination: inv_stop - inv_damage "
                f"({risk.inv_stop - risk.inv_damage:.2f}) < 0.10, "
                "risk buffer too small"
            )
        
        # 高杠杆 + 高仓位检测需要知道 leverage，暂时跳过
        # 因为 leverage 信息来自交易所，不在配置中
        
        # liq_distance_threshold 过小
        if risk.liq_distance_threshold < 0.02:
            violations.append(
                f"Dangerous configuration: liq_distance_threshold "
                f"({risk.liq_distance_threshold}) < 0.02, too aggressive"
            )
        
        return violations
    
    def create_invalid_config_event(
        self,
        session_id: str,
        timestamp: datetime,
        violations: List[str],
        config_hash: str,
    ) -> AuditEvent:
        """创建配置无效审计事件"""
        return AuditEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.CONFIG_INVALID,
            reason="Config validation failed",
            config_hash=config_hash,
            details={"violations": violations},
        )

