"""
审计事件类型定义

M2 必须交付的最小事件集：
- STATE_CHANGE: 状态迁移
- RISK_TRIGGER: 风控触发
- ORDER_BLOCKED: 订单被阻止
- PARAM_UPDATE: 参数更新
- REANCHOR_REQUEST: re-anchor 请求
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Optional

from src.models.snapshot import Snapshot


class AuditEventType(Enum):
    """审计事件类型"""
    # 状态相关
    STATE_CHANGE = auto()          # 状态迁移
    
    # 风控相关
    RISK_TRIGGER = auto()          # 风控触发
    INVENTORY_STOP = auto()        # 库存止损
    RISK_BUDGET_STOP = auto()      # 风险预算止损
    STRUCTURAL_STOP = auto()       # 结构止损
    EMERGENCY_STOP = auto()        # 紧急止损
    
    # 订单相关
    ORDER_BLOCKED = auto()         # 订单被阻止
    ORDER_DUPLICATE_BLOCKED = auto()  # 重复订单被阻止
    ORDER_STUCK = auto()           # 订单卡住
    CANCEL_RATE_EXCEEDED = auto()  # 撤单频率超限
    
    # 参数相关
    PARAM_UPDATE = auto()          # 参数更新
    
    # Re-anchor 相关
    REANCHOR_REQUEST = auto()      # re-anchor 请求
    REANCHOR_APPROVED = auto()     # re-anchor 批准
    REANCHOR_REJECTED = auto()     # re-anchor 拒绝
    
    # 退出相关
    EMERGENCY_EXIT = auto()        # 紧急退出
    FORCED_EXIT = auto()           # 强制退出
    
    # 配置相关
    CONFIG_INVALID = auto()        # 配置无效
    
    # 数据相关
    DATA_UNAVAILABLE = auto()      # 数据不可用
    DUPLICATE_EVENT = auto()       # 重复事件


@dataclass
class AuditEvent:
    """
    审计事件
    
    所有审计事件必须包含：
    - session_id: 会话 ID
    - timestamp: 时间戳
    - event_type: 事件类型
    - reason: 触发原因
    - snapshot: 状态快照（可选）
    """
    session_id: str
    timestamp: datetime
    event_type: AuditEventType
    reason: str
    
    # 状态迁移相关
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    
    # 风控相关
    trigger_type: Optional[str] = None
    trigger_value: Optional[float] = None
    threshold: Optional[float] = None
    
    # 订单相关
    order_type: Optional[str] = None
    order_id: Optional[str] = None
    
    # 参数相关
    param_name: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    config_hash: Optional[str] = None
    
    # Re-anchor 相关
    old_range: Optional[Dict[str, float]] = None
    new_range: Optional[Dict[str, float]] = None
    rejection_cause: Optional[str] = None
    new_session_id: Optional[str] = None
    constraints_applied: Optional[Dict[str, Any]] = None
    
    # 退出相关
    exit_method: Optional[str] = None
    exit_result: Optional[str] = None
    
    # 快照
    snapshot: Optional[Snapshot] = None
    
    # 额外信息
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        d = {
            "ts": self.timestamp.isoformat(),
            "session": self.session_id,
            "type": self.event_type.name,
            "reason": self.reason,
        }
        
        # 添加非空字段
        if self.from_state:
            d["from"] = self.from_state
        if self.to_state:
            d["to"] = self.to_state
        if self.trigger_type:
            d["trigger"] = self.trigger_type
        if self.trigger_value is not None:
            d["value"] = self.trigger_value
        if self.threshold is not None:
            d["threshold"] = self.threshold
        if self.order_type:
            d["order_type"] = self.order_type
        if self.order_id:
            d["order_id"] = self.order_id
        if self.param_name:
            d["param_name"] = self.param_name
        if self.old_value is not None:
            d["old_value"] = self.old_value
        if self.new_value is not None:
            d["new_value"] = self.new_value
        if self.config_hash:
            d["config_hash"] = self.config_hash
        if self.old_range:
            d["old_range"] = self.old_range
        if self.new_range:
            d["new_range"] = self.new_range
        if self.rejection_cause:
            d["rejection_cause"] = self.rejection_cause
        if self.new_session_id:
            d["new_session_id"] = self.new_session_id
        if self.constraints_applied:
            d["constraints_applied"] = self.constraints_applied
        if self.exit_method:
            d["exit_method"] = self.exit_method
        if self.exit_result:
            d["exit_result"] = self.exit_result
        if self.snapshot:
            d["snapshot"] = self.snapshot.to_dict()
        if self.details:
            d["details"] = self.details
        
        return d
    
    @classmethod
    def state_change(
        cls,
        session_id: str,
        timestamp: datetime,
        from_state: str,
        to_state: str,
        reason: str,
        snapshot: Optional[Snapshot] = None,
    ) -> "AuditEvent":
        """创建状态迁移事件"""
        return cls(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.STATE_CHANGE,
            reason=reason,
            from_state=from_state,
            to_state=to_state,
            snapshot=snapshot,
        )
    
    @classmethod
    def risk_trigger(
        cls,
        session_id: str,
        timestamp: datetime,
        trigger_type: str,
        value: float,
        threshold: float,
        reason: str,
        snapshot: Optional[Snapshot] = None,
    ) -> "AuditEvent":
        """创建风控触发事件"""
        return cls(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.RISK_TRIGGER,
            reason=reason,
            trigger_type=trigger_type,
            trigger_value=value,
            threshold=threshold,
            snapshot=snapshot,
        )
    
    @classmethod
    def order_blocked(
        cls,
        session_id: str,
        timestamp: datetime,
        order_type: str,
        reason: str,
        state: str,
    ) -> "AuditEvent":
        """创建订单阻止事件"""
        return cls(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.ORDER_BLOCKED,
            reason=reason,
            order_type=order_type,
            to_state=state,  # 当前状态
        )
    
    @classmethod
    def param_update(
        cls,
        session_id: str,
        timestamp: datetime,
        param_name: str,
        old_value: Any,
        new_value: Any,
        config_hash: str,
        reason: str = "",
    ) -> "AuditEvent":
        """创建参数更新事件"""
        return cls(
            session_id=session_id,
            timestamp=timestamp,
            event_type=AuditEventType.PARAM_UPDATE,
            reason=reason,
            param_name=param_name,
            old_value=old_value,
            new_value=new_value,
            config_hash=config_hash,
        )
    
    @classmethod
    def reanchor_request(
        cls,
        session_id: str,
        timestamp: datetime,
        approved: bool,
        old_range: Dict[str, float],
        new_range: Optional[Dict[str, float]],
        reason: str,
        rejection_cause: Optional[str] = None,
        inventory_ratio: Optional[float] = None,
        state: Optional[str] = None,
        new_session_id: Optional[str] = None,
        constraints_applied: Optional[Dict[str, Any]] = None,
        snapshot: Optional[Snapshot] = None,
    ) -> "AuditEvent":
        """创建 re-anchor 请求事件"""
        event_type = AuditEventType.REANCHOR_APPROVED if approved else AuditEventType.REANCHOR_REJECTED
        return cls(
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
            reason=reason,
            old_range=old_range,
            new_range=new_range,
            rejection_cause=rejection_cause,
            new_session_id=new_session_id,
            constraints_applied=constraints_applied,
            snapshot=snapshot,
            details={
                "inventory_ratio": inventory_ratio,
                "state": state,
            } if inventory_ratio is not None else {},
        )

