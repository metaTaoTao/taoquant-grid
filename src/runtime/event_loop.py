"""
事件循环基础框架

提供 noop event loop 验证架构跑通
"""

import time
from datetime import datetime
from typing import Callable, List, Optional

from src.models.events import BaseEvent, EventType, BarCloseEvent
from src.models.state import StrategyState
from src.audit.events import AuditEvent, AuditEventType
from src.audit.journal import IAuditJournal, AuditJournal
from src.config.schema import GridStrategyConfig
from src.config.loader import compute_config_hash
from src.state_machine.states import StateMachine
from src.utils.timeutils import generate_session_id


class NoopEventLoop:
    """
    空事件循环
    
    用于验证架构跑通，不执行任何交易逻辑
    """
    
    def __init__(
        self,
        config: GridStrategyConfig,
        output_dir: str,
        session_id: Optional[str] = None,
    ):
        """
        初始化事件循环
        
        Args:
            config: 策略配置
            output_dir: 输出目录
            session_id: 会话 ID（可选，自动生成）
        """
        self.config = config
        self.output_dir = output_dir
        self.session_id = session_id or generate_session_id()
        self.config_hash = compute_config_hash(config)
        
        # 初始化审计日志
        self.audit_journal = AuditJournal(output_dir)
        
        # 初始化状态机
        self.state_machine = StateMachine(
            session_id=self.session_id,
            audit_journal=self.audit_journal,
        )
        
        # 事件计数
        self._event_count = 0
        self._bar_count = 0
        self._is_running = False
        
        # 事件处理器
        self._event_handlers: List[Callable[[BaseEvent], None]] = []
    
    def register_handler(self, handler: Callable[[BaseEvent], None]) -> None:
        """注册事件处理器"""
        self._event_handlers.append(handler)
    
    def process_event(self, event: BaseEvent) -> None:
        """
        处理事件
        
        noop 实现：只计数和记录
        """
        self._event_count += 1
        
        if event.event_type == EventType.BAR_CLOSE:
            self._bar_count += 1
        
        # 调用注册的处理器
        for handler in self._event_handlers:
            handler(event)
    
    def on_startup(self) -> None:
        """启动回调"""
        timestamp = datetime.now()
        
        # 写入启动审计事件
        event = AuditEvent(
            session_id=self.session_id,
            timestamp=timestamp,
            event_type=AuditEventType.PARAM_UPDATE,
            reason="startup",
            param_name="session",
            old_value=None,
            new_value=self.session_id,
            config_hash=self.config_hash,
        )
        self.audit_journal.write(event)
        
        print(f"[{timestamp}] NoopEventLoop started")
        print(f"  Session ID: {self.session_id}")
        print(f"  Config Hash: {self.config_hash}")
        print(f"  Symbol: {self.config.symbol}")
        print(f"  State: {self.state_machine.current_state.name}")
    
    def on_shutdown(self) -> None:
        """关闭回调"""
        timestamp = datetime.now()
        
        print(f"[{timestamp}] NoopEventLoop stopped")
        print(f"  Total events: {self._event_count}")
        print(f"  Total bars: {self._bar_count}")
        print(f"  Final state: {self.state_machine.current_state.name}")
        
        self.audit_journal.close()
    
    def run_once(self, event: BaseEvent) -> None:
        """处理单个事件"""
        self.process_event(event)
    
    def run_until_stopped(self) -> None:
        """运行直到停止"""
        self._is_running = True
        self.on_startup()
        
        try:
            while self._is_running:
                # 实际实现中这里会等待事件
                time.sleep(0.1)
        finally:
            self.on_shutdown()
    
    def stop(self) -> None:
        """停止事件循环"""
        self._is_running = False
    
    @property
    def event_count(self) -> int:
        """已处理事件数"""
        return self._event_count
    
    @property
    def bar_count(self) -> int:
        """已处理 bar 数"""
        return self._bar_count


def run_noop_test(config_path: str, output_dir: str, n_bars: int = 10) -> bool:
    """
    运行 noop 测试
    
    验证：
    1. 配置加载正常
    2. 审计日志写入正常
    3. 状态机初始化正常
    4. 事件处理框架正常
    
    Args:
        config_path: 配置文件路径
        output_dir: 输出目录
        n_bars: 模拟 bar 数量
        
    Returns:
        是否成功
    """
    from src.config.loader import load_config
    from src.config.validator import ConfigValidator
    
    print("=" * 60)
    print("NoopEventLoop Test")
    print("=" * 60)
    
    # 1. 加载配置
    print("\n1. Loading config...")
    config = load_config(config_path)
    print(f"   Symbol: {config.symbol}")
    print(f"   Bar TF: {config.grid.bar_tf}")
    
    # 2. 校验配置
    print("\n2. Validating config...")
    validator = ConfigValidator()
    result = validator.validate(config)
    print(f"   Valid: {result.is_valid}")
    if result.violations:
        print(f"   Violations: {result.violations}")
        return False
    if result.warnings:
        print(f"   Warnings: {result.warnings}")
    
    # 3. 创建事件循环
    print("\n3. Creating event loop...")
    loop = NoopEventLoop(config, output_dir)
    
    # 4. 启动
    loop.on_startup()
    
    # 5. 模拟事件
    print(f"\n4. Simulating {n_bars} bars...")
    for i in range(n_bars):
        bar_time = datetime.now()
        event = BarCloseEvent(
            event_type=EventType.BAR_CLOSE,
            timestamp=bar_time,
            session_id=loop.session_id,
            symbol=config.symbol,
            bar_tf=config.grid.bar_tf,
            bar_time=bar_time,
            open=85000 + i * 10,
            high=85050 + i * 10,
            low=84950 + i * 10,
            close=85020 + i * 10,
            volume=100.0,
            mark_price=85020 + i * 10,
        )
        loop.run_once(event)
    
    # 6. 关闭
    loop.on_shutdown()
    
    # 7. 验证审计日志
    print("\n5. Verifying audit log...")
    from pathlib import Path
    audit_file = Path(output_dir) / "audit_events.jsonl"
    if audit_file.exists():
        with open(audit_file, "r") as f:
            lines = f.readlines()
        print(f"   Audit events: {len(lines)}")
    else:
        print("   ERROR: Audit file not created!")
        return False
    
    print("\n" + "=" * 60)
    print("NoopEventLoop Test PASSED")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    import sys
    
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/grid_strategy.yaml"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output/noop_test"
    
    success = run_noop_test(config_path, output_dir)
    sys.exit(0 if success else 1)

