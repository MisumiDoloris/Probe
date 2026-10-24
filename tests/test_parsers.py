"""序列号解析与「命令不支持就换下一条」的行为。

序列号在不同 VRP 版本上写法差别很大，这里只用真实的回显样本验解析，
不连设备。
"""

import unittest

from probe.collect import ssh as ssh_mod
from probe.collect.ssh import CliCollector, _parse_serial, _looks_like_error


class TestParseSerial(unittest.TestCase):
    def test_huawei_esn(self):
        text = "ESN of this device: 2102354876ABCDEF1234"
        self.assertEqual(_parse_serial(text), "2102354876ABCDEF1234")

    def test_huawei_elabel(self):
        text = (
            "=================================================\n"
            "Board Serial Number : 2102354876ABCDEF\n"
            "=================================================\n"
        )
        self.assertEqual(_parse_serial(text), "2102354876ABCDEF")

    def test_cisco_inventory(self):
        text = (
            'NAME: "Chassis", DESCR: "Cisco IOS Software"\n'
            "PID: WS-C2960-24TT-L , VID: V03 , SN: FOC1234X5YZ\n"
        )
        self.assertEqual(_parse_serial(text), "FOC1234X5YZ")

    def test_error_output_returns_empty(self):
        self.assertEqual(_parse_serial("Error: Unrecognized command found at '^' position."), "")
        self.assertEqual(_parse_serial("<不支持 display esn>"), "")

    def test_garbage_returns_empty(self):
        self.assertEqual(_parse_serial("uptime is 0 week, 0 day"), "")


class TestErrorHint(unittest.TestCase):
    def test_detects_common_errors(self):
        for text in [
            "Error: Unrecognized command found at '^' position.",
            "Error:Too many parameters found at '^' position.",
            "% Invalid input detected at '^' marker.",
            "% Incomplete command.",
        ]:
            self.assertTrue(_looks_like_error(text), text)

    def test_normal_output_not_error(self):
        self.assertFalse(_looks_like_error("VRP (R) software, Version 5.110"))


class FakeConn:
    """第一条序列号命令故意报不支持，第二条返回正常回显。"""

    last = None

    def __init__(self, **params):
        self.params = params
        self.sent = []
        FakeConn.last = self

    def find_prompt(self):
        return "<TEST-SW-01>"

    def send_command(self, cmd, read_timeout=None):
        self.sent.append(cmd)
        if cmd == "display elabel":
            return "Error: Unrecognized command found at '^' position."
        if cmd == "display esn":
            return "ESN of this device: 2102354876ABCDEF1234"
        if "version" in cmd:
            return "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 5.110 (S5700 V200R001C00)\n"
        return "y" * 300

    def disconnect(self):
        pass


TABLE = {
    "huawei": {
        "netmiko_os": "huawei",
        "version": "display version",
        "config": "display current-configuration",
        "serial": ["display elabel", "display esn"],
    }
}


class TestFallbackCommands(unittest.TestCase):
    def test_unsupported_command_falls_through(self):
        orig = ssh_mod.ConnectHandler
        ssh_mod.ConnectHandler = lambda **kw: FakeConn(**kw)
        try:
            c = CliCollector(TABLE, transport="ssh")
            out = c.collect("127.0.0.1", {"brand": "huawei", "username": "a", "password": "b"})
        finally:
            ssh_mod.ConnectHandler = orig

        self.assertEqual(out["serial"], "2102354876ABCDEF1234", "应当落到第二条命令")
        sent = FakeConn.last.sent
        self.assertIn("display elabel", sent)
        self.assertIn("display esn", sent)
        self.assertLess(sent.index("display elabel"), sent.index("display esn"), "按配置顺序试")


if __name__ == "__main__":
    unittest.main()
