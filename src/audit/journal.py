"""
审计日志写入

实现 append-only 的 JSONL 格式审计日志
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.audit.events import AuditEvent, AuditEventType


class IAuditJournal(ABC):
    """审计日志接口"""
    
    @abstractmethod
    def write(self, event: AuditEvent) -> None:
        """写入审计事件"""
        pass
    
    @abstractmethod
    def flush(self) -> None:
        """刷新缓冲区"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭日志"""
        pass
    
    @abstractmethod
    def query(
        self,
        event_types: Optional[List[AuditEventType]] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AuditEvent]:
        """查询审计事件"""
        pass


class AuditJournal(IAuditJournal):
    """
    审计日志实现
    
    特点：
    - append-only
    - JSON Lines 格式
    - 每条事件立即 flush
    - 可查询
    """
    
    def __init__(self, output_dir: str, filename: str = "audit_events.jsonl"):
        """
        初始化审计日志
        
        Args:
            output_dir: 输出目录
            filename: 日志文件名
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.filepath = self.output_dir / filename
        self._file = None
        self._event_count = 0
    
    def _ensure_file(self) -> None:
        """确保文件已打开"""
        if self._file is None:
            self._file = open(self.filepath, "a", encoding="utf-8")
    
    def write(self, event: AuditEvent) -> None:
        """
        写入审计事件
        
        立即 flush 确保数据持久化
        """
        self._ensure_file()
        
        # 转换为 JSON 并写入
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        
        self._event_count += 1
    
    def flush(self) -> None:
        """刷新缓冲区"""
        if self._file is not None:
            self._file.flush()
    
    def close(self) -> None:
        """关闭日志"""
        if self._file is not None:
            self._file.close()
            self._file = None
    
    def query(
        self,
        event_types: Optional[List[AuditEventType]] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AuditEvent]:
        """
        查询审计事件
        
        从文件中读取并过滤
        """
        if not self.filepath.exists():
            return []
        
        results = []
        
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    
                    # 过滤
                    if event_types:
                        if data.get("type") not in [et.name for et in event_types]:
                            continue
                    
                    if session_id:
                        if data.get("session") != session_id:
                            continue
                    
                    ts = datetime.fromisoformat(data.get("ts", ""))
                    
                    if start_time and ts < start_time:
                        continue
                    
                    if end_time and ts > end_time:
                        continue
                    
                    # 重建 AuditEvent（简化版，只保留字典）
                    results.append(data)
                    
                except (json.JSONDecodeError, ValueError):
                    continue
        
        return results
    
    @property
    def event_count(self) -> int:
        """已写入事件数"""
        return self._event_count
    
    def __enter__(self) -> "AuditJournal":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class NullAuditJournal(IAuditJournal):
    """
    空审计日志（用于测试或禁用审计）
    """
    
    def write(self, event: AuditEvent) -> None:
        pass
    
    def flush(self) -> None:
        pass
    
    def close(self) -> None:
        pass
    
    def query(
        self,
        event_types: Optional[List[AuditEventType]] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AuditEvent]:
        return []

