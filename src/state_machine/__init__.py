"""
状态机模块

四态状态机实现：
- NORMAL
- DEFENSIVE
- DAMAGE_CONTROL
- EMERGENCY_STOP
"""

from src.state_machine.states import StateMachine
from src.state_machine.transitions import TransitionTrigger, TransitionResult

__all__ = [
    "StateMachine",
    "TransitionTrigger",
    "TransitionResult",
]

