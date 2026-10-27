"""快照层测试。

两个承诺以前没人验：文件名带时间戳「永不覆盖」，以及 list_files 取到的是最新那份。
同一秒跑两次采集很常见（复测、bat 连点两下），覆盖掉一次就等于 diff 拿这一次比这一次。
"""

import json
import os
import shutil
import tempfile
import unittest

from probe.report import snapshot


def dev(ip="192.168.56.10", config="sysname A\n", version="VRP 5.110"):
    return {"ip": ip, "hostname": "SW", "version": version, "raw": {"config": config}, "reachable": True}


class TestSaveNeverOverwrites(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="snap_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_two_saves_in_one_second_keep_both_files(self):
        p1 = snapshot.save([dev()], self.dir)
        p2 = snapshot.save([dev(config="sysname B\n")], self.dir)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(snapshot.list_files(self.dir)), 2)
        self.assertEqual(snapshot.load(p1)["devices"][0]["raw"]["config"], "sysname A\n")
        self.assertEqual(snapshot.load(p2)["devices"][0]["raw"]["config"], "sysname B\n")

    def test_suffixed_file_sorts_last_so_latest_is_right(self):
        """带序号的那份必须排在后面，否则 latest 取到的是旧的那一份。"""
        p1 = snapshot.save([dev()], self.dir)
        p2 = snapshot.save([dev(config="sysname B\n")], self.dir)
        files = snapshot.list_files(self.dir)
        self.assertEqual(os.path.basename(files[-1]), os.path.basename(p2))
        self.assertEqual(os.path.basename(files[-2]), os.path.basename(p1))
        self.assertEqual(snapshot.latest(self.dir), os.path.join(self.dir, files[-1]))


class TestListAndLatest(unittest.TestCase):
    def test_missing_dir_returns_empty(self):
        self.assertEqual(snapshot.list_files("/tmp/绝对不存在的目录_probe_test"), [])

    def test_latest_without_snapshots_is_none(self):
        d = tempfile.mkdtemp(prefix="snap_empty_")
        try:
            self.assertIsNone(snapshot.latest(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_other_files_ignored(self):
        d = tempfile.mkdtemp(prefix="snap_mix_")
        try:
            snapshot.save([dev()], d)
            with open(os.path.join(d, "笔记.json"), "w", encoding="utf-8") as f:
                json.dump({}, f)
            self.assertEqual(len(snapshot.list_files(d)), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestFingerprint(unittest.TestCase):
    def test_same_content_same_fingerprint(self):
        self.assertEqual(snapshot.fingerprint(dev()), snapshot.fingerprint(dev()))

    def test_config_change_moves_fingerprint(self):
        self.assertNotEqual(
            snapshot.fingerprint(dev()), snapshot.fingerprint(dev(config="sysname A\nvlan batch 20\n"))
        )

    def test_touched_at_does_not_move_fingerprint(self):
        """时间戳不算进指纹，否则每采一次都算「有变化」。"""
        a = dev()
        b = dict(dev(), uptime="123")
        self.assertEqual(snapshot.fingerprint(a), snapshot.fingerprint(b))


if __name__ == "__main__":
    unittest.main()
