"""采集层接线测试：不连设备，只验参数和守卫。

走隧道那条路（笔记本 eNSP 的设备挂在服务器 127.0.0.1:20022）靠的就是这里两个参数传对了：
自定义端口要传到 netmiko，telnet 要换成 *_telnet 的 device_type。
把 ConnectHandler 换成假的，能看清真正发了什么，不用真设备。
"""

import unittest

from probe.collect import ssh as ssh_mod
from probe.collect.ssh import CliCollector


class FakeConn:
    def __init__(self, **params):
        self.params = params
        self.sent = []

    def find_prompt(self):
        return "<TEST-SW-01>"

    def send_command(self, cmd, read_timeout=None):
        self.sent.append(cmd)
        if "version" in cmd:
            return "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 5.170\n"
        return "x" * 600

    def disconnect(self):
        pass


class Patched:
    """把 ConnectHandler 换掉，记录参数。"""

    def __init__(self):
        self.conn = None
        self._orig = ssh_mod.ConnectHandler

    def __enter__(self):
        def fake(**params):
            self.conn = FakeConn(**params)
            return self.conn

        ssh_mod.ConnectHandler = fake
        return self

    def __exit__(self, *exc):
        ssh_mod.ConnectHandler = self._orig


TABLE = {
    "huawei": {
        "netmiko_os": "huawei",
        "version": "display version",
        "config": "display current-configuration",
    }
}


class TestWiring(unittest.TestCase):
    def test_custom_port_reaches_netmiko(self):
        """清单里写 port: 20022，必须原样传给 netmiko，而不是被 22 覆盖。"""
        c = CliCollector(TABLE, transport="ssh")
        with Patched() as p:
            out = c.collect("127.0.0.1", {"brand": "huawei", "username": "a",
                                          "password": "b", "port": 20022})
        self.assertEqual(p.conn.params["port"], 20022)
        self.assertEqual(p.conn.params["device_type"], "huawei")
        self.assertEqual(out["hostname"], "TEST-SW-01")
        self.assertIn("VRP", out["version"])

    def test_default_ssh_port(self):
        c = CliCollector(TABLE, transport="ssh")
        with Patched() as p:
            c.collect("127.0.0.1", {"brand": "huawei", "username": "a", "password": "b"})
        self.assertEqual(p.conn.params["port"], 22)

    def test_telnet_appends_suffix_and_defaults_23(self):
        """telnet 要换成 huawei_telnet，默认端口 23，不能还用 22。"""
        c = CliCollector(TABLE, transport="telnet")
        with Patched() as p:
            c.collect("127.0.0.1", {"brand": "huawei", "username": "a", "password": "b"})
        self.assertEqual(p.conn.params["device_type"], "huawei_telnet")
        self.assertEqual(p.conn.params["port"], 23)

    def test_only_readonly_commands_sent(self):
        """真发出去的命令逐条过守卫，一条写命令都不能出现在 sent 里。"""
        from probe.ro_guard import is_readonly

        c = CliCollector(TABLE, transport="ssh")
        with Patched() as p:
            c.collect("127.0.0.1", {"brand": "huawei", "username": "a", "password": "b"})
        self.assertTrue(p.conn.sent, "一条命令都没发，测试没意义")
        for cmd in p.conn.sent:
            self.assertTrue(is_readonly(cmd), f"发出了非只读命令: {cmd!r}")


if __name__ == "__main__":
    unittest.main()
