"""
类型定义
"""

from typing import NewType

# Session ID: 格式 s{YYYYMMDD}_{HHmmss}
SessionId = NewType("SessionId", str)

# Config Hash: 配置文件的 SHA256 哈希前 8 位
ConfigHash = NewType("ConfigHash", str)

