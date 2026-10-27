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
    base = {"name": "测试交换机", "ip": "10.0.0.1", "method": "snmp", "community": "public",
            "brand": "huawei", "reachable": True, "error": ""}
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


class TestBlankValueIsNotAValue(unittest.TestCase):
    """YAML 里写 `ip:` 留空，值是 None。先 str() 再判空会把 None 变成 "None" 放行。"""

    def test_ip_key_present_but_empty(self):
        problems = cli._validate_devices([{"name": "核心", "ip": None, "method": "snmp"}], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("没写 ip", problems[0])

    def test_ip_is_a_list(self):
        problems = cli._validate_devices([{"name": "核心", "ip": ["10.0.0.1"], "method": "snmp"}], CMDS)
        self.assertTrue(problems)

    def test_empty_ip_does_not_crash_collect(self):
        """以前这里抛 AttributeError，退出码 1，被当成「全部没采到」。"""
        with open("/tmp/probe_test_ipnull.yaml", "w", encoding="utf-8") as f:
            f.write("devices:\n  - name: 核心交换机\n    ip:\n    method: snmp\n    community: public\n")
        try:
            rc = cli.cmd_collect(argparse.Namespace(note="", devices="/tmp/probe_test_ipnull.yaml",
                                                    excel="x.xlsx", no_excel=True))
            self.assertEqual(rc, 2)
        finally:
            os.unlink("/tmp/probe_test_ipnull.yaml")


class TestCaseInsensitive(unittest.TestCase):
    """客户清单从 Excel 转过来，method 和 brand 大小写乱是常态。"""

    def test_method_upper_is_accepted_and_normalised(self):
        cfg = dev(method="SSH", brand="Huawei")
        self.assertEqual(cli._validate_devices([cfg], CMDS), [])
        self.assertEqual(cfg["method"], "ssh", "必须写回规范值，采集层是拿它做 == 比较的")
        self.assertEqual(cfg["brand"], "huawei")

    def test_telnet_upper_is_not_routed_to_ssh(self):
        """只放行不归一的话，Telnet 会走 SSH 去连 22 端口。"""
        cfg = dev(method="Telnet")
        self.assertEqual(cli._validate_devices([cfg], CMDS), [])
        self.assertEqual(cfg["method"], "telnet")

    def test_surrounding_spaces_are_cleaned(self):
        cfg = dev(method=" ssh ", brand=" huawei ")
        self.assertEqual(cli._validate_devices([cfg], CMDS), [])
        self.assertEqual(cfg["method"], "ssh")
        self.assertEqual(cfg["brand"], "huawei")


class TestMissingMethod(unittest.TestCase):
    def test_missing_method_is_reported_not_defaulted(self):
        """不写 method 就默认 snmp，设备只开 Telnet 时回来的错是超时，方向全偏。"""
        cfg = dev()
        cfg.pop("method")
        problems = cli._validate_devices([cfg], CMDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("没写 method", problems[0])


class TestBlankLedgerIsNotDeliverable(unittest.TestCase):
    """连上了但一个字段都没取到，结论不能写「均取到回显」。"""

    def test_all_blank_is_needs_review(self):
        d = dev(ip="10.0.0.1", method="ssh", reachable=True, hostname="SW", raw={})
        verdict, why = doc_report._verdict([d], None)
        self.assertEqual(verdict, "需核实")
        self.assertIn("一个字段都没取到", why)

    def test_partly_blank_is_needs_review(self):
        ok = dev(ip="10.0.0.1", vendor="华为", model="S5700", version="VRP", serial="S1", uptime="1")
        blank = dev(ip="10.0.0.2", method="ssh", reachable=True, raw={})
        verdict, why = doc_report._verdict([ok, blank], None)
        self.assertEqual(verdict, "需核实")
        self.assertIn("1 台设备连上了但字段全空", why)

    def test_one_field_taken_is_enough_to_pass(self):
        d = dev(ip="10.0.0.1", version="VRP 5.110")
        self.assertEqual(doc_report._verdict([d], None)[0], "可交付")


class TestReadonlyStatementFollowsVerdict(unittest.TestCase):
    """结论说不能当盘点结论用，只读声明就不许说「可作为资产盘点记录」。"""

    def _text(self, devices):
        doc = doc_report.build({"taken_at": "20261027_000000", "devices": devices})
        return "\n".join(p.text for p in doc.paragraphs)

    def test_failed_report_does_not_claim_inventory_record(self):
        text = self._text([dev(ip="10.0.0.1", reachable=False, error="连接超时", raw={})])
        self.assertNotIn("因此本报告可作为资产盘点与配置基线的记录", text)
        self.assertIn("不能单独作为资产盘点", text)

    def test_clean_report_still_claims_it(self):
        text = self._text([dev(ip="10.0.0.1", vendor="华为", model="S5700", version="VRP",
                               serial="S1", uptime="1")])
        self.assertIn("因此本报告可作为资产盘点与配置基线的记录", text)


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


class TestNetworkValidation(unittest.TestCase):
    def test_empty(self):
        self.assertTrue(cli._validate_network(""))

    def test_garbage(self):
        self.assertIn("不是合法的网段", cli._validate_network("abc"))

    def test_prefix_too_long(self):
        self.assertTrue(cli._validate_network("192.168.1.0/33"))

    def test_too_big(self):
        """IPv6 的 /64 会把 2^64 个地址整体物化，程序静默卡死。"""
        msg = cli._validate_network("fd00::/64")
        self.assertIn("太多", msg)

    def test_normal(self):
        self.assertEqual(cli._validate_network("192.168.56.0/24"), "")

    def test_single_host(self):
        self.assertEqual(cli._validate_network("192.168.56.10/32"), "")


class TestCommandTableValidation(unittest.TestCase):
    def test_unknown_key_is_reported(self):
        """把 version 写成 verison，既不进守卫也不会下发，采集算成功、字段全空。"""
        problems = cli._validate_commands(
            {"huawei": {"netmiko_os": "huawei", "verison": "display version"}}
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("verison", problems[0])

    def test_table_not_a_dict(self):
        problems = cli._validate_commands({"huawei": "display version"})
        self.assertTrue(problems)
        self.assertIn("huawei", problems[0])

    def test_normal_table(self):
        self.assertEqual(
            cli._validate_commands({"huawei": {"netmiko_os": "huawei", "version": "display version"}}),
            [],
        )

    def test_repo_table_is_clean(self):
        """仓库自带的命令表必须过校验 —— 这条会抓住「写了但从来不采」的废配置。"""
        real = cli._load_yaml("commands.yaml")
        self.assertEqual(cli._validate_commands(real), [])


class TestLoadDevices(unittest.TestCase):
    def _write(self, text, name="dev.yaml"):
        path = os.path.join(tempfile.mkdtemp(prefix="probe_load_"), name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_missing_file(self):
        with self.assertRaises(RuntimeError) as ctx:
            cli._load_devices("/tmp/绝对不存在的清单_probe.yaml")
        self.assertIn("找不到设备清单", str(ctx.exception))

    def test_broken_yaml(self):
        path = self._write("devices:\n  - name: A\n   ip: 10.0.0.1\n")   # 缩进少一格
        with self.assertRaises(RuntimeError) as ctx:
            cli._load_devices(path)
        self.assertIn("YAML 格式不对", str(ctx.exception))

    def test_tab_indent(self):
        path = self._write("devices:\n\t- name: A\n")
        with self.assertRaises(RuntimeError) as ctx:
            cli._load_devices(path)
        self.assertIn("YAML", str(ctx.exception))

    def test_top_level_is_a_list(self):
        path = self._write("- name: A\n  ip: 10.0.0.1\n")
        with self.assertRaises(RuntimeError) as ctx:
            cli._load_devices(path)
        self.assertIn("顶层是一个列表", str(ctx.exception))

    def test_normal(self):
        path = self._write("devices:\n  - name: A\n    ip: 10.0.0.1\n    method: snmp\n")
        self.assertEqual(len(cli._load_devices(path)), 1)


class TestOutPathValidation(unittest.TestCase):
    def test_directory(self):
        self.assertIn("是一个目录", cli._check_out_path("/tmp", "台账", ".xlsx"))

    def test_no_extension(self):
        self.assertIn("没写扩展名", cli._check_out_path("/tmp/台账", "台账", ".xlsx"))

    def test_normal(self):
        self.assertEqual(cli._check_out_path("/tmp/台账.xlsx", "台账", ".xlsx"), "")


class TestInventoryToleratesDirtyEntries(unittest.TestCase):
    def test_dirty_entries_skipped(self):
        from probe.report import inventory
        rows = inventory.to_records([None, "坏条目", {"ip": "10.0.0.1", "uptime": "482910400"}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["IP 地址"], "10.0.0.1")
        self.assertEqual(rows[0]["运行时长"], "55 天 21 小时", "台账也要把 ticks 转成人话")


class TestSnapshotLoadMoreErrors(unittest.TestCase):
    def test_directory_is_not_a_snapshot(self):
        with self.assertRaises(RuntimeError) as ctx:
            snapshot.load("/tmp")
        self.assertIn("是一个目录", str(ctx.exception))

    def test_gbk_file_is_named(self):
        path = os.path.join(tempfile.mkdtemp(prefix="probe_gbk_"), "snap.json")
        with open(path, "w", encoding="gbk") as f:
            f.write('{"devices": [{"ip": "10.0.0.1", "note": "中文"}]}')
        with self.assertRaises(RuntimeError) as ctx:
            snapshot.load(path)
        self.assertIn("UTF-8", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
