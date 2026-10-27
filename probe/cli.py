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
import ipaddress
import os
import sys
import warnings

import yaml

# paramiko 2.12 会为 TripleDES 打一堆弃用警告，每次跑命令都刷屏，
# 不影响功能，这里按内容过滤掉，其它警告照旧。
warnings.filterwarnings("ignore", message=".*TripleDES.*")

from . import __version__
from .collect.base import Device, field_value
from .collect import discovery
from .collect.snmp import SnmpCollector
from .collect.ssh import CliCollector
from .report import snapshot, diff as diff_mod
from .report import inventory, doc_report

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(HERE, "config")

DEFAULT_NETWORK = "192.168.1.0/24"
# 一个段最多扫这么多地址。再大就不是这个工具的场合了，IPv6 的 /64 会把
# 2^64 个地址整体物化成列表，程序静默卡死，一个字都不输出。
MAX_SWEEP_ADDRESSES = 65536


def _yaml_hint(e):
    """把 yaml 的报错翻成一句能照着改的话。"""
    mark = getattr(e, "problem_mark", None)
    line = getattr(mark, "line", None)
    problem = getattr(e, "problem", None) or str(e)
    where = f"第 {line + 1} 行" if isinstance(line, int) else ""
    return f"{where} {problem}".strip()


def _load_yaml(name):
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except UnicodeDecodeError:
        raise RuntimeError(f"{name} 读不了：不是 UTF-8 编码，用记事本另存成 UTF-8 再来")
    except yaml.YAMLError as e:
        raise RuntimeError(f"{name} 格式不对：{_yaml_hint(e)}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} 顶层应该是「品牌: 设置」这样的键值对，现在读到的是 {type(data).__name__}")
    return data


def _load_devices(arg=None):
    """设备清单。默认读 config/devices.yaml，--devices 可以指到别处。

    一个客户一份清单，换现场不用改代码，也不用把清单混在一起。

    读不进来是最常见的现场故障（Excel 转出来带 Tab 缩进、记事本另存成 GBK、
    直接把一行一台贴进文件没有 devices:），这里一律翻成人话，不甩栈。
    """
    path = arg or os.path.join(CONFIG_DIR, "devices.yaml")
    if not os.path.exists(path):
        raise RuntimeError(
            f"找不到设备清单：{path}\n"
            "改 --devices 指到你自己的清单，或者照 config/devices.yaml.example 抄一份"
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except UnicodeDecodeError:
        raise RuntimeError(f"清单读不了：{path} 不是 UTF-8 编码。Windows 记事本另存时选 UTF-8")
    except yaml.YAMLError as e:
        raise RuntimeError(
            f"清单的 YAML 格式不对：{path}\n"
            f"{_yaml_hint(e)}\n"
            "常见三种：缩进用了 Tab（只能用空格）、冒号后面没跟空格、顶层少了 devices:"
        )
    if isinstance(data, list):
        raise RuntimeError(
            f"清单格式不对：{path} 顶层是一个列表。要写成 devices: 换行再缩进列设备，"
            "参考 config/devices.yaml.example"
        )
    if not isinstance(data, dict):
        raise RuntimeError(f"清单格式不对：{path} 读出来不是键值对（可能是空的或者只有注释）")
    return data.get("devices") or []


def _validate_network(text):
    """扫之前先看网段写得对不对。

    ipaddress 对写错的网段直接抛 ValueError，现场看到的是栈；IPv6 的 /64
    会把 2^64 个地址整体物化成列表，程序静默卡死，一个字都不输出。
    """
    raw = str(text or "").strip()
    if not raw:
        return f"没写网段。形如 {DEFAULT_NETWORK}，只扫一台就写 192.168.1.1/32"
    try:
        net = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        return f"{raw!r} 不是合法的网段。形如 {DEFAULT_NETWORK}，单个地址要写成 192.168.1.1/32"
    total = net.num_addresses
    if total > MAX_SWEEP_ADDRESSES:
        return (
            f"{raw} 里有 {total} 个地址，太多，这个工具是给单段办公楼用的。"
            f"缩到 /16 之内（{MAX_SWEEP_ADDRESSES} 个地址）再来"
        )
    return ""


def _check_out_path(path, what, must_ext):
    """输出路径的检查。

    采完几十台、跑到最后一刻才发现路径是个目录，代价最大；不带扩展名
    静默成功更糟，Windows 上双击打不开，现场结论是「没出表」。
    """
    p = str(path or "").strip()
    if not p:
        return f"{what}的路径是空的"
    if os.path.isdir(p):
        return f"{what}指向的是一个目录：{p}。要给完整文件名，比如 {os.path.join(p, what + must_ext)}"
    if not os.path.splitext(p)[1]:
        return f"{what}没写扩展名：{p}。补上 {must_ext}，不然 Windows 上双击打不开"
    return ""


def cmd_sweep(args):
    bad = _validate_network(args.network)
    if bad:
        print(bad)
        return 2
    if not (1 <= int(args.workers) <= 256):
        print("并发数要在 1 到 256 之间，默认 64")
        return 2

    print(f"扫 {args.network}  ...")
    found = discovery.sweep(args.network, workers=args.workers)
    print(f"在线 {len(found)} 台")
    for ip, ports in sorted(found.items()):
        print(f"  {ip:16s} 开放端口 {ports}")
    if not found:
        print("这一段一个都没探到。先确认网段写对了、本机跟设备在同一层，再怀疑设备没开")
    return 0


# 同一个 IP 写了多条采集方式时，按这个顺序合并，前面的优先。
# SSH 能取到的字段最全，SNMP 只补它独有的（sysDescr / sysName / uptime）。
METHOD_PRIORITY = {"ssh": 0, "telnet": 1, "snmp": 2}
VALID_METHODS = {"snmp", "ssh", "telnet"}


def _validate_commands(commands):
    """命令表本身的校验。

    最阴的一种错是键名拼错：既不进只读守卫、也不会被下发，采集算成功、
    字段全空，报告上一片「未采集到」，查半天才想到是表里把 version 写成
    verison。这里把不认识的键直接点出来。
    """
    from .collect.ssh import COLLECT_KEYS

    allowed = set(COLLECT_KEYS) | {"label", "netmiko_os"}
    problems = []
    for brand, table in commands.items():
        if not isinstance(table, dict):
            problems.append(
                f"commands.yaml 里 {brand} 那一组不是键值对（缩进错一格就会这样），现在是 {type(table).__name__}"
            )
            continue
        unknown = sorted(k for k in table if k not in allowed)
        if unknown:
            problems.append(
                f"commands.yaml 里 {brand} 下有不认识的键 {unknown}，"
                f"能用的只有 {sorted(allowed)}；写错的键既不报错也不会去采"
            )
    return problems


def _validate_devices(devices_cfg, commands):
    """清单先校验，再决定采不采。校验通过时顺手把值规范化并写回。

    两个坑都踩过：
    一是以前缺 ip 的条目会被按 IP 分组那一步静默跳过，客户清单漏一个字段，
    采集一声不吭，报告台数就少一台。现在宁可整批不采并指名到第几条。
    二是判断「有没有值」不能先 str() 再判：YAML 里写 `ip:` 留空，值是 None，
    str(None) 得到字符串 "None"，非空就放行了，然后下游 .strip() 当场崩。
    这类空值恰恰是 Excel 导出来最常见的样子。

    method / brand 在这里小写归一后写回 cfg，采集层拿到的就是规范值。
    只拦不归一会更糟：method 写成 Telnet 时，采集层是拿它跟 "telnet" 比的，
    对不上就走 SSH 连 22 端口，拿 SSH 去连一台只会 Telnet 的老设备。
    """
    problems = []
    for i, cfg in enumerate(devices_cfg, 1):
        if not isinstance(cfg, dict):
            problems.append(f"第 {i} 条不是一个键值对，检查缩进")
            continue
        name = str(cfg.get("name") or "").strip() or "(没有写 name)"

        raw_ip = cfg.get("ip")
        if raw_ip is None or isinstance(raw_ip, (dict, list)):
            problems.append(f"第 {i} 条（{name}）没写 ip")
            continue
        ip = str(raw_ip).strip()
        if not ip:
            problems.append(f"第 {i} 条（{name}）没写 ip")
            continue
        cfg["ip"] = ip

        method = str(cfg.get("method") or "").strip().lower()
        if not method:
            problems.append(
                f"第 {i} 条（{name}）没写 method，得写 ssh / telnet / snmp。"
                "不写会被当成 snmp 去问，设备只开了 Telnet 时回来的错是超时，方向就带偏了"
            )
            continue
        if method not in VALID_METHODS:
            problems.append(
                f"第 {i} 条（{name}）method 写成 {cfg.get('method')!r}，只能是 ssh / telnet / snmp"
            )
            continue
        cfg["method"] = method

        for key in ("username", "password", "community"):
            env_key = cfg.get(f"{key}_env")
            if env_key and not str(os.environ.get(str(env_key), "")).strip():
                problems.append(
                    f"第 {i} 条（{name}）写的是 {key}_env: {env_key}，但这个环境变量是空的。"
                    "用 08_现场录入.bat 跑，或者先设好环境变量再来"
                )

        if method in ("ssh", "telnet"):
            brand = str(cfg.get("brand") or "").strip().lower()
            if not brand:
                problems.append(
                    f"第 {i} 条（{name}）用 {method} 采就必须写 brand，它决定读命令表里的哪一组"
                )
                continue
            if brand not in commands:
                known = "、".join(sorted(commands)) or "(命令表是空的)"
                hint = ""
                if brand in {k.lower() for k in commands}:
                    hint = "；大小写不用管，已经自动归一了，检查有没有多余的字符"
                problems.append(
                    f"第 {i} 条（{name}）品牌 {cfg.get('brand')!r} 不在 commands.yaml 里，现有 {known}"
                    f"。命令表里没有的品牌，把这条改成 method: snmp 还能采到系统信息和运行时长{hint}"
                )
                continue
            table = commands.get(brand) or {}
            if not str(table.get("netmiko_os") or "").strip():
                problems.append(
                    f"第 {i} 条（{name}）品牌 {brand} 在命令表里没写 netmiko_os，"
                    f"用 {method} 采不了（只会报 device_type 不被支持）"
                )
                continue
            cfg["brand"] = brand
    return problems


def _collect_one(cfg, commands):
    """按一条清单项采一台，返回 dict。失败抛异常。"""
    ip = cfg.get("ip", "").strip()
    method = cfg.get("method", "snmp")
    if method == "snmp":
        data = SnmpCollector(field_value(cfg, "community", "public")).collect(ip, cfg)
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
    try:
        devices_cfg = _load_devices(getattr(args, "devices", None))
        commands = _load_yaml("commands.yaml")
    except RuntimeError as e:
        print(e)
        return 2

    if not devices_cfg:
        print("清单里没有设备，先填。参考 config/devices.yaml.example")
        return 2
    if not isinstance(devices_cfg, list):
        print("清单格式不对：devices: 下面应该是一个列表，检查缩进和短横线")
        return 2

    cmd_problems = _validate_commands(commands)
    problems = _validate_devices(devices_cfg, commands)
    if not args.no_excel:
        bad_out = _check_out_path(args.excel, "台账", ".xlsx")
        if bad_out:
            problems.append(bad_out)
    all_problems = cmd_problems + problems
    if all_problems:
        print(f"跑之前先有 {len(all_problems)} 处要改，这一批一台都没采：")
        for p in all_problems:
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
        missed = len(results) - succeeded
        if args.no_excel:
            print(f"{len(results)} 台里采到 {succeeded} 台，没采到的那 {missed} 台看上面带「失败」的行。")
        else:
            print(f"{len(results)} 台里采到 {succeeded} 台。没采到的那 {missed} 台，原因写在台账的「待核实」那一页。")
    return 0


def _check_snapshot_shape(snap, path):
    """快照结构对不对。结构不对就不出报告，免得生成一份看着正常的东西。"""
    if not isinstance(snap, dict):
        return f"快照 {path} 格式不对：顶层应该是一个对象，现在拿到的是 {type(snap).__name__}"
    devices = snap.get("devices")
    if devices is None:
        return ""
    if not isinstance(devices, list):
        return f"快照 {path} 里的 devices 应该是一个列表，现在拿到的是 {type(devices).__name__}"
    for i, d in enumerate(devices, 1):
        if not isinstance(d, dict):
            return f"快照 {path} 里第 {i} 台设备不是键值对，文件可能被手改坏了"
        if not str(d.get("ip") or "").strip():
            return f"快照 {path} 里第 {i} 台设备没有 ip，diff 靠 IP 配对，先把这个字段补上"
    return ""


def _safe_compare(old_path, new_path):
    """比两份快照。读不了或结构不对就说一句，不出半份变更清单。"""
    try:
        old_snap, new_snap = snapshot.load(old_path), snapshot.load(new_path)
    except RuntimeError as e:
        print(f"变更清单出不了：{e}")
        return None
    for snap, path in ((old_snap, old_path), (new_snap, new_path)):
        bad = _check_snapshot_shape(snap, path)
        if bad:
            print(f"变更清单出不了：{bad}")
            return None
    return diff_mod.compare(old_snap, new_snap)


def cmd_diff(args):
    base = args.dir or snapshot.SNAPSHOT_DIR
    if not os.path.isdir(base):
        print(f"没有快照目录 {base}")
        return 2
    files = sorted(f for f in os.listdir(base) if f.startswith("snapshot_") and f.endswith(".json"))
    if len(files) < 2:
        print("快照不足两份，跑两次 collect 再来比")
        return 2

    result = _safe_compare(os.path.join(base, files[-2]), os.path.join(base, files[-1]))
    if result is None:
        return 2
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

    bad_out = _check_out_path(args.out, "报告", ".docx")
    if bad_out:
        print(bad_out)
        return 2

    diff_result = None
    if args.diff:
        # 给了 --snapshot 就跟它自己前面那一份比。
        # 以前固定拿目录里最新两份，于是正文讲这一批、第 5 节讲另一批，
        # 报告自相矛盾还照样出得来，退出码 0。
        if args.snapshot:
            base = os.path.dirname(snap_path) or snapshot.SNAPSHOT_DIR
            files = snapshot.list_files(base)
            cur = os.path.basename(snap_path)
            if cur not in files:
                print("--snapshot 指的那份不在它所在目录的快照序列里，出不了变更清单，这次只出单份报告")
            elif files.index(cur) == 0:
                print("这份快照前面没有更早的一份，出不了变更清单，这次只出单份报告")
            else:
                idx = files.index(cur)
                diff_result = _safe_compare(os.path.join(base, files[idx - 1]), snap_path)
        else:
            base = args.dir or snapshot.SNAPSHOT_DIR
            files = snapshot.list_files(base)
            if len(files) < 2:
                print("只有一份快照，出不了变更清单，报告里这一段会缺")
            else:
                diff_result = _safe_compare(os.path.join(base, files[-2]), os.path.join(base, files[-1]))

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
