"""diff 的三种配置比对情形。

用两份合成快照跑，不连设备。重点是「这次没取到配置回显」不能渲染成满屏删除行，
否则甲方会读成「设备配置被删了」。
"""

import unittest

from probe.report import diff as diff_mod


def snap(devs, at="20261024_000000"):
    return {"taken_at": at, "devices": devs}


def dev(ip, config, version="VRP 5.110", fp=None):
    return {
        "ip": ip,
        "hostname": "TEST-SW-01",
        "version": version,
        "raw": {"config": config},
        "fingerprint": fp if fp is not None else f"{ip}-{version}-{len(config)}",
    }


class TestConfigDiff(unittest.TestCase):
    def test_vlan_added_shows_evidence(self):
        old = snap([dev("192.168.56.10", "sysname A\n#\n", fp="a")])
        new = snap([dev("192.168.56.10", "sysname A\n#\nvlan batch 20\n", fp="b")])
        r = diff_mod.compare(old, new)
        self.assertEqual(r["summary"]["changed"], 1)
        item = r["changed"][0]
        self.assertIn("+vlan batch 20", item["config_diff"])
        self.assertEqual(item["config_diff_note"], "")

    def test_collect_failed_gives_note_not_deleted_lines(self):
        old = snap([dev("192.168.56.10", "sysname A\n#\nvlan batch 20\n", fp="a")])
        new = snap([dev("192.168.56.10", "", version="", fp="b")])
        r = diff_mod.compare(old, new)
        item = r["changed"][0]
        self.assertEqual(item["config_diff"], [], "不该吐出删除行")
        self.assertIn("本次没取到配置回显", item["config_diff_note"])
        text = "\n".join(diff_mod.to_lines(r))
        self.assertIn("本次没取到配置回显", text)
        self.assertNotIn("-vlan batch 20", text)

    def test_first_time_comparable(self):
        old = snap([dev("192.168.56.10", "", version="", fp="a")])
        new = snap([dev("192.168.56.10", "sysname A\n#\n", fp="b")])
        item = diff_mod.compare(old, new)["changed"][0]
        self.assertIn("第一次可比", item["config_diff_note"])
        self.assertEqual(item["config_diff"], [])


class TestNoFalseConfigClaim(unittest.TestCase):
    """指纹变了不等于配置变了。

    指纹里含版本号，所以一次版本升级会让指纹变，而配置回显一个字没动。
    以前只要指纹变就无条件加一条「配置有变化」，报告于是宣称配置被改过，
    却一行证据都列不出来 —— 甲方没法签这个字。
    """

    def test_version_only_change_is_not_config_change(self):
        old = snap([dev("192.168.56.10", "sysname A\n#\n", version="VRP 5.110", fp="a")])
        new = snap([dev("192.168.56.10", "sysname A\n#\n", version="VRP 5.170", fp="b")])
        item = diff_mod.compare(old, new)["changed"][0]
        fields = [c[0] for c in item["changes"]]
        self.assertIn("version", fields)
        self.assertNotIn("config", fields, "配置回显一样，不许说配置变了")
        self.assertEqual(item["config_diff"], [])

    def test_real_config_change_still_claims_config(self):
        old = snap([dev("192.168.56.10", "sysname A\n#\n", fp="a")])
        new = snap([dev("192.168.56.10", "sysname A\n#\nvlan batch 20\n", fp="b")])
        item = diff_mod.compare(old, new)["changed"][0]
        self.assertIn("config", [c[0] for c in item["changes"]])
        self.assertIn("+vlan batch 20", item["config_diff"])

    def test_hostname_only_change_is_not_config_change(self):
        old = snap([dict(dev("192.168.56.10", "sysname A\n#\n", fp="a"))])
        new_dev = dev("192.168.56.10", "sysname A\n#\n", fp="a2")
        new_dev["hostname"] = "NEW-NAME"
        item = diff_mod.compare(old, snap([new_dev]))["changed"][0]
        fields = [c[0] for c in item["changes"]]
        self.assertIn("hostname", fields)
        self.assertNotIn("config", fields)


class TestNoComparisonWhenOneSideFailed(unittest.TestCase):
    """上一轮没采到，这一轮采到了，不是「发生变化」。"""

    def dev_full(self, ip="10.0.0.1", **kw):
        d = {"ip": ip, "hostname": "SW-01", "version": "VRP 5.110", "reachable": True,
             "error": "", "raw": {"config": "sysname SW-01\n"}, "fingerprint": "bbb"}
        d.update(kw)
        return d

    def test_failed_last_round_is_not_a_change(self):
        old = snap([{"ip": "10.0.0.1", "reachable": False, "hostname": "", "version": "",
                     "error": "认证失败", "raw": {}, "fingerprint": "aaa"}])
        new = snap([self.dev_full()])
        r = diff_mod.compare(old, new)
        self.assertEqual(r["summary"]["changed"], 0, "上次没采到，不能算变更")
        self.assertEqual(r["uncomparable"], ["10.0.0.1"])

    def test_failed_this_round_is_not_a_change(self):
        old = snap([self.dev_full()])
        new = snap([{"ip": "10.0.0.1", "reachable": False, "error": "连接超时", "raw": {},
                     "fingerprint": "ccc"}])
        r = diff_mod.compare(old, new)
        self.assertEqual(r["summary"]["changed"], 0)
        self.assertIn("10.0.0.1", r["uncomparable"])

    def test_uncomparable_is_said_out_loud(self):
        old = snap([{"ip": "10.0.0.1", "reachable": False, "error": "x", "raw": {}, "fingerprint": "a"}])
        new = snap([self.dev_full()])
        text = "\n".join(diff_mod.to_lines(diff_mod.compare(old, new)))
        self.assertIn("没有可比数据", text)

    def test_old_snapshot_without_reachable_field_still_compares(self):
        """v0.5 以前的快照没有 reachable 字段，缺字段要按老行为照常比。"""
        old = snap([{"ip": "10.0.0.1", "hostname": "SW-01", "version": "VRP 5.110",
                     "raw": {"config": "sysname A\n"}, "fingerprint": "a"}])
        new = snap([self.dev_full(fingerprint="b")])
        r = diff_mod.compare(old, new)
        self.assertEqual(r["uncomparable"], [])
        self.assertEqual(r["summary"]["changed"], 1)

    def test_missing_ip_entry_is_skipped_not_crash(self):
        old = snap([{"hostname": "没有 ip 的设备", "fingerprint": "a"}])
        new = snap([self.dev_full()])
        r = diff_mod.compare(old, new)
        self.assertIsInstance(r["uncomparable"], list)


if __name__ == "__main__":
    unittest.main()
