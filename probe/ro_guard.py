"""只读守卫。

这个工具的第一条约束是只读。所有准备下发到设备的命令，必须先过这里。

依据是等保 2.0（GB/T 22239-2019）安全运维管理里对变更管理的要求
重要操作必须可审计。这个小工具做不到 4A（账号、认证、授权、审计），
所以写操作一律交给有审计能力的那一层，也就是人在堡垒机里执行。

工具这边只做两件事，查询，以及生成配置命令给人看。
"""

import re

# 明确禁止的写法。命中任意一条直接拒。
# 注意不能简单匹配 config 字样，因为 display current-configuration 是只读的，含 config。
DENY_PATTERNS = [
    (r"^system-view", "进入系统视图"),
    (r"^sys\b", "进入系统视图（简写）"),
    (r"^configure", "进入配置模式"),
    (r"^conf\s+t", "进入配置模式（简写）"),
    (r"^config\s", "进入配置模式"),
    (r"\bwrite\s+(memory|file|running)", "保存配置"),
    (r"\bsave\b", "保存配置"),
    (r"\berase\b", "擦除"),
    (r"\bdelete\b", "删除"),
    (r"\bformat\b", "格式化"),
    (r"\breload\b", "重启"),
    (r"\bundo\b", "撤销配置"),
    (r"\breset\b", "重置"),
    (r"\bclear\b", "清除"),
    (r"\bcopy\s", "复制覆盖"),
    (r"\brename\b", "改名"),
    (r"\bcommit\b", "提交"),
    (r"\bshutdown\b", "关闭接口"),
    (r"\bset\s+\S+", "设置"),
]

# 允许的命令前缀。只查不改。
ALLOW_PREFIXES = (
    "show ",
    "display ",
    "dis ",
    "sh ",
    "get ",
    "dir",
    "pwd",
    "ping ",
    "tracert ",
    "traceroute ",
    "more ",
    "?",
)


class ReadOnlyViolation(RuntimeError):
    """命中只读约束时抛出。"""


def assert_readonly(cmd):
    """校验一条命令是不是只读。不是就抛异常，绝不静默放过。"""
    text = (cmd or "").strip()
    if not text:
        raise ReadOnlyViolation("空命令")

    low = text.lower()

    if not low.startswith(ALLOW_PREFIXES):
        raise ReadOnlyViolation(f"不在只读白名单前缀里，拒绝下发: {text!r}")

    for pattern, why in DENY_PATTERNS:
        if re.search(pattern, low):
            raise ReadOnlyViolation(f"命中写操作（{why}），拒绝下发: {text!r}")

    return text


def is_readonly(cmd):
    """同名判断，返回布尔值，不抛异常，给测试和批量校验用。"""
    try:
        assert_readonly(cmd)
        return True
    except ReadOnlyViolation:
        return False
