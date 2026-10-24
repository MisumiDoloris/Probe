"""SSH 与 Telnet 采集，走 netmiko。

两条硬规矩。
一，下发的每一条命令都先过 ro_guard，不合只读就抛异常，不发。
二，整体超时要短。巡检一台设备最多给它二十秒，卡住的记失败，不拖着整批。
"""

from .base import Collector
from ..ro_guard import assert_readonly

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_OK = True
except Exception:  # pragma: no cover
    NETMIKO_OK = False


# 采集哪几类信息。都对应 commands.yaml 里的键。
COLLECT_KEYS = ("version", "config", "interfaces", "cpu", "memory")


class CliCollector(Collector):
    """cfg 里带 host / username / password / brand / transport。"""

    name = "cli"

    def __init__(self, commands, transport="ssh", timeout=20):
        self.commands = commands      # commands.yaml 读出来的整张表
        self.transport = transport    # ssh 或 telnet
        self.timeout = timeout

    def _pick_commands(self, brand):
        table = self.commands.get(brand)
        if not table:
            raise RuntimeError(f"commands.yaml 里没有这个品牌: {brand}")
        return table

    def collect(self, ip, device_cfg=None):
        if not NETMIKO_OK:
            raise RuntimeError("netmiko 不可用")
        cfg = device_cfg or {}
        brand = cfg.get("brand", "")
        table = self._pick_commands(brand)

        # 先整表过一遍守卫，再去连设备。
        # 表里有一条写命令就当场抛，绝不因为「还没连上」而把它带到设备上试。
        for key in COLLECT_KEYS:
            cmd = table.get(key)
            if cmd:
                assert_readonly(cmd)

        os_type = table.get("netmiko_os", "")
        if self.transport == "telnet" and not os_type.endswith("_telnet"):
            os_type = f"{os_type}_telnet"

        params = {
            "device_type": os_type,
            "host": ip,
            "username": cfg.get("username", ""),
            "password": cfg.get("password", ""),
            "timeout": self.timeout,
            "conn_timeout": self.timeout,
            "fast_cli": False,
        }
        if self.transport == "telnet":
            params["port"] = cfg.get("port", 23)
        else:
            params.setdefault("port", cfg.get("port", 22))

        raw = {}
        conn = None
        hostname = ""
        try:
            conn = ConnectHandler(**params)
            # 设备真名从提示符里读（<TEST-SW-01> / [TEST-SW-01]），比配置里写的标签可靠。
            try:
                hostname = conn.find_prompt().strip().strip("<>[]").strip()
            except Exception:
                hostname = ""
            for key in COLLECT_KEYS:
                cmd = table.get(key)
                if not cmd:
                    continue
                assert_readonly(cmd)          # 只读硬约束，在这里卡
                try:
                    raw[key] = conn.send_command(cmd, read_timeout=self.timeout)
                except Exception as e:
                    raw[key] = f"<失败 {type(e).__name__}: {e}>"
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {e}")
        finally:
            if conn is not None:
                try:
                    conn.disconnect()
                except Exception:
                    pass

        version_text = raw.get("version", "")
        return {
            "method": self.transport,
            "version": _parse_version(version_text),
            "hostname": hostname or cfg.get("name", ""),
            "raw": raw,
        }


def _parse_version(text):
    """从回显里捞版本号。捞不到就返回空，不猜。"""
    if not text:
        return ""
    for line in text.splitlines():
        low = line.lower()
        if "version" in low and len(line.strip()) < 120:
            return line.strip()
    first = text.strip().splitlines()
    return first[0].strip()[:120] if first else ""
