"""从回显或 sysDescr 里认品牌与型号。

SSH 的 display version 和 SNMP 的 sysDescr 里都带型号，写法不同但关键词一样，
所以抽出来共用一份，别两边各写一套正则。
"""

import re

# 型号出现在括号里或者行首，比如 (S5700 V200R001C00)、S5735-L24T4X。
# 只认这几种前缀，认不出就留空，不猜。
MODEL_RE = re.compile(
    r"\b(S\d{4}[A-Za-z0-9-]*|AR\d{3,4}[A-Za-z0-9-]*|USG\d{4}[A-Za-z0-9-]*|"
    r"CE\d{4}[A-Za-z0-9-]*|NE\d{4}[A-Za-z0-9-]*|CloudEngine[ A-Za-z0-9-]+|"
    r"WS-C\d{4}[A-Za-z0-9-]*)\b"
)

# 品牌靠系统描述里的关键词判断，顺序有讲究，先匹配更具体的。
VENDOR_HINTS = (
    ("huawei", ("huawei", "versatile routing platform", "vrp")),
    ("h3c", ("h3c", "comware", "hp comware")),
    ("ruijie", ("ruijie", "rgos")),
    ("cisco", ("cisco", "ios software", "ios xe")),
)

VENDOR_NAMES = {"huawei": "华为", "h3c": "华三", "ruijie": "锐捷", "cisco": "思科"}


def parse_model(text):
    """从回显里捞型号，捞不到返回空串。"""
    m = MODEL_RE.search(text or "")
    return m.group(1) if m else ""


def parse_vendor(text, brand=""):
    """先看清单里写的 brand，再从系统描述里认，都不行就把 brand 原样返回。"""
    if brand:
        return VENDOR_NAMES.get(brand.lower(), brand)
    low = (text or "").lower()
    for key, hints in VENDOR_HINTS:
        if any(h in low for h in hints):
            return VENDOR_NAMES[key]
    return ""
