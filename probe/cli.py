"""命令行入口。

四个子命令。
sweep   扫网段，找出在线设备
collect 按 devices.yaml 逐台采集，存快照，出台账
diff    比两份快照，出变更清单
report  出 Word 巡检报告（给甲方的那一层）

用法示例
    python -m probe.cli sweep --network 192.168.1.0/24
    python -m probe.cli collect
    python -m probe.cli diff
"""

import argparse
import os
import sys
import warnings

import yaml

# paramiko 2.12 会为 TripleDES 打一堆弃用警告，每次跑命令都刷屏，
# 不影响功能，这里按内容过滤掉，其它警告照旧。
warnings.filterwarnings("ignore", message=".*TripleDES.*")

from . import __version__
from .collect.base import Device
from .collect import discovery
from .collect.snmp import SnmpCollector
from .collect.ssh import CliCollector
from .report import snapshot, diff as diff_mod
from .report import inventory, doc_report

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(HERE, "config")


def _load_yaml(name):
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_devices(arg=None):
    """设备清单。默认读 config/devices.yaml，--devices 可以指到别处。

    一个客户一份清单，换现场不用改代码，也不用把清单混在一起。
    """
    path = arg or os.path.join(CONFIG_DIR, "devices.yaml")
    if not os.path.exists(path):
        print(f"找不到设备清单 {path}，参考 config/devices.yaml.example")
        return []
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("devices", [])


def cmd_sweep(args):
    print(f"扫 {args.network}  ...")
    found = discovery.sweep(args.network, workers=args.workers)
    print(f"在线 {len(found)} 台")
    for ip, ports in sorted(found.items()):
        print(f"  {ip:16s} 开放端口 {ports}")
    return 0


# 同一个 IP 写了多条采集方式时，按这个顺序合并，前面的优先。
# SSH 能取到的字段最全，SNMP 只补它独有的（sysDescr / sysName / uptime）。
METHOD_PRIORITY = {"ssh": 0, "telnet": 1, "snmp": 2}
VALID_METHODS = {"snmp", "ssh", "telnet"}


def _validate_devices(devices_cfg, commands):
    """清单先校验，再决定采不采。

    以前缺 ip 的条目会被按 IP 分组那一步静默跳过：客户清单里漏一个字段，
    采集一声不吭，报告台数就少一台，签字时没人知道少了谁。宁可整批不采
    并把问题列出来，也不静默少算。

    method 以前也不校验，写成 sshh 会被当成 SSH 去连。有设备时它照样能采到，
    台账里就写着 sshh；没设备时它报「连接超时」，把排查方向带偏。
    """
    problems = []
    for i, cfg in enumerate(devices_cfg, 1):
        if not isinstance(cfg, dict):
            problems.append(f"第 {i} 条不是一个键值对，检查缩进")
            continue
        name = str(cfg.get("name") or "").strip() or "(没有写 name)"
        if not str(cfg.get("ip", "")).strip():
            problems.append(f"第 {i} 条（{name}）没写 ip")
            continue
        method = str(cfg.get("method", "snmp")).strip()
        if method not in VALID_METHODS:
            problems.append(
                f"第 {i} 条（{name}）method 写成 {method!r}，只能是 ssh / telnet / snmp"
            )
            continue
        if method in ("ssh", "telnet"):
            brand = str(cfg.get("brand", "")).strip()
            if brand not in commands:
                known = "、".join(sorted(commands)) or "(命令表是空的)"
                problems.append(f"第 {i} 条（{name}）品牌 {brand!r} 不在 commands.yaml 里，现有 {known}")
    return problems


def _collect_one(cfg, commands):
    """按一条清单项采一台，返回 dict。失败抛异常。"""
    ip = cfg.get("ip", "").strip()
    method = cfg.get("method", "snmp")
    if method == "snmp":
        data = SnmpCollector(cfg.get("community", "public")).collect(ip, cfg)
    else:
        data = CliCollector(commands, transport=method).collect(ip, cfg)
    data.setdefault("method", method)
    return data


def _merge_into(base, extra):
    """把 extra 里的值补到 base 上，base 已有的不覆盖；raw 按字段逐个补。"""
    for key, val in extra.items():
        if key in ("raw", "error", "method"):
            continue
        if not str(base.get(key, "")).strip() and str(val or "").strip():
            base[key] = val
    raw = dict(base.get("raw") or {})
    for rkey, rval in (extra.get("raw") or {}).items():
        if not str(raw.get(rkey, "")).strip():
            raw[rkey] = rval
    base["raw"] = raw
    return base


def cmd_collect(args):
    devices_cfg = _load_devices(getattr(args, "devices", None))
    commands = _load_yaml("commands.yaml")
    if not devices_cfg:
        print("devices.yaml 里没有设备，先填。参考 devices.yaml.example")
        return 2
    if not isinstance(devices_cfg, list):
        print("设备清单格式不对：devices: 下面应该是一个列表，检查缩进和短横线")
        return 2

    problems = _validate_devices(devices_cfg, commands)
    if problems:
        print(f"设备清单有 {len(problems)} 处问题，这一批不采，改好再来：")
        for p in problems:
            print(f"  · {p}")
        return 2

    # 同一个 IP 可能写了多条采集方式，先按 IP 归组，采完再合并成一行台账。
    grouped = {}
    for cfg in devices_cfg:
        ip = cfg.get("ip", "").strip()
        if ip:
            grouped.setdefault(ip, []).append(cfg)

    results = []
    succeeded = 0
    for ip, cfgs in grouped.items():
        cfgs = sorted(cfgs, key=lambda c: METHOD_PRIORITY.get(c.get("method", "snmp"), 9))
        merged = None
        used, failures = [], []
        for cfg in cfgs:
            method = cfg.get("method", "snmp")
            try:
                data = _collect_one(cfg, commands)
            except Exception as e:
                # 采集层抛的 RuntimeError 里已经写好了人能读的原因，别再套一层类名
                failures.append((method, str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"))
                continue
            used.append(method)
            merged = data if merged is None else _merge_into(merged, data)

        dev = Device(ip=ip)
        if merged is None:
            dev.error = "；".join(f"{m} {msg}" for m, msg in failures) or "没有可用的采集方式"
        else:
            for key, val in merged.items():
                if hasattr(dev, key):
                    setattr(dev, key, val)
            dev.method = "+".join(used)
            dev.reachable = True
            if failures:
                print(f"  {ip:16s} 部分成功，{('、'.join(m for m, _ in failures))} 没采到")

        results.append(dev.to_dict())
        if merged is not None:
            succeeded += 1
            print(f"  {ip:16s} ok  {dev.method}")
        else:
            print(f"  {ip:16s} 失败 {dev.error[:60]}")

    path = snapshot.save(results, note=args.note)
    print(f"快照已存 {path}")

    if not args.no_excel:
        out = inventory.export_excel(results, args.excel)
        print(f"台账已出 {out}")

    if succeeded == 0:
        print(f"全部 {len(results)} 台都没采到。快照和台账还是出了，但这份不能当巡检结果用。")
        return 1
    if succeeded < len(results):
        print(f"{len(results)} 台里采到 {succeeded} 台，剩下 {len(results) - succeeded} 台看第 4 节。")
    return 0


def _check_snapshot_shape(snap, path):
    """快照结构对不对。结构不对就不出报告，免得生成一份看着正常的东西。"""
    if not isinstance(snap, dict):
        return f"快照 {path} 格式不对：顶层应该是一个对象，现在拿到的是 {type(snap).__name__}"
    devices = snap.get("devices")
    if devices is not None and not isinstance(devices, list):
        return f"快照 {path} 里的 devices 应该是一个列表，现在拿到的是 {type(devices).__name__}"
    return ""


def cmd_diff(args):
    base = args.dir or snapshot.SNAPSHOT_DIR
    if not os.path.isdir(base):
        print(f"没有快照目录 {base}")
        return 2
    files = sorted(f for f in os.listdir(base) if f.startswith("snapshot_") and f.endswith(".json"))
    if len(files) < 2:
        print("快照不足两份，跑两次 collect 再来比")
        return 2

    old_path = os.path.join(base, files[-2])
    new_path = os.path.join(base, files[-1])
    try:
        old_snap, new_snap = snapshot.load(old_path), snapshot.load(new_path)
    except RuntimeError as e:
        print(e)
        return 2
    for snap, path in ((old_snap, old_path), (new_snap, new_path)):
        bad = _check_snapshot_shape(snap, path)
        if bad:
            print(bad)
            return 2
    result = diff_mod.compare(old_snap, new_snap)
    for line in diff_mod.to_lines(result):
        print(line)
    return 0


def cmd_report(args):
    if args.snapshot:
        snap_path = args.snapshot
    else:
        files = snapshot.list_files(args.dir or snapshot.SNAPSHOT_DIR)
        if not files:
            print("没有快照，先跑 collect")
            return 2
        snap_path = os.path.join(args.dir or snapshot.SNAPSHOT_DIR, files[-1])

    try:
        snap = snapshot.load(snap_path)
    except RuntimeError as e:
        print(e)
        return 2
    bad = _check_snapshot_shape(snap, snap_path)
    if bad:
        print(bad)
        return 2

    diff_result = None
    if args.diff:
        files = snapshot.list_files(args.dir or snapshot.SNAPSHOT_DIR)
        if len(files) < 2:
            print("只有一份快照，出不了变更清单，报告里这一段会缺")
        else:
            base = args.dir or snapshot.SNAPSHOT_DIR
            try:
                diff_result = diff_mod.compare(
                    snapshot.load(os.path.join(base, files[-2])),
                    snapshot.load(os.path.join(base, files[-1])),
                )
            except RuntimeError as e:
                print(f"对比那两份读不了，这次只出单份报告：{e}")

    meta = {
        "title": args.title,
        "org": args.org,
        "report_no": args.report_no,
        "inspector": args.inspector,
    }
    out = doc_report.save(snap, args.out, diff_result=diff_result, meta=meta)
    print(f"报告已出 {out}（快照 {snap_path}）")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="probe", description=f"网络设备巡检（只读） v{__version__}")
    p.add_argument("--version", action="version", version=f"probe {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sweep", help="扫网段找在线设备")
    s.add_argument("--network", required=True)
    s.add_argument("--workers", type=int, default=64)
    s.set_defaults(func=cmd_sweep)

    c = sub.add_parser("collect", help="按清单采集并存快照")
    c.add_argument("--note", default="")
    c.add_argument("--devices", default=None, help="设备清单 yaml，默认 probe/config/devices.yaml")
    c.add_argument("--excel", default="output/台账.xlsx")
    c.add_argument("--no-excel", action="store_true")
    c.set_defaults(func=cmd_collect)

    d = sub.add_parser("diff", help="对比最近两份快照")
    d.add_argument("--dir", default=None)
    d.set_defaults(func=cmd_diff)

    r = sub.add_parser("report", help="出 Word 巡检报告")
    r.add_argument("--snapshot", default=None, help="快照 json 路径，默认取最新一份")
    r.add_argument("--dir", default=None, help="快照目录")
    r.add_argument("--diff", action="store_true", help="带上与上一份快照的对比")
    r.add_argument("--out", default="output/巡检报告.docx")
    r.add_argument("--title", default="网络设备巡检报告")
    r.add_argument("--org", default="＿＿＿＿＿＿＿＿")
    r.add_argument("--report-no", dest="report_no", default="＿＿＿＿＿＿")
    r.add_argument("--inspector", default="＿＿＿")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
