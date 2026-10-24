"""只读守卫的验收用例（T01 / T02）。

不依赖 pytest，用标准库 unittest 写，装好 Python 就能跑：

    python -m unittest discover -s tests -v

用例清单是定死的十五条，来自验收方案里的 T01 与 T02。
放行的四条过了，说明白名单没误伤（尤其 display current-configuration 含 config 字样）；
拒绝的十一条全拒了，说明黑名单没漏。
"""

import unittest

from probe.ro_guard import assert_readonly, is_readonly, ReadOnlyViolation

# T01：必须放行。四条。
ALLOW = [
    "display current-configuration",
    "display version",
    "show running-config",
    "show ip interface brief",
]

# T02：必须拒绝。十一条。
DENY = [
    "system-view",
    "sys",
    "configure terminal",
    "write memory",
    "save",
    "reset saved-configuration",
    "undo interface GigabitEthernet0/0/1",
    "reload",
    "delete flash:/config.cfg",
    "copy running-config startup-config",
    "interface GigabitEthernet0/0/1",
]


class TestAllow(unittest.TestCase):
    def test_allow_list(self):
        """T01：四条查询命令全过，且返回的是去掉首尾空白的原命令。"""
        for cmd in ALLOW:
            with self.subTest(cmd=cmd):
                self.assertTrue(is_readonly(cmd), f"应该放行却拒了: {cmd!r}")
                self.assertEqual(assert_readonly(cmd), cmd)

    def test_allow_with_spaces(self):
        """前后带空格的同一条命令也过，守卫不能因为空格误判。"""
        for cmd in ALLOW:
            with self.subTest(cmd=cmd):
                self.assertTrue(is_readonly(f"  {cmd}  "))


class TestDeny(unittest.TestCase):
    def test_deny_list(self):
        """T02：十一条写操作全拒，且抛的是 ReadOnlyViolation。"""
        for cmd in DENY:
            with self.subTest(cmd=cmd):
                self.assertFalse(is_readonly(cmd), f"应该拒却放行了: {cmd!r}")
                with self.assertRaises(ReadOnlyViolation):
                    assert_readonly(cmd)

    def test_deny_case_insensitive(self):
        """大小写混写也拒，设备侧不区分大小写。"""
        for cmd in ("System-View", "SAVE", "Reload"):
            with self.subTest(cmd=cmd):
                self.assertFalse(is_readonly(cmd), f"大写形式漏了: {cmd!r}")

    def test_empty(self):
        """空命令抛异常，不能静默放过。"""
        with self.assertRaises(ReadOnlyViolation):
            assert_readonly("")
        with self.assertRaises(ReadOnlyViolation):
            assert_readonly("   ")


class TestCliCollectorGuard(unittest.TestCase):
    """采集层真的调了守卫：commands.yaml 里塞一条写命令，采集必须拒。"""

    def test_collector_blocks_write_command(self):
        from probe.collect.ssh import CliCollector

        fake_table = {
            "huawei": {
                "netmiko_os": "huawei",
                "version": "display version",
                "config": "save",          # 故意写错，看守卫拦不拦
            }
        }
        c = CliCollector(fake_table, transport="ssh")
        with self.assertRaises(ReadOnlyViolation):
            # 守卫在发命令之前就应该拒，不该走到连设备那一步。
            # 这里用不存在的地址，如果真的去连会超时而不是抛 Guard 异常。
            c.collect("203.0.113.1", {"brand": "huawei", "username": "x", "password": "y"})


if __name__ == "__main__":
    unittest.main()
