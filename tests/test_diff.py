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


if __name__ == "__main__":
    unittest.main()
