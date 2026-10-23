"""探活。

三种办法，按侵入性从低到高排。
一是 ping，最轻，但防火墙常把 ICMP 关了。
二是 TCP 连端口，更准，但要知道连哪个口。
三是 ARP，只在本网段有效，而且要 root。

默认走前两种，都不需要 root，也不会在目标设备上留登录痕迹。
"""

import ipaddress
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

# 网络设备上常见的管理端口，按品牌概率排
DEFAULT_PORTS = (22, 23, 443, 80, 161)


def _ping(host, timeout=1):
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
        )
        return r.returncode == 0
    except Exception:
        return False


def _tcp_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def probe_host(host, ports=DEFAULT_PORTS, timeout=1):
    """返回 (是否在线, 开放端口列表)。"""
    if _ping(host, timeout):
        return True, [p for p in ports if _tcp_open(host, p, timeout)]
    open_ports = [p for p in ports if _tcp_open(host, p, timeout)]
    return bool(open_ports), open_ports


def sweep(network, workers=64, ports=DEFAULT_PORTS, timeout=1):
    """扫一个网段，返回 {ip: [开放端口]}。"""
    net = ipaddress.ip_network(network, strict=False)
    hosts = [str(h) for h in net.hosts()]

    found = {}

    def work(h):
        alive, op = probe_host(h, ports, timeout)
        return h, alive, op

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for h, alive, op in ex.map(work, hosts):
            if alive:
                found[h] = op
    return found
