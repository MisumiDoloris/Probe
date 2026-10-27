"""错误翻译。报告里「待核实」的原因栏直接引用这些句子，所以每句都要能照着查。

2026-10-28 现场：Telnet 登不上，报的是「超时未认出提示符」，而设备实际说的是
`Error: Local authentication is rejected` —— 原因是这个用户的 service-type
只给了 ssh。提示里没提这一条，白查了半天。
"""

import unittest

from probe.collect.ssh import _explain


class FakeReadTimeout(Exception):
    """模拟 netmiko 的 ReadTimeout：带 command / output 两个属性。"""

    def __init__(self, message="", command="", output=""):
        super().__init__(message)
        self.command = command
        self.output = output


class TestExplain(unittest.TestCase):
    def test_local_auth_rejected_names_service_type(self):
        exc = FakeReadTimeout(
            message="Pattern not detected: '\\\\[[\\\\w.-]+\\\\]' in output",
            output="Login authentication\nUsername:\nPassword:\nError: Local authentication is rejected\n",
        )
        msg = _explain(exc)
        self.assertIn("拒绝本地认证", msg)
        self.assertIn("service-type", msg)
        self.assertNotIn("用户名或密码不对", msg, "这句会把人带到密码上去")

    def test_plain_auth_failure_still_says_password(self):
        exc = RuntimeError("Authentication failed.")
        self.assertIn("用户名或密码不对", _explain(exc))

    def test_readtimeout_mentions_service_type(self):
        msg = _explain(FakeReadTimeout(message="Pattern not detected: 'Change'"))
        self.assertIn("超时未认出提示符", msg)
        self.assertIn("service-type", msg)

    def test_refused(self):
        self.assertIn("端口拒绝连接", _explain(ConnectionRefusedError("refused")))

    def test_unknown_is_passed_through_but_short(self):
        msg = _explain(ValueError("x" * 500))
        self.assertLessEqual(len(msg), 140)


if __name__ == "__main__":
    unittest.main()
