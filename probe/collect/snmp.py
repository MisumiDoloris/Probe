"""SNMP 采集。只做 GET，不做 SET。

注意 pysnmp 版本差异。这套代码按 pysnmp 7.x 的 asyncio 接口写的，
网上大量教程写的是 4.x 的 hlapi，在 7.x 上 from pysnmp.hlapi import SnmpEngine 会直接 ImportError。

端口可配，默认 161。测试时用 snmpsim 起假 agent 在 1161 之类的端口上。
"""

import asyncio

try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
        get_cmd,
    )
    PYSNMP_OK = True
except Exception:  # pragma: no cover
    PYSNMP_OK = False

# 标准 MIB-II，所有开了 SNMP 的设备都有
OIDS = {
    "descr": "1.3.6.1.2.1.1.1.0",
    "uptime": "1.3.6.1.2.1.1.3.0",
    "name": "1.3.6.1.2.1.1.5.0",
}


async def _get_one(engine, community, ip, oid, timeout=2, retries=1, port=161):
    target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    err_ind, err_stat, err_idx, binds = await get_cmd(
        engine,
        CommunityData(community, mpModel=1),
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if err_ind:
        raise RuntimeError(str(err_ind))
    if err_stat:
        raise RuntimeError(f"{err_stat.prettyPrint()} at {err_idx}")
    for _oid, val in binds:
        return str(val)
    return ""


def get_mib2(ip, community="public", timeout=2, retries=1, port=161):
    """取 sysDescr、sysUpTime、sysName。失败抛异常，由上层记进 error 字段。"""
    if not PYSNMP_OK:
        raise RuntimeError("pysnmp 不可用，检查是不是 4.x 写法装在 7.x 上")

    async def run():
        engine = SnmpEngine()
        out = {}
        for key, oid in OIDS.items():
            out[key] = await _get_one(engine, community, ip, oid, timeout, retries, port)
        return out

    return asyncio.run(run())


class SnmpCollector:
    name = "snmp"

    def __init__(self, community="public", port=161):
        self.community = community
        self.port = port

    def collect(self, ip, device_cfg=None):
        cfg = device_cfg or {}
        community = cfg.get("community", self.community)
        port = int(cfg.get("port", self.port))
        try:
            data = get_mib2(ip, community, port=port)
        except Exception as e:
            raise RuntimeError(f"SNMP 失败 {type(e).__name__} {e}")

        # sysDescr 一般是 "Huawei Versatile Routing Platform Software ... VRP (R) software, Version 8.180 ..."
        descr = data.get("descr", "")
        return {
            "method": "snmp",
            "hostname": data.get("name", ""),
            "version": descr[:200],
            "uptime": data.get("uptime", ""),
            "raw": {"sysDescr": descr, "sysName": data.get("name", "")},
        }
