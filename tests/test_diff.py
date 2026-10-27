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


if __name__ == "__main__":
    unittest.main()
