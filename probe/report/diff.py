"""两次快照对比。

出三类变更，这是巡检报告里最值钱的一段。
一是新出现的设备，可能是私接的，安全上要问。
二是消失的设备，可能是下线，也可能是坏了没人报。
三是配置变了的设备，要有人解释是谁在什么时候改的。
"""


def _index(snapshot):
    return {d["ip"]: d for d in snapshot.get("devices", [])}


def compare(old_snap, new_snap):
    old = _index(old_snap)
    new = _index(new_snap)

    old_ips = set(old)
    new_ips = set(new)

    added = sorted(new_ips - old_ips)
    removed = sorted(old_ips - new_ips)

    changed = []
    for ip in sorted(old_ips & new_ips):
        a, b = old[ip], new[ip]
        diffs = []
        if a.get("fingerprint") != b.get("fingerprint"):
            if a.get("version") != b.get("version"):
                diffs.append(("version", a.get("version", ""), b.get("version", "")))
            if a.get("hostname") != b.get("hostname"):
                diffs.append(("hostname", a.get("hostname", ""), b.get("hostname", "")))
            diffs.append(("config", "有变化", "有变化"))
        if diffs:
            changed.append({"ip": ip, "changes": diffs})

    return {
        "old_at": old_snap.get("taken_at", ""),
        "new_at": new_snap.get("taken_at", ""),
        "added": added,
        "removed": removed,
        "changed": changed,
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

    if not any(s.values()):
        out.append("")
        out.append("没有变化")

    return out
