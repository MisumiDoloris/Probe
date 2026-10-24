"""Word 巡检报告层。

只吃快照（可选一份对比结果），不碰采集层。采集方式换了这里一行不用动。
出一份能交给甲方的东西：封面、结论、台账、异常、变更、只读声明、签字栏。
"""

import os
import re
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

FONT_BODY = "仿宋"
FONT_HEAD = "黑体"
PLACEHOLDER = "＿＿＿＿"

# 台账里列出来的字段。空值一律写「未采集到」，不留白让人猜。
LEDGER = [
    ("ip", "IP 地址"),
    ("hostname", "设备名"),
    ("vendor", "品牌"),
    ("model", "型号"),
    ("version", "版本"),
    ("serial", "序列号"),
    ("uptime", "运行时长"),
    ("method", "采集方式"),
]

# SNMP 能拿到的只有 sysDescr / sysName，型号和序列号得靠 SSH 或 Telnet 补。
# 所以这两列空着不算故障，只在待补采里提一句。
SNMP_BLIND = {"serial"}   # SNMP 只有序列号真拿不到，品牌型号从 sysDescr 解析，运行时长本来就有


def _fmt_time(raw):
    """快照里的时间戳是 20261022_203616 这种，给人看的要成 2026-10-22 20:36。"""
    raw = str(raw or "").strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$", raw)
    if not m:
        return raw or "未记录"
    y, mo, d, h, mi, se = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{se}"


def _font(run, name=FONT_BODY, size=10.5, bold=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _para(doc, text="", name=FONT_BODY, size=10.5, bold=False, align=None, space_after=6):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        _font(p.add_run(text), name, size, bold)
    return p


def _heading(doc, text, level=1):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    _font(p.add_run(text), FONT_HEAD, 14 if level == 1 else 12, True)
    return p


def _table(doc, headers, rows, font_size=9):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font(p.add_run(h), FONT_HEAD, font_size, True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            _font(cells[i].paragraphs[0].add_run("" if v is None else str(v)), FONT_BODY, font_size)
    return t


def _stats(devices):
    total = len(devices)
    failed = [d for d in devices if d.get("error")]
    ok = [d for d in devices if not d.get("error") and d.get("reachable")]
    methods = {}
    for d in devices:
        m = d.get("method") or "未采集"
        methods[m] = methods.get(m, 0) + 1
    return total, ok, failed, methods


def _blind_fields(devices):
    """SNMP 采集拿不到的字段，按设备记一笔，提示补采。"""
    rows = []
    for d in devices:
        if d.get("error") or d.get("method") != "snmp":
            continue
        missing = [label for key, label in LEDGER if key in SNMP_BLIND and not str(d.get(key, "")).strip()]
        if missing:
            rows.append((d.get("ip", ""), "、".join(missing)))
    return rows


def _verdict(devices, diff_result):
    total, ok, failed, _ = _stats(devices)
    if failed:
        return "需核实", f"{len(failed)} 台设备采集失败，原因见第 4 节。这份报告不能当盘点结论用。"
    if total == 0:
        return "需核实", "快照里没有设备，清单可能是空的。"
    if diff_result and any(diff_result.get("summary", {}).values()):
        s = diff_result["summary"]
        return "有变更需确认", (
            f"与上次相比新增 {s['added']} 台、下线 {s['removed']} 台、配置变更 {s['changed']} 台，见第 5 节。"
        )
    return "可交付", f"本次 {total} 台设备均取到回显，无采集异常。"


def build(snapshot, diff_result=None, meta=None):
    """出一份报告对象。snapshot 是快照 dict，diff_result 是 diff.compare 的结果。"""
    meta = meta or {}
    devices = snapshot.get("devices", [])
    taken_at = snapshot.get("taken_at", "")
    total, ok, failed, methods = _stats(devices)
    verdict, why = _verdict(devices, diff_result)

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.8)
        section.right_margin = Cm(2.6)

    # 一、封面
    _para(doc, "")
    _para(doc, "")
    _para(doc, meta.get("title", "网络设备巡检报告"), FONT_HEAD, 26, True, WD_ALIGN_PARAGRAPH.CENTER, 18)
    _para(doc, meta.get("org", "＿＿＿＿＿＿＿＿"), FONT_BODY, 14, False, WD_ALIGN_PARAGRAPH.CENTER, 40)
    for line in [
        f"报告编号：{meta.get('report_no', PLACEHOLDER)}",
        f"巡检日期：{_fmt_time(taken_at) if taken_at else PLACEHOLDER}",
        f"编制人：{meta.get('inspector', PLACEHOLDER)}",
        f"编制日期：{meta.get('issue_date') or date.today().isoformat()}",
    ]:
        _para(doc, line, FONT_BODY, 12, False, WD_ALIGN_PARAGRAPH.CENTER, 10)
    doc.add_page_break()

    # 二、概述
    _heading(doc, "一、巡检概述")
    _para(doc, f"本次巡检范围由设备清单给定，共 {total} 台。快照时间 {_fmt_time(taken_at)}。")
    if methods:
        desc = "、".join(f"{m} {n} 台" for m, n in sorted(methods.items()))
        _para(doc, f"采集方式：{desc}。")
    _para(doc, "采集过程只下发查询类命令（show、display），不进入配置模式，不对设备做任何写操作。")
    _para(doc, "SNMP 采集能取到的是系统描述与设备名，品牌、型号、序列号要靠 SSH 或 Telnet 补采。")

    # 三、结论
    _heading(doc, "二、巡检结论")
    _table(doc, ["结论", "依据"], [[verdict, why]])
    _para(doc, "")
    _table(
        doc,
        ["设备总数", "采集成功", "采集失败", "待补采"],
        [[total, len(ok), len(failed), len(_blind_fields(devices))]],
    )

    # 四、台账
    _heading(doc, "三、设备台账")
    if devices:
        rows = []
        for d in devices:
            row = []
            for key, _label in LEDGER:
                val = str(d.get(key, "")).strip()
                if key == "version" and len(val) > 60:
                    val = val[:60] + "…"
                row.append(val or "未采集到")
            rows.append(row)
        _table(doc, [label for _key, label in LEDGER], rows, font_size=8)
    else:
        _para(doc, "快照里没有设备。")

    # 五、异常与待核实
    _heading(doc, "四、异常与待核实")
    issues = []
    for d in failed:
        issues.append((d.get("ip", ""), "采集失败", str(d.get("error", ""))[:80]))
    for ip, fields in _blind_fields(devices):
        issues.append((ip, "字段待补采", f"{fields} 未取到，需 SSH 或 Telnet 补采"))
    if issues:
        _table(doc, ["IP 地址", "问题", "说明"], issues)
    else:
        _para(doc, "本次没有采集失败，也没有需要补采的字段。")

    # 六、变更（有对比才出）
    if diff_result:
        _heading(doc, "五、变更清单")
        _para(
            doc,
            f"对比区间：{_fmt_time(diff_result.get('old_at'))} 至 {_fmt_time(diff_result.get('new_at'))}。",
        )
        s = diff_result.get("summary", {})
        _para(doc, f"新增 {s.get('added', 0)} 台，下线 {s.get('removed', 0)} 台，配置变更 {s.get('changed', 0)} 台。")
        if diff_result.get("added"):
            _para(doc, "新出现的设备，需确认是否为私接：", bold=True)
            _para(doc, "、".join(diff_result["added"]))
        if diff_result.get("removed"):
            _para(doc, "本次未扫到的设备，需确认是下线还是故障：", bold=True)
            _para(doc, "、".join(diff_result["removed"]))
        if diff_result.get("changed"):
            _para(doc, "配置或版本发生变化的设备，需有人说明变更时间与操作人：", bold=True)
            for item in diff_result["changed"]:
                fields = "、".join(c[0] for c in item.get("changes", []))
                _para(doc, f"{item.get('ip', '')}　变更项：{fields}")
                if item.get("config_diff_note"):
                    _para(doc, f"　　{item['config_diff_note']}")
                for line in item.get("config_diff") or []:
                    _para(doc, f"　　{line}")
                extra = (item.get("config_diff_total") or 0) - len(item.get("config_diff") or [])
                if extra > 0:
                    _para(doc, f"　　另有 {extra} 行差异，完整内容见快照文件。")
        if not any(s.values()):
            _para(doc, "两次快照之间没有变化。")

    # 七、只读声明
    _heading(doc, "六、只读声明")
    _para(
        doc,
        "本工具在设计上只做查询。所有准备下发的命令先过只读守卫，不属于 show、display 白名单的直接拒绝，"
        "不会静默放过。依据是 GB/T 22239-2019《信息安全技术 网络安全等级保护基本要求》中对变更管理的要求，"
        "写操作应在具备审计能力的一层执行。",
    )
    _para(doc, "因此本报告可作为资产盘点与配置基线的记录，不能作为配置变更的依据。")

    # 八、签字
    _heading(doc, "七、确认")
    t = doc.add_table(rows=2, cols=4)
    t.style = "Table Grid"
    heads = ["巡检人", "审核人", "甲方确认", "日期"]
    for i, h in enumerate(heads):
        cell = t.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font(p.add_run(h), FONT_HEAD, 10, True)
        t.rows[1].cells[i].text = ""
        _font(t.rows[1].cells[i].paragraphs[0].add_run(""), FONT_BODY, 10)
        t.rows[1].cells[i].add_paragraph()
        t.rows[1].cells[i].add_paragraph()

    return doc


def save(snapshot, out_path, diff_result=None, meta=None):
    doc = build(snapshot, diff_result=diff_result, meta=meta)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc.save(out_path)
    return out_path
