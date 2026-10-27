"""快照。

每次巡检存一份 JSON，文件名带时间戳，永不覆盖。
diff 就靠两份快照比，所以快照要存全：设备清单、每台的关键字段、原始回显的哈希。
"""

import hashlib
import json
import os
import re
from datetime import datetime

SNAPSHOT_DIR = "snapshots"


def _slug(ts):
    return re.sub(r"[^0-9A-Za-z]", "", ts)


def fingerprint(device: dict) -> str:
    """一台设备的指纹。配置回显变了，指纹就变，这是 diff 的核心判据。"""
    raw = device.get("raw") or {}
    basis = "|".join(
        [
            device.get("ip", ""),
            device.get("hostname", ""),
            device.get("version", ""),
            str(raw.get("config", "")),
            str(raw.get("interfaces", "")),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:16]


def _free_path(base_dir, name):
    """同名文件已存在就加序号，绝不覆盖。

    文件名到秒，同一秒跑两次采集（复测、脚本连跑、bat 连点两次）会撞上。
    撞了就直接覆盖的话，diff 拿到的「上一次」其实是这一次，报告里那段
    「与上次相比」整个失真，而且一声不响。

    后缀用下划线而不是短横线：字典序里 '_' 排在 '.' 之后，
    带序号的排在原文件后面，list_files 取最新才不会取反。
    """
    stem, ext = os.path.splitext(name)
    path = os.path.join(base_dir, name)
    n = 1
    while os.path.exists(path):
        path = os.path.join(base_dir, f"{stem}_{n}{ext}")
        n += 1
    return path


def save(devices, base_dir=SNAPSHOT_DIR, note=""):
    os.makedirs(base_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "taken_at": ts,
        "note": note,
        "count": len(devices),
        "devices": [],
    }
    for d in devices:
        item = dict(d)
        item["fingerprint"] = fingerprint(d)
        payload["devices"].append(item)

    path = _free_path(base_dir, f"snapshot_{_slug(ts)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load(path):
    """读一份快照。

    读不了要说清是哪份、坏在哪，别把异常栈甩给人。交付现场遇到这种情况，
    需要的是一句话，不是一屏栈。快照是文本 json，在 Windows 上用记事本或
    Excel 另存一次就会变成 UTF-16 或 GBK，--snapshot 又是让人直接填路径的参数。
    """
    if os.path.isdir(path):
        raise RuntimeError(f"{path} 是一个目录，不是快照文件。--snapshot 后面要给具体的 json 文件")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"找不到快照文件：{path}")
    except UnicodeDecodeError:
        raise RuntimeError(
            f"快照读不了：{path} 不是 UTF-8 编码。用记事本打开另存成 UTF-8，或者重新采一次"
        )
    except PermissionError:
        raise RuntimeError(f"快照读不了：{path} 没有读取权限，先把它从只读或占用状态里放出来")
    except OSError as e:
        raise RuntimeError(f"快照读不了：{path}，{e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"快照文件读不了：{path}，第 {e.lineno} 行第 {e.colno} 列格式不对。文件可能损坏，或者被手改坏了"
        )


def list_files(base_dir=SNAPSHOT_DIR):
    """快照文件名按时间升序。报告层和 diff 都用它，别各写一份。"""
    if not os.path.isdir(base_dir):
        return []
    return sorted(f for f in os.listdir(base_dir) if f.startswith("snapshot_") and f.endswith(".json"))


def latest(base_dir=SNAPSHOT_DIR, before=None):
    """取最近一份快照路径。before 可以指定某一份，用来跟它比。"""
    if before:
        return before
    files = list_files(base_dir)
    if not files:
        return None
    return os.path.join(base_dir, files[-1])
