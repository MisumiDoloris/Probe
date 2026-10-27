"""台账字段的显示规则：什么算取到、运行时长怎么变成人话。

Word 报告与 Excel 台账是同一份数据的两个出口，必须对同一台设备说同一句话。
这两个函数放一处，别两边各写一套，否则迟早一边改了另一边没改。
"""

import re

# 采集层对「设备不认这条命令」的标记，形如 <不支持 display version>。
# 这是内部信号，不该原样出现在甲方签字的台账里。
UNSUPPORTED_RE = re.compile(r"^<不支持\s*(.*?)>$")


def clean_value(value):
    """取一个字段的显示值，返回 (显示值, 空着的原因)。

    原因非空就说明这不是真的值。两种不算取到：空字符串，以及
    <不支持 命令> 这种占位符。占位符本身要留个痕迹，不然报告里
    看不出「设备不认这条命令」和「命令没跑」的区别。
    """
    val = str(value if value is not None else "").strip()
    if not val:
        return "", ""
    m = UNSUPPORTED_RE.match(val)
    if m:
        return "", f"设备不认 {m.group(1).strip().rstrip('>')} 这条命令"
    return val, ""


def fmt_uptime(raw):
    """运行时长转人话。

    SNMP 给的是 TimeTicks（百分之一秒），482910400 原样印在台账上，
    甲方只会问这是什么。SSH 采到的是「0 week, 0 day, 4 hours」，
    本来就是人话，原样留着。
    """
    val = str(raw or "").strip()
    if not val.isdigit():
        return val
    secs = int(val) // 100
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分"
