"""采集层的公共数据结构与后端接口。

设计上把采集和报告分开。以后换采集方式（加串口、换协议），报告层一行不用动。
"""

from dataclasses import dataclass, field, asdict


@dataclass
class Device:
    """一台设备采到的全部信息。空字段留空字符串，不要写猜的值。"""

    ip: str
    reachable: bool = False
    hostname: str = ""
    vendor: str = ""
    model: str = ""
    version: str = ""
    serial: str = ""
    uptime: str = ""
    method: str = ""          # snmp / ssh / telnet
    error: str = ""
    # 原始回显，按命令名存。diff 就靠它比。
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class Collector:
    """采集后端基类。每个后端只负责一件事，把一台设备问清楚。"""

    name = "base"

    def collect(self, ip, device_cfg=None):
        raise NotImplementedError
