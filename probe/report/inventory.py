"""台账导出。

一层是台账，给运维自己查，Excel 一条设备一行。
一层是报告，给甲方和做等保整改的人，Word 出。

这里只管台账这一层。
"""

import os

import pandas as pd

COLUMNS = [
    ("ip", "IP 地址"),
    ("hostname", "设备名"),
    ("vendor", "品牌"),
    ("model", "型号"),
    ("version", "版本"),
    ("serial", "序列号"),
    ("uptime", "运行时长"),
    ("method", "采集方式"),
    ("error", "采集异常"),
]


def to_records(devices):
    rows = []
    for d in devices:
        row = {}
        for key, label in COLUMNS:
            val = d.get(key, "")
            if key == "version" and isinstance(val, str) and len(val) > 80:
                val = val[:80]
            row[label] = val
        rows.append(row)
    return rows


def export_excel(devices, path="output/台账.xlsx"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = to_records(devices)

    df = pd.DataFrame(rows, columns=[label for _, label in COLUMNS])

    # 第二张表只放有问题的，运维一眼看这里
    issues = df[(df["采集异常"].astype(str).str.strip() != "") | (df["版本"].astype(str).str.strip() == "")]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="设备台账", index=False)
        issues.to_excel(writer, sheet_name="待核实", index=False)
        _autosize(writer.sheets["设备台账"])
        _autosize(writer.sheets["待核实"])
    return path


def _autosize(ws):
    """列宽按内容给，中文按两倍算。"""
    for col in ws.columns:
        width = 10
        letter = col[0].column_letter
        for cell in col:
            v = str(cell.value or "")
            w = sum(2 if ord(ch) > 127 else 1 for ch in v)
            width = max(width, min(w + 2, 60))
        ws.column_dimensions[letter].width = width
