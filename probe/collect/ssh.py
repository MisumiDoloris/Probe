"""SSH 与 Telnet 采集，走 netmiko。

两条硬规矩。
一，下发的每一条命令都先过 ro_guard，不合只读就抛异常，不发。
二，整体超时要短。巡检一台设备最多给它二十秒，卡住的记失败，不拖着整批。
"""

import re

from .base import Collector, field_value
from .parsing import parse_model, parse_vendor
from ..ro_guard import assert_readonly

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_OK = True
except Exception:  # pragma: no cover
    NETMIKO_OK = False


# 采集哪几类信息。都对应 commands.yaml 里的键。
COLLECT_KEYS = ("version", "config", "interfaces", "cpu", "memory", "serial")


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
            spec = table.get(key)
            if not spec:
                continue
            for cmd in (spec if isinstance(spec, list) else [spec]):
                assert_readonly(cmd)

        os_type = table.get("netmiko_os", "")
        if self.transport == "telnet" and not os_type.endswith("_telnet"):
            os_type = f"{os_type}_telnet"

        params = {
            "device_type": os_type,
            "host": ip,
            "username": field_value(cfg, "username"),
            "password": field_value(cfg, "password"),
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
                spec = table.get(key)
                if not spec:
                    continue
                # 一条命令可以写成列表，按顺序试，第一条有正常回显的就用。
                # 序列号就是这样：不同 VRP 版本认的命令不一样。
                candidates = spec if isinstance(spec, list) else [spec]
                for cmd in candidates:
                    assert_readonly(cmd)      # 只读硬约束，在这里卡
                    try:
                        out = conn.send_command(cmd, read_timeout=self.timeout)
                    except Exception as e:
                        raw[key] = f"<失败 {type(e).__name__}: {e}>"
                        continue
                    if _looks_like_error(out):
                        raw[key] = f"<不支持 {cmd}>"
                        continue
                    raw[key] = out
                    break
        except Exception as e:
            raise RuntimeError(_explain(e))
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
            "vendor": parse_vendor(version_text, brand),
            "model": parse_model(version_text),
            "uptime": _parse_uptime(version_text),
            "serial": _parse_serial(raw.get("serial", "")),
            "raw": raw,
        }



# 命令不被这版 VRP 认时的回显特征，用来判断要不要换下一条备选命令。
ERROR_HINTS = ("Error:", "Unrecognized command", "Too many parameters", "Incomplete command",
               "Wrong parameter", "% Invalid input", "% Incomplete command")


def _looks_like_error(text):
    head = (text or "").strip()
    if not head:
        return True
    return any(hint in head[:300] for hint in ERROR_HINTS)



def _parse_uptime(text):
    """display version 里那句 uptime is ... 抓出来，抓不到返回空。"""
    m = re.search(r"uptime is ([^\r\n]+)", text or "", re.I)
    return m.group(1).strip() if m else ""


# 序列号在各版 VRP 上的写法不统一，这里只认几种明确的标签，抓不到就留空。
SERIAL_RE = re.compile(
    r"(?:\bESN\b|\bSN\b|Serial\s*Number|Barcode)\s*(?:of\s+this\s+device)?\s*[:：]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-]{5,})",
    re.I,
)


def _parse_serial(text):
    if not text or _looks_like_error(text):
        return ""
    for line in str(text).splitlines():
        if not re.search(r"ESN|\bSN\b|Serial|Barcode", line, re.I):
            continue
        m = SERIAL_RE.search(line)
        if m:
            return m.group(1).strip()
    return ""


def _explain(exc):
    """把底层异常翻成人能读的原因。

    报告里的「待核实」原因栏直接引用这句，所以不能把
    ReadTimeout: Pattern not detected: '(?:Chang...' 这种原文丢进去。
    """
    name = type(exc).__name__
    text = str(exc)
    low = text.lower()
    # 设备明确说「本地认证被拒」时，原因通常不是密码错，是 aaa 下这个用户
    # 没允许这种登录方式（service-type 只给了 ssh，Telnet 就登不上）。
    # 这句必须排在下面 authentication 那条前面，否则会被吃掉。
    buffer_text = ""
    for attr in ("output", "args"):
        val = getattr(exc, attr, "")
        buffer_text += str(val or "")
    haystack = (low + " " + buffer_text.lower())
    if "rejected" in haystack and "authentication" in haystack:
        return "设备拒绝本地认证：这个用户没允许这种登录方式，检查 aaa 下 local-user 的 service-type 有没有 ssh / telnet"
    if "authentication" in low or name == "NetmikoAuthenticationException":
        return "认证失败：用户名或密码不对"
    if "readtimeout" in name.lower() or "pattern not detected" in low:
        return (
            "超时未认出提示符：可能是密码不对，也可能是 aaa 下这个用户没配对应的 service-type"
            "（Telnet 要 telnet、SSH 要 ssh），或者 vty 没允许该协议、没关分屏"
        )
    if "refused" in low:
        return "端口拒绝连接：服务没开或端口号不对"
    if name == "NetmikoTimeoutException":
        return "连接超时：地址不通、端口没开或被防火墙拦"
    return f"{name}: {text[:120]}"


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
