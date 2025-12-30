"""
网格生成器

实现:
- 基于 ATR 生成网格层级
- 活跃窗口限制 (N_buy_active / M_sell_active)
- 边缘递减机制
- core/buffer 区间距差异
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from src.models.state import StrategyState
from src.models.grid import GridLevel, GridOrder, OrderSide, OrderStatus
from src.interfaces import IAdvantageGate, IGridEngine


@dataclass
class SpacingConfig:
    """间距配置"""
    base_step_method: str = "atr"     # "atr" | "fixed"
    base_step_fixed: float = 100.0    # 固定间距值
    core_compress_factor: float = 0.7  # core 区压缩系数
    buffer_expand_factor: float = 1.3  # buffer 区扩张系数


@dataclass
class ActiveWindowConfig:
    """活跃窗口配置"""
    N_buy_active: int = 5   # 最多活跃 buy 层数
    M_sell_active: int = 5  # 最多活跃 sell 层数


@dataclass
class EdgeDecayConfig:
    """边缘递减配置"""
    edge_band_atr_mult: float = 1.5   # 边缘带宽度 = 1.5 * ATR
    edge_decay_factor: float = 0.7    # 每层递减系数


@dataclass
class GridEngine(IGridEngine):
    """
    网格引擎
    
    根据当前状态和库存生成目标订单集
    """
    # 配置
    session_id: str = ""
    symbol: str = ""
    base_size: float = 0.001          # 基础订单 size (BTC)
    
    spacing_config: SpacingConfig = field(default_factory=SpacingConfig)
    active_window_config: ActiveWindowConfig = field(default_factory=ActiveWindowConfig)
    edge_decay_config: EdgeDecayConfig = field(default_factory=EdgeDecayConfig)
    
    # 优势门控
    advantage_gate: Optional[IAdvantageGate] = None
    
    # 当前状态
    _current_atr: float = 0.0
    _current_price: float = 0.0
    _outer_range_low: float = 0.0
    _outer_range_high: float = 0.0
    
    # 订单序列号
    _order_sequence: int = 0
    
    def generate_orders(
        self,
        current_price: float,
        state: StrategyState,
        inventory_ratio: float,
    ) -> List[GridOrder]:
        """
        生成目标订单集
        
        根据当前状态和库存，生成应该存在的订单
        
        Args:
            current_price: 当前价格
            state: 当前状态
            inventory_ratio: 库存比率
            
        Returns:
            目标订单列表
        """
        self._current_price = current_price
        
        # 检查优势门控
        if self.advantage_gate is not None:
            if not self.advantage_gate.opportunity_valid:
                # 机会无效，只生成 reduce-only 订单
                return self._generate_reduce_only_orders(current_price, inventory_ratio)
        
        # 根据状态生成订单
        if state == StrategyState.EMERGENCY_STOP:
            return []  # 紧急停止，不生成任何订单
        
        if state == StrategyState.DAMAGE_CONTROL:
            return self._generate_reduce_only_orders(current_price, inventory_ratio)
        
        if state == StrategyState.DEFENSIVE:
            return self._generate_defensive_orders(current_price, inventory_ratio)
        
        # NORMAL 状态
        return self._generate_normal_orders(current_price, inventory_ratio)
    
    def _generate_normal_orders(
        self,
        current_price: float,
        inventory_ratio: float,
    ) -> List[GridOrder]:
        """生成 NORMAL 状态的订单"""
        orders = []
        
        # 获取 core zone
        core_low, core_high = self._get_core_zone()
        
        # 计算 spacing
        base_step = self._calculate_base_step()
        core_step = base_step * self.spacing_config.core_compress_factor
        buffer_step = base_step * self.spacing_config.buffer_expand_factor
        
        # 生成 buy 订单（价格低于当前价）
        buy_orders = self._generate_buy_levels(
            current_price,
            core_low,
            core_step,
            buffer_step,
            self.active_window_config.N_buy_active,
        )
        orders.extend(buy_orders)
        
        # 生成 sell 订单（价格高于当前价）
        sell_orders = self._generate_sell_levels(
            current_price,
            core_high,
            core_step,
            buffer_step,
            self.active_window_config.M_sell_active,
        )
        orders.extend(sell_orders)
        
        return orders
    
    def _generate_defensive_orders(
        self,
        current_price: float,
        inventory_ratio: float,
    ) -> List[GridOrder]:
        """
        生成 DEFENSIVE 状态的订单
        
        - 冻结新增 buy
        - 只保留 core 内的 sell
        """
        orders = []
        
        core_low, core_high = self._get_core_zone()
        base_step = self._calculate_base_step()
        core_step = base_step * self.spacing_config.core_compress_factor
        
        # 只生成 sell 订单
        sell_orders = self._generate_sell_levels(
            current_price,
            core_high,
            core_step,
            core_step,  # DEFENSIVE 下 buffer 也用 core_step
            self.active_window_config.M_sell_active,
        )
        orders.extend(sell_orders)
        
        return orders
    
    def _generate_reduce_only_orders(
        self,
        current_price: float,
        inventory_ratio: float,
    ) -> List[GridOrder]:
        """
        生成 reduce-only 订单
        
        只生成能减少库存的订单
        """
        orders = []
        
        if inventory_ratio <= 0:
            return orders
        
        base_step = self._calculate_base_step()
        
        # 只生成 sell 订单，且标记为 reduce_only
        for i in range(self.active_window_config.M_sell_active):
            level_id = i + 1
            price = current_price + base_step * level_id
            
            # 边缘递减
            decay = self._calculate_edge_decay(i, self.active_window_config.M_sell_active)
            actual_size = self.base_size * decay
            
            order = self._create_order(
                level_id=level_id,
                price=price,
                side=OrderSide.SELL,
                size=actual_size,
                reduce_only=True,
            )
            orders.append(order)
        
        return orders
    
    def _generate_buy_levels(
        self,
        current_price: float,
        core_low: float,
        core_step: float,
        buffer_step: float,
        max_levels: int,
    ) -> List[GridOrder]:
        """生成 buy 层级"""
        orders = []
        price = current_price - core_step
        
        for i in range(max_levels):
            level_id = -(i + 1)  # buy 用负数表示
            
            # 判断是否在 core 区
            is_in_core = price >= core_low
            step = core_step if is_in_core else buffer_step
            
            # 检查是否超出 outer_range
            if price < self._outer_range_low:
                break
            
            # 边缘递减
            decay = self._calculate_edge_decay(i, max_levels)
            actual_size = self.base_size * decay
            
            order = self._create_order(
                level_id=level_id,
                price=price,
                side=OrderSide.BUY,
                size=actual_size,
                reduce_only=False,
                is_in_core=is_in_core,
            )
            orders.append(order)
            
            # 计算下一层价格
            price -= step
        
        return orders
    
    def _generate_sell_levels(
        self,
        current_price: float,
        core_high: float,
        core_step: float,
        buffer_step: float,
        max_levels: int,
    ) -> List[GridOrder]:
        """生成 sell 层级"""
        orders = []
        price = current_price + core_step
        
        for i in range(max_levels):
            level_id = i + 1  # sell 用正数表示
            
            # 判断是否在 core 区
            is_in_core = price <= core_high
            step = core_step if is_in_core else buffer_step
            
            # 检查是否超出 outer_range
            if price > self._outer_range_high:
                break
            
            # 边缘递减
            decay = self._calculate_edge_decay(i, max_levels)
            actual_size = self.base_size * decay
            
            order = self._create_order(
                level_id=level_id,
                price=price,
                side=OrderSide.SELL,
                size=actual_size,
                reduce_only=False,
                is_in_core=is_in_core,
            )
            orders.append(order)
            
            # 计算下一层价格
            price += step
        
        return orders
    
    def _create_order(
        self,
        level_id: int,
        price: float,
        side: OrderSide,
        size: float,
        reduce_only: bool = False,
        is_in_core: bool = True,
    ) -> GridOrder:
        """创建订单"""
        self._order_sequence += 1
        
        client_order_id = GridOrder.generate_client_order_id(
            session_id=self.session_id,
            level_id=abs(level_id),
            side=side,
            sequence=self._order_sequence,
        )
        
        return GridOrder(
            client_order_id=client_order_id,
            symbol=self.symbol,
            side=side,
            price=price,
            qty=size,
            reduce_only=reduce_only,
            grid_level=level_id,
            session_id=self.session_id,
            status=OrderStatus.PENDING,
            tags={"is_in_core": is_in_core},
        )
    
    def _calculate_base_step(self) -> float:
        """计算基础间距"""
        if self.spacing_config.base_step_method == "fixed":
            return self.spacing_config.base_step_fixed
        
        # ATR 方法
        if self._current_atr <= 0:
            return self.spacing_config.base_step_fixed  # fallback
        
        return self._current_atr
    
    def _calculate_edge_decay(self, level_index: int, max_levels: int) -> float:
        """
        计算边缘递减系数
        
        靠近边缘的层级 size 递减
        """
        if max_levels <= 1:
            return 1.0
        
        # 判断是否在边缘带
        edge_start = max_levels - 2  # 最后两层开始递减
        
        if level_index < edge_start:
            return 1.0
        
        # 计算递减
        steps_in_edge = level_index - edge_start + 1
        return self.edge_decay_config.edge_decay_factor ** steps_in_edge
    
    def _get_core_zone(self) -> Tuple[float, float]:
        """获取 core zone"""
        if self.advantage_gate is not None:
            return self.advantage_gate.core_zone
        
        # 默认等于 outer_range
        return (self._outer_range_low, self._outer_range_high)
    
    def update_spacing(self, atr: float) -> None:
        """更新网格间距"""
        self._current_atr = atr
    
    def update_outer_range(self, low: float, high: float) -> None:
        """更新 outer_range"""
        self._outer_range_low = low
        self._outer_range_high = high
    
    def set_advantage_gate(self, gate: IAdvantageGate) -> None:
        """设置优势门控"""
        self.advantage_gate = gate
    
    @property
    def current_atr(self) -> float:
        """当前 ATR"""
        return self._current_atr

