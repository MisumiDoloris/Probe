"""同一台设备写多条采集方式时的合并逻辑。

场景：清单里同一 IP 写一条 SSH、一条 SNMP。SSH 取版本和配置，SNMP 补运行时长，
台账上只能有一行，不能变成一个 IP 两行。
"""

import argparse
import unittest
from unittest import mock

from probe import cli


class TestMergeInto(unittest.TestCase):
    def test_fill_empty_only(self):
        base = {"version": "VRP 5.110", "model": "", "uptime": "", "raw": {"config": "abc"}}
        extra = {"version": "别的版本", "model": "S5700", "uptime": "1 hour", "raw": {"sysDescr": "descr"}}
        out = cli._merge_into(base, extra)
        self.assertEqual(out["version"], "VRP 5.110", "已有值不该被覆盖")
        self.assertEqual(out["model"], "S5700")
        self.assertEqual(out["uptime"], "1 hour")
        self.assertEqual(out["raw"], {"config": "abc", "sysDescr": "descr"})


class TestCollectMerge(unittest.TestCase):
    def test_same_ip_two_methods_one_row(self):
        cfgs = [
            {"ip": "192.168.56.10", "method": "snmp", "community": "public", "brand": "huawei"},
            {"ip": "192.168.56.10", "method": "ssh", "brand": "huawei"},
        ]
        def fake_collect(cfg, commands):
            if cfg["method"] == "snmp":
                return {"method": "snmp", "hostname": "SW", "uptime": "1 hour",
                        "version": "descr", "raw": {"sysDescr": "descr", "sysName": "SW"}}
            return {"method": "ssh", "hostname": "SW", "version": "VRP 5.110",
                    "model": "S5700", "vendor": "华为", "uptime": "",
                    "raw": {"version": "VRP 5.110", "config": "cfg"}}

        args = argparse.Namespace(note="", devices=None, excel="x.xlsx", no_excel=True)
        captured = {}

        def fake_save(results, note="", **kw):
            captured["results"] = results
            return "snapshots/fake.json"

        with mock.patch.object(cli, "_load_devices", return_value=cfgs), \
             mock.patch.object(cli, "_collect_one", side_effect=fake_collect), \
             mock.patch.object(cli.snapshot, "save", side_effect=fake_save):
            cli.cmd_collect(args)

        rows = captured["results"]
        self.assertEqual(len(rows), 1, "同一 IP 只能出一行")
        row = rows[0]
        self.assertEqual(row["method"], "ssh+snmp")
        self.assertEqual(row["model"], "S5700", "SSH 的型号要留下")
        self.assertEqual(row["uptime"], "1 hour", "SNMP 的运行时长要补进来")
        self.assertIn("config", row["raw"])
        self.assertIn("sysDescr", row["raw"])
        self.assertEqual(row["error"], "")

    def test_one_method_fails_other_still_ok(self):
        cfgs = [
            {"ip": "10.0.0.1", "method": "ssh", "brand": "huawei"},
            {"ip": "10.0.0.1", "method": "snmp", "community": "public"},
        ]
        def fake_collect(cfg, commands):
            if cfg["method"] == "snmp":
                raise RuntimeError("SNMP 失败 超时")
            return {"method": "ssh", "hostname": "SW", "version": "VRP", "raw": {}}

        args = argparse.Namespace(note="", devices=None, excel="x.xlsx", no_excel=True)
        captured = {}

        def fake_save(results, note="", **kw):
            captured["results"] = results
            return "snapshots/fake.json"

        with mock.patch.object(cli, "_load_devices", return_value=cfgs), \
             mock.patch.object(cli, "_collect_one", side_effect=fake_collect), \
             mock.patch.object(cli.snapshot, "save", side_effect=fake_save):
            cli.cmd_collect(args)

        row = captured["results"][0]
        self.assertTrue(row["reachable"])
        self.assertEqual(row["method"], "ssh")
        self.assertEqual(row["error"], "", "一种方式成功就不算失败")


if __name__ == "__main__":
    unittest.main()
