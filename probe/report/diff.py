"""两次快照对比。

出三类变更，这是巡检报告里最值钱的一段。
一是新出现的设备，可能是私接的，安全上要问。
二是消失的设备，可能是下线，也可能是坏了没人报。
三是配置变了的设备，要有人解释是谁在什么时候改的。

配置变了还要说清「变了什么」，光写「有变化」甲方没法签。
所以这里对配置回显做一次行级比对，最多列五行证据。
"""

import difflib

MAX_DIFF_LINES = 5


def _index(snapshot):
    """按 IP 建索引。

    容忍脏条目：快照被手改过、或某条缺 ip 时，跳过而不是抛 KeyError。
    这类脏数据 CLI 入口会挡，但 diff 也可能被别处直接调用。
    """
    out = {}
    for d in snapshot.get("devices") or []:
        if not isinstance(d, dict):
            continue
        ip = str(d.get("ip") or "").strip()
        if ip:
            out[ip] = d
    return out


def _config_diff(old_dev, new_dev, limit=MAX_DIFF_LINES):
    """配置回显的行级差异。

    返回 (证据行, 总数, 说明)。三种特殊情况单独说明，不能把「这次没取到回显」
    渲染成满屏的删除行 —— 那会被读成「设备配置被删了」。
    """
    a = str((old_dev.get("raw") or {}).get("config", "")).strip()
    b = str((new_dev.get("raw") or {}).get("config", "")).strip()
    if not a and not b:
        return [], 0, ""
    if a and not b:
        return [], 0, "本次没取到配置回显（多半采集失败），无法比对"
    if b and not a:
        return [], 0, "上次没取到配置回显，这次取到了，本次是第一次可比"
    lines = []
    for line in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++")):
            continue
        if line[:1] in "+-" and line[1:].strip():
            lines.append(line.rstrip())
    return lines[:limit], len(lines), ""


def compare(old_snap, new_snap):
    old = _index(old_snap)
    new = _index(new_snap)

    old_ips = set(old)
    new_ips = set(new)

    added = sorted(new_ips - old_ips)
    removed = sorted(old_ips - new_ips)

    changed = []
    uncomparable = []
    method_changed = []
    for ip in sorted(old_ips & new_ips):
        a, b = old[ip], new[ip]
        # 有一侧没采到就没有可比数据。上一轮口令写错、这一轮采到了，
        # 两台设备在指纹上必然不同，以前会报成「配置和版本都变了」，
        # 让甲方去解释一次根本没发生的变更。这里只记「无法比对」。
        #
        # 判据只认明确的 False：v0.5 以前的快照没有 reachable 这个字段，
        # 缺字段要按老行为照常比，不能因为读不到就当成失败。
        if (
            a.get("reachable") is False
            or b.get("reachable") is False
            or a.get("error")
            or b.get("error")
        ):
            uncomparable.append(ip)
            continue
        # 采集方式变了，字段来源就不一样，也不该拿来比。
        # Telnet 的版本栏是 display version 里的一行，SNMP 的版本栏是 sysDescr 整串，
        # 同一台设备、一个字没改，指纹也会变。2026-10-28 现场就撞上了：
        # 同一台 S5700 先 Telnet 后 SNMP 各采一次，报告写「发生变化 1 台」。
        # 只比两边都有值的情况：早期快照没有 method 这个字段，缺了要按老行为照常比。
        m_a = str(a.get("method") or "").strip()
        m_b = str(b.get("method") or "").strip()
        if m_a and m_b and m_a != m_b:
            method_changed.append(ip)
            continue
        if a.get("fingerprint") == b.get("fingerprint"):
            continue
        diffs = []
        if a.get("version") != b.get("version"):
            diffs.append(("version", a.get("version", ""), b.get("version", "")))
        if a.get("hostname") != b.get("hostname"):
            diffs.append(("hostname", a.get("hostname", ""), b.get("hostname", "")))
        lines, total, note = _config_diff(a, b)
        if lines or total or note:
            # 只有配置回显真的不同（或这次没取到回显）才算配置变化。
            # 以前是只要指纹变就无条件加一条「配置有变化」，于是一次版本升级
            # 报告就写「配置被改过」却列不出一行证据，甲方没法签这个字。
            diffs.append(("config", "有变化", "有变化"))
        elif str((a.get("raw") or {}).get("interfaces", "")) != str((b.get("raw") or {}).get("interfaces", "")):
            diffs.append(("interfaces", "有变化", "有变化"))
        if not diffs:
            # 指纹变了却对不上任何一项，宁可报出来让人看一眼，也不静默放过。
            diffs.append(("指纹", "有变化", "有变化"))
        changed.append({"ip": ip, "changes": diffs,
                        "config_diff": lines, "config_diff_total": total,
                        "config_diff_note": note})

    return {
        "old_at": old_snap.get("taken_at", ""),
        "new_at": new_snap.get("taken_at", ""),
        "added": added,
        "removed": removed,
        "changed": changed,
        "uncomparable": uncomparable,
        "method_changed": method_changed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def to_lines(result):
    """把对比结果转成人话，终端和报告都用它。"""
    out = []
    s = result["summary"]
    out.append(f"对比 {result['old_at']} 与 {result['new_at']}")
    out.append(f"新增 {s['added']} 台，下线 {s['removed']} 台，配置变更 {s['changed']} 台")

    if result["added"]:
        out.append("")
        out.append("新出现的设备，要确认是不是私接")
        for ip in result["added"]:
            out.append(f"  {ip}")

    if result["removed"]:
        out.append("")
        out.append("这次没扫到的设备，要确认是下线还是故障")
        for ip in result["removed"]:
            out.append(f"  {ip}")

    if result["changed"]:
        out.append("")
        out.append("配置或版本变了的设备，要有人解释")
        for item in result["changed"]:
            fields = "、".join(c[0] for c in item["changes"])
            out.append(f"  {item['ip']}  变了 {fields}")
            if item.get("config_diff_note"):
                out.append(f"      {item['config_diff_note']}")
            for line in item.get("config_diff") or []:
                out.append(f"      {line}")
            extra = (item.get("config_diff_total") or 0) - len(item.get("config_diff") or [])
            if extra > 0:
                out.append(f"      …另有 {extra} 行差异，详见快照")

    if result.get("uncomparable"):
        out.append("")
        out.append("上一轮或这一轮没采到，没有可比数据（不算变更，先把它补采一次）：")
        for ip in result["uncomparable"]:
            out.append(f"  {ip}")

    if result.get("method_changed"):
        out.append("")
        out.append("采集方式和上次不一样，字段来源不同，这次不参与比较（不算变更）：")
        for ip in result["method_changed"]:
            out.append(f"  {ip}")

    if not any(s.values()):
        out.append("")
        if result.get("uncomparable") or result.get("method_changed"):
            out.append("没有任何比对出来的变化。上面那几台要么补采一次、要么换回同一种采集方式才能比。")
        else:
            out.append("没有变化")

    return out
