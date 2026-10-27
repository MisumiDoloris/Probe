"""报告层的口径测试。

这一层以前完全没测试，所以 v0.7 把「待补采」的白名单缩成只剩序列号，
32 条单测照样全绿，报告却开始对甲方隐瞒：品牌型号空着，第 4 节一个字不提。

这里钉三条规矩：
一，台账里每一个空白都必须在第 4 节出现，并写清是补采还是重跑采集。
二，内部占位符（<不支持 命令>）不许出现在台账里。
三，运行时长是给人看的，不是 ticks。

全部用合成快照，不连设备。
"""

import unittest

from probe.report import doc_report


def dev(ip="192.168.56.10", method="snmp", reachable=True, error="", **kw):
    d = {
        "ip": ip, "hostname": "TEST-SW-01", "vendor": "", "model": "", "version": "",
        "serial": "", "uptime": "", "method": method, "error": error,
        "reachable": reachable, "raw": {},
    }
    d.update(kw)
    return d


def snap(devices, at="20261024_210000"):
    return {"taken_at": at, "devices": devices}


def flat(doc):
    """段落 + 表格单元格拍平，断言时不用关心它印在哪张表里。"""
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


class TestBlankFieldsMustBeExplained(unittest.TestCase):
    def test_snmp_parsed_nothing_vendor_model_still_listed(self):
        """纯 SNMP 采到一台 Dell，sysDescr 解析不出品牌型号：两栏空着，必须进第 4 节。"""
        d = dev(vendor="", model="", uptime="12003400",
                raw={"sysDescr": "Dell PowerConnect 5524, Software Version 2.0.0.5"})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("字段待补采", text)
        self.assertIn("品牌", text)
        self.assertIn("型号", text)
        self.assertNotIn("本次没有采集失败，台账里也没有空着的字段", text)

    def test_serial_on_snmp_blames_protocol_not_device(self):
        """序列号空要说是协议不提供，别让甲方以为设备坏了。"""
        d = dev(vendor="华为", model="S5700", version="VRP 5.110", uptime="482910400",
                raw={"sysDescr": "Huawei VRP (S5700 V200R001C00)"})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("SNMP 协议不提供", text)

    def test_parsable_but_empty_says_rerun_collection(self):
        """sysDescr 里明明有 S5700，型号栏却是空的：这不是设备的问题，是快照没入库。"""
        d = dev(vendor="", model="", uptime="482910400",
                raw={"sysDescr": "Huawei Versatile Routing Platform Software (S5700 V200R019C10SPC500)"})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("需重跑采集", text)

    def test_merged_method_also_checked(self):
        """SSH+SNMP 合并采集的设备不能被整台跳过，这是 v0.7 之前就有的老洞。"""
        d = dev(method="ssh+snmp", vendor="华为", model="", version="", serial="",
                uptime="99001", raw={"sysDescr": "Huawei VRP"})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("字段待补采", text)
        self.assertIn("型号", text)

    def test_complete_device_gets_the_clean_sentence(self):
        d = dev(vendor="华为", model="S5700", version="VRP 5.110", serial="2102351ABC",
                uptime="0 week, 0 day, 4 hours", raw={"sysDescr": "Huawei VRP (S5700)"})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("本次没有采集失败，台账里也没有空着的字段", text)


class TestNoInternalPlaceholders(unittest.TestCase):
    def test_unsupported_command_marker_never_reaches_ledger(self):
        """<不支持 display version> 是采集层的内部标记，进了台账甲方看不懂。"""
        d = dev(method="ssh", vendor="华为", version="<不支持 display version>",
                serial="<不支持 display device>", uptime="99001", raw={})
        text = flat(doc_report.build(snap([d])))
        self.assertNotIn("<不支持", text)
        self.assertIn("设备不认", text)      # 但原因要说出来
        self.assertIn("未采集到", text)      # 台账上照样是这四个字


class TestUptimeReadable(unittest.TestCase):
    def test_ticks_become_days(self):
        d = dev(vendor="华为", model="S5700", version="VRP", serial="SN1",
                uptime="482910400", raw={})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("55 天", text)
        self.assertNotIn("482910400", text)

    def test_ssh_human_uptime_kept(self):
        d = dev(vendor="华为", model="S5700", version="VRP", serial="SN1",
                uptime="0 week, 0 day, 4 hours", raw={})
        text = flat(doc_report.build(snap([d])))
        self.assertIn("0 week, 0 day, 4 hours", text)


class TestStatsArithmetic(unittest.TestCase):
    def test_total_equals_ok_plus_failed(self):
        """探活不通但没有 error 的设备，既不算成功也不算失败会让汇总表加起来对不上。"""
        devices = [
            dev(ip="10.0.0.1", vendor="华为", model="S5700", version="VRP", serial="S1", uptime="1"),
            dev(ip="10.0.0.2", reachable=False, raw={}),
        ]
        total, ok, failed, _ = doc_report._stats(devices)
        self.assertEqual(total, len(ok) + len(failed))
        self.assertEqual(len(failed), 1)

    def test_unreachable_device_blocks_deliverable(self):
        devices = [dev(ip="10.0.0.1", reachable=False, raw={})]
        verdict, why = doc_report._verdict(devices, None)
        self.assertEqual(verdict, "需核实")
        self.assertIn("采集失败", why)


class TestVerdictTiers(unittest.TestCase):
    def test_all_clean_is_deliverable(self):
        devices = [dev(vendor="华为", model="S5700", version="VRP", serial="S1", uptime="1")]
        self.assertEqual(doc_report._verdict(devices, None)[0], "可交付")

    def test_empty_snapshot_is_not_deliverable(self):
        self.assertEqual(doc_report._verdict([], None)[0], "需核实")

    def test_changes_raise_the_verdict(self):
        devices = [dev(vendor="华为", model="S5700", version="VRP", serial="S1", uptime="1")]
        diff = {"summary": {"added": 0, "removed": 0, "changed": 1}}
        self.assertEqual(doc_report._verdict(devices, diff)[0], "有变更需确认")

    def test_diff_summary_without_counts_does_not_crash(self):
        """summary 只带部分键时不许 KeyError，报告必须出得来。"""
        devices = [dev(vendor="华为", model="S5700", version="VRP", serial="S1", uptime="1")]
        diff = {"summary": {}}
        self.assertEqual(doc_report._verdict(devices, diff)[0], "可交付")


if __name__ == "__main__":
    unittest.main()
