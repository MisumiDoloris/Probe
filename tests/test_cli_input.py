"""入口处的输入校验。

这一组盯的是「写错的东西不许无声过去」：
清单里漏字段、method 拼错、品牌不在命令表，以前要么静默丢设备，要么
被当成别的方式去连；全部采集失败时退出码还是 0，脚本会读成成功。

快照那头同理：文件坏了、结构不对，要给一句话，不能甩 traceback，也不能
生成一份看着正常的报告。
"""

import argparse
import os
import tempfile
import unittest
from unittest import mock

from probe import cli
from probe.report import doc_report, snapshot

CMDS = {"huawei": {"label": "华为 VRP", "netmiko_os": "huawei"}}


def dev(**kw):
    base = {"name": "测试交换机", "ip": "10.0.0.1", "method": "snmp", "community": "public", "brand": "huawei"}
    base.update(kw)
    return base


class TestValidateDevices(unittest.TestCase):
    def test_missing_ip_is_reported(self):
        problems = cli._validate_devices([dev(ip="")], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("没写 ip", problems[0])

    def test_bad_method_is_reported_not_guessed(self):
        """method 写成 sshh 会被当成 SSH 去连，报回来的错把排查方向带偏。"""
        problems = cli._validate_devices([dev(method="sshh")], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("method", problems[0])
        self.assertIn("sshh", problems[0])

    def test_unknown_brand_is_reported(self):
        problems = cli._validate_devices([dev(method="ssh", brand="huaweii")], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("huaweii", problems[0])

    def test_snmp_does_not_need_brand(self):
        self.assertEqual(cli._validate_devices([dev(method="snmp", brand="")], CMDS), [])

    def test_good_list_passes(self):
        self.assertEqual(cli._validate_devices([dev(), dev(ip="10.0.0.2", method="ssh")], CMDS), [])

    def test_entry_not_a_dict(self):
        problems = cli._validate_devices(["10.0.0.1"], CMDS)
        self.assertTrue(problems)


class TestCollectRefusesBadList(unittest.TestCase):
    def _args(self):
        return argparse.Namespace(note="", devices=None, excel="x.xlsx", no_excel=True)

    def test_bad_list_returns_2_and_saves_nothing(self):
        """清单有一处问题就整批不采，也不能留下快照。"""
        saved = []
        with mock.patch.object(cli, "_load_devices", return_value=[dev(ip="")]), \
             mock.patch.object(cli.snapshot, "save", side_effect=lambda *a, **k: saved.append(1)):
            rc = cli.cmd_collect(self._args())
        self.assertEqual(rc, 2)
        self.assertEqual(saved, [], "清单不合格时不该存快照")

    def test_devices_not_a_list(self):
        with mock.patch.object(cli, "_load_devices", return_value={"ip": "10.0.0.1"}):
            self.assertEqual(cli.cmd_collect(self._args()), 2)


class TestCollectExitCode(unittest.TestCase):
    def _args(self):
        return argparse.Namespace(note="", devices=None, excel="x.xlsx", no_excel=True)

    def test_all_failed_is_nonzero(self):
        """全部失败还退 0 的话，脚本会读成采集成功。"""
        with mock.patch.object(cli, "_load_devices", return_value=[dev()]), \
             mock.patch.object(cli, "_collect_one", side_effect=RuntimeError("连接超时")), \
             mock.patch.object(cli.snapshot, "save", return_value="x.json"):
            rc = cli.cmd_collect(self._args())
        self.assertEqual(rc, 1)

    def test_partial_success_is_zero(self):
        cfgs = [dev(ip="10.0.0.1"), dev(ip="10.0.0.2")]

        def fake(cfg, commands):
            if cfg["ip"] == "10.0.0.2":
                raise RuntimeError("连接超时")
            return {"method": "snmp", "hostname": "SW", "uptime": "1", "raw": {}}

        with mock.patch.object(cli, "_load_devices", return_value=cfgs), \
             mock.patch.object(cli, "_collect_one", side_effect=fake), \
             mock.patch.object(cli.snapshot, "save", return_value="x.json"):
            self.assertEqual(cli.cmd_collect(self._args()), 0)


class TestSnapshotLoadErrors(unittest.TestCase):
    def test_broken_json_names_the_file_and_position(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("{不是合法 json")
            path = f.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                snapshot.load(path)
            msg = str(ctx.exception)
            self.assertIn(path, msg)
            self.assertIn("第", msg, "要给出坏在第几行")
        finally:
            os.unlink(path)

    def test_missing_file_is_human(self):
        with self.assertRaises(RuntimeError) as ctx:
            snapshot.load("/tmp/probe_绝不存在的快照.json")
        self.assertIn("找不到", str(ctx.exception))


class TestSnapshotShape(unittest.TestCase):
    def test_dict_devices_reported(self):
        bad = cli._check_snapshot_shape({"devices": {"ip": "10.0.0.1"}}, "x.json")
        self.assertTrue(bad)
        self.assertIn("x.json", bad)

    def test_none_devices_is_allowed(self):
        self.assertEqual(cli._check_snapshot_shape({"devices": None}, "x.json"), "")

    def test_normal_shape_ok(self):
        self.assertEqual(cli._check_snapshot_shape({"devices": []}, "x.json"), "")

    def test_top_level_not_object(self):
        self.assertTrue(cli._check_snapshot_shape([1, 2, 3], "x.json"))


class TestReportSurvivesBadSnapshot(unittest.TestCase):
    def test_none_devices_still_builds(self):
        doc = doc_report.build({"taken_at": "20261027_000000", "devices": None})
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("需核实", "\n".join(
            c.text for t in doc.tables for r in t.rows for c in r.cells
        ) + text)

    def test_non_dict_device_skipped_not_crash(self):
        doc = doc_report.build({"taken_at": "20261027_000000", "devices": ["坏条目", {"ip": "10.0.0.1"}]})
        self.assertIsNotNone(doc)


if __name__ == "__main__":
    unittest.main()
