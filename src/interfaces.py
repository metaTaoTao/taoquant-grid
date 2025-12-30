"""
核心接口定义

所有模块必须实现这些接口，确保回测和实盘使用相同的核心逻辑
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.models.events import BaseEvent, BarCloseEvent, FillEvent
from src.models.grid import GridOrder
from src.models.state import StrategyState


class IMarketDataSource(ABC):
    """
    行情数据源接口
    
    实现：
    - ReplayMarketData: 回测数据回放
    - LiveMarketData: 实盘行情（WebSocket/REST）
    """
    
    @abstractmethod
    def subscribe(self, symbol: str, bar_tf: str) -> None:
        """订阅行情"""
        pass
    
    @abstractmethod
    def unsubscribe(self, symbol: str) -> None:
        """取消订阅"""
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> Tuple[float, float]:
        """
        获取当前价格
        
        Returns:
            (mark_price, last_price)
        """
        pass
    
    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Optional[BarCloseEvent]:
        """获取最新 K 线"""
        pass
    
    @abstractmethod
    def set_event_callback(self, callback: Callable[[BaseEvent], None]) -> None:
        """设置事件回调"""
        pass
    
    @abstractmethod
    def start(self) -> None:
        """启动数据源"""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """停止数据源"""
        pass
    
    @property
    @abstractmethod
    def is_running(self) -> bool:
        """是否正在运行"""
        pass


class IExecutionAdapter(ABC):
    """
    执行适配器接口
    
    实现：
    - SimBroker: 回测撮合
    - LiveBroker: 实盘执行（Bitget）
    """
    
    @abstractmethod
    def place_order(self, order: GridOrder) -> str:
        """
        下单
        
        Returns:
            exchange_order_id
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单
        
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> int:
        """
        撤销所有订单
        
        Returns:
            撤销数量
        """
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: str) -> List[GridOrder]:
        """获取活跃订单"""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """
        获取持仓
        
        Returns:
            {
                "position_qty": float,
                "avg_price": float,
                "unrealized_pnl": float,
                "margin": float,
            }
        """
        pass
    
    @abstractmethod
    def get_account(self) -> Dict[str, Any]:
        """
        获取账户信息
        
        Returns:
            {
                "equity": float,
                "available": float,
                "margin_usage": float,
                "liq_distance": float (可选),
            }
        """
        pass
    
    @abstractmethod
    def set_fill_callback(self, callback: Callable[[FillEvent], None]) -> None:
        """设置成交回调"""
        pass
    
    @property
    @abstractmethod
    def supports_reduce_only(self) -> bool:
        """是否支持 reduce-only"""
        pass


class IStateMachine(ABC):
    """
    状态机接口
    
    管理策略的四态迁移
    """
    
    @property
    @abstractmethod
    def current_state(self) -> StrategyState:
        """当前状态"""
        pass
    
    @abstractmethod
    def transition_to(
        self,
        new_state: StrategyState,
        reason: str,
        timestamp: datetime,
    ) -> bool:
        """
        状态迁移
        
        Returns:
            是否成功迁移
        """
        pass
    
    @abstractmethod
    def can_transition_to(self, new_state: StrategyState) -> bool:
        """是否可以迁移到目标状态"""
        pass
    
    @abstractmethod
    def execute_entry_actions(
        self,
        new_state: StrategyState,
        timestamp: datetime,
    ) -> None:
        """执行进入状态的强制动作"""
        pass


class IRiskEngine(ABC):
    """
    风控引擎接口
    
    评估风险触发器，决定是否触发状态迁移
    """
    
    @abstractmethod
    def evaluate(
        self,
        timestamp: datetime,
        trigger_point: str,  # "on_fill" | "on_bar_close"
    ) -> Optional[Tuple[StrategyState, str]]:
        """
        评估风险
        
        Returns:
            (目标状态, 原因) 或 None（不需要迁移）
        """
        pass
    
    @abstractmethod
    def check_emergency(self) -> bool:
        """检查是否需要紧急停止"""
        pass
    
    @abstractmethod
    def update_indicators(self, bar: BarCloseEvent) -> None:
        """更新风控指标"""
        pass


class IAdvantageGate(ABC):
    """
    优势门控接口
    
    M3 提供 stub，M4 提供完整实现
    """
    
    @property
    @abstractmethod
    def opportunity_valid(self) -> bool:
        """
        机会窗口是否有效
        
        false 时禁止新增网格，只允许减仓/harvest
        """
        pass
    
    @property
    @abstractmethod
    def core_zone(self) -> Tuple[float, float]:
        """
        返回 (core_low, core_high)
        
        影响 spacing 和 active window
        """
        pass
    
    @abstractmethod
    def on_control_loop(self, timestamp: datetime) -> None:
        """
        control_loop 调用
        
        4H/1D 更新一次，写 PARAM_UPDATE 审计事件
        """
        pass


class IGridEngine(ABC):
    """
    网格引擎接口
    
    生成目标订单集
    """
    
    @abstractmethod
    def generate_orders(
        self,
        current_price: float,
        state: StrategyState,
        inventory_ratio: float,
    ) -> List[GridOrder]:
        """
        生成目标订单集
        
        根据当前状态和库存，生成应该存在的订单
        """
        pass
    
    @abstractmethod
    def update_spacing(self, atr: float) -> None:
        """更新网格间距"""
        pass


class IOrderManager(ABC):
    """
    订单管理器接口
    
    差量计算与订单执行
    """
    
    @abstractmethod
    def sync_orders(
        self,
        desired_orders: List[GridOrder],
        current_orders: List[GridOrder],
    ) -> Tuple[List[GridOrder], List[str]]:
        """
        同步订单
        
        Returns:
            (需要下的新订单, 需要撤销的订单 ID)
        """
        pass
    
    @abstractmethod
    def can_place_order(self, order: GridOrder) -> Tuple[bool, str]:
        """
        检查是否可以下单
        
        Returns:
            (是否可以, 原因)
        """
        pass
    
    @property
    @abstractmethod
    def order_mode(self) -> str:
        """当前订单模式"""
        pass
    
    @order_mode.setter
    @abstractmethod
    def order_mode(self, mode: str) -> None:
        """设置订单模式"""
        pass

