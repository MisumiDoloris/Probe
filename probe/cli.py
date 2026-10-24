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


def cmd_collect(args):
    devices_cfg = _load_devices(getattr(args, "devices", None))
    commands = _load_yaml("commands.yaml")
    if not devices_cfg:
        print("devices.yaml 里没有设备，先填。参考 devices.yaml.example")
        return 2

    results = []
    for cfg in devices_cfg:
        ip = cfg.get("ip", "").strip()
        if not ip:
            continue
        dev = Device(ip=ip)
        try:
            method = cfg.get("method", "snmp")
            if method == "snmp":
                data = SnmpCollector(cfg.get("community", "public")).collect(ip, cfg)
            else:
                data = CliCollector(commands, transport=method).collect(ip, cfg)
            for k, v in data.items():
                if hasattr(dev, k):
                    setattr(dev, k, v)
            dev.reachable = True
        except Exception as e:
            # 采集层抛的 RuntimeError 里已经写好了人能读的原因，别再套一层类名
            dev.error = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
        results.append(dev.to_dict())
        flag = "ok" if dev.reachable else "失败"
        print(f"  {ip:16s} {flag} {dev.error[:60]}")

    path = snapshot.save(results, note=args.note)
    print(f"快照已存 {path}")

    if not args.no_excel:
        out = inventory.export_excel(results, args.excel)
        print(f"台账已出 {out}")
    return 0


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
    result = diff_mod.compare(snapshot.load(old_path), snapshot.load(new_path))
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

    snap = snapshot.load(snap_path)
    diff_result = None
    if args.diff:
        files = snapshot.list_files(args.dir or snapshot.SNAPSHOT_DIR)
        if len(files) < 2:
            print("只有一份快照，出不了变更清单，报告里这一段会缺")
        else:
            base = args.dir or snapshot.SNAPSHOT_DIR
            diff_result = diff_mod.compare(
                snapshot.load(os.path.join(base, files[-2])),
                snapshot.load(os.path.join(base, files[-1])),
            )

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
    p = argparse.ArgumentParser(prog="probe", description="网络设备巡检（只读）")
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
