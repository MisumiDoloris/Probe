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

    path = os.path.join(base_dir, f"snapshot_{_slug(ts)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
