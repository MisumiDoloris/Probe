"""品牌与型号解析，SSH 的 display version 和 SNMP 的 sysDescr 共用一份。

真机上型号藏在括号里，sysDescr 也是同一句话，所以两条采集路径都要能认出来。
"""

import unittest

from probe.collect.parsing import parse_model, parse_vendor


class TestModel(unittest.TestCase):
    def test_huawei_from_display_version(self):
        text = "VRP (R) software, Version 5.110 (S5700 V200R001C00)"
        self.assertEqual(parse_model(text), "S5700")

    def test_huawei_from_sysdescr(self):
        text = ("Huawei Versatile Routing Platform Software VRP (R) software, "
                "Version 8.180 (S5735-L24T4X V200R019C10SPC500)")
        self.assertEqual(parse_model(text), "S5735-L24T4X")

    def test_router_and_firewall(self):
        self.assertEqual(parse_model("Version 5.170 (AR2220 V200R007C00)"), "AR2220")
        self.assertEqual(parse_model("USG6000V V500R005C20"), "USG6000V")

    def test_cisco_chassis(self):
        self.assertEqual(parse_model("cisco WS-C2960-24TT-L (PowerPC405) processor"), "WS-C2960-24TT-L")

    def test_nothing_found(self):
        self.assertEqual(parse_model("some unknown platform"), "")
        self.assertEqual(parse_model(""), "")


class TestVendor(unittest.TestCase):
    def test_from_sysdescr(self):
        self.assertEqual(parse_vendor("Huawei Versatile Routing Platform Software"), "华为")
        self.assertEqual(parse_vendor("H3C Comware Software, Version 7.1.070"), "华三")
        self.assertEqual(parse_vendor("Ruijie RGOS Software"), "锐捷")
        self.assertEqual(parse_vendor("Cisco IOS Software, C2960"), "思科")

    def test_brand_wins(self):
        self.assertEqual(parse_vendor("whatever", brand="huawei"), "华为")
        self.assertEqual(parse_vendor("whatever", brand="cisco"), "思科")

    def test_unknown(self):
        self.assertEqual(parse_vendor("some unknown platform"), "")


if __name__ == "__main__":
    unittest.main()
