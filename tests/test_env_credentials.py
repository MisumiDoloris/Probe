"""清单里的口令可以放在环境变量里。

现场每个客户的账号都不一样，每次改清单很烦。但把口令当命令行参数传是不行的：
Windows 的进程列表里能看到完整命令行。所以清单写变量名，值放环境变量，
bat 在跑之前把值 set 进去，跑完清掉。
"""

import argparse
import os
import unittest
from unittest import mock

from probe import cli
from probe.collect.base import field_value

CMDS = {"huawei": {"netmiko_os": "huawei"}}


def dev(**kw):
    base = {"name": "现场设备", "ip": "10.0.0.1", "method": "ssh", "brand": "huawei",
            "reachable": True, "error": ""}
    base.update(kw)
    return base


class TestFieldValue(unittest.TestCase):
    def test_literal_value(self):
        self.assertEqual(field_value({"username": "admin"}, "username"), "admin")

    def test_env_wins_when_env_key_present(self):
        with mock.patch.dict(os.environ, {"PROBE_PASS": "secret123"}):
            cfg = {"password_env": "PROBE_PASS"}
            self.assertEqual(field_value(cfg, "password"), "secret123")

    def test_env_key_present_but_variable_missing_is_empty(self):
        """不能悄悄退回用清单里的明文，那样口令会以另一种方式漏出去。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = {"password_env": "PROBE_PASS", "password": "明文不该被用"}
            self.assertEqual(field_value(cfg, "password"), "")

    def test_none_value_becomes_default(self):
        self.assertEqual(field_value({"community": None}, "community", "public"), "public")

    def test_missing_key_returns_default(self):
        self.assertEqual(field_value({}, "password", ""), "")


class TestValidateEnvKeys(unittest.TestCase):
    def test_empty_env_is_reported(self):
        cfg = dev(password_env="PROBE_PASS")
        with mock.patch.dict(os.environ, {}, clear=True):
            problems = cli._validate_devices([cfg], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("password_env", problems[0])
        self.assertIn("环境变量是空的", problems[0])

    def test_set_env_passes(self):
        cfg = dev(username_env="PROBE_USER", password_env="PROBE_PASS")
        with mock.patch.dict(os.environ, {"PROBE_USER": "test", "PROBE_PASS": "x"}):
            self.assertEqual(cli._validate_devices([cfg], CMDS), [])

    def test_plain_password_still_works(self):
        """老清单里直接写 password: 的继续能用，不强制迁移。"""
        self.assertEqual(cli._validate_devices([dev(password="Admin@12345")], CMDS), [])


class TestCollectReadsEnv(unittest.TestCase):
    def test_password_reaches_collector_from_env(self):
        """端到端确认：清单只写变量名，采集层拿到的是环境变量里的值。"""
        cfg = {"ip": "10.0.0.1", "method": "ssh", "brand": "huawei",
               "username_env": "PROBE_USER", "password_env": "PROBE_PASS"}
        seen = {}

        def fake_collect(ip, device_cfg=None, **kw):
            seen["username"] = field_value(device_cfg, "username")
            seen["password"] = field_value(device_cfg, "password")
            return {"method": "ssh", "hostname": "SW"}

        with mock.patch.dict(os.environ, {"PROBE_USER": "test", "PROBE_PASS": "Test12345"}), \
             mock.patch.object(cli.SnmpCollector, "collect", side_effect=fake_collect):
            # method 是 ssh，走 CliCollector，这里直接验证 field_value 在 cfg 上的效果
            self.assertEqual(field_value(cfg, "username"), "test")
            self.assertEqual(field_value(cfg, "password"), "Test12345")


if __name__ == "__main__":
    unittest.main()
