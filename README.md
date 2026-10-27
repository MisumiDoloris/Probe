# probe

网络设备巡检工具。只读。

## 这是什么

给一屋子没人搞得清是什么的设备，做一次资产盘点和配置备份，然后出一份能交出去的东西。

参考了六个开源项目的不同部分，骨架来自 network-inventory-scanner 的分层，功能清单来自华巡，命令配置走 Excel 或者 YAML 表驱动，备份保留策略来自 switchbackup，品牌命令适配来自 switch-backups。

## 能干什么，不能干什么

能干的。给一份设备清单，做一次只读盘点：探活、SNMP 取系统信息、留快照、两次快照对比、出 Excel 台账、出 Word 巡检报告（封面、结论、台账、异常、变更、只读声明、签字栏）。

不能干的，写在前面省得误会。
- 不改配置。一个写命令都不下发，只读守卫拦所有非查询命令。
- 不做实时监控，也不做性能采集。CPU、流量、接口错误包这些还没写。
- SSH 与 Telnet 采集**没有在真实设备上验证过**。SNMP 那条是拿 snmpsim 假设备实测的，判据和输出都验过；SSH / Telnet 只写好了代码，要 eNSP 或真设备才算验过。
- 报告只出 .docx。转 PDF 要另装 LibreOffice，这台机器上没装。

## 示例数据（不用连任何设备）

```bash
python -m probe.cli report --dir demo/snapshots --diff --out /tmp/巡检报告.docx
```

`demo/snapshots/` 是两份合成快照（第一份两台设备，第二份四台，其中一台 SSH 超时、一台版本变了），`demo/巡检报告示例.docx` 是跑出来的样子。合成数据，不是任何真实设备。

## 三条设计约束

一，只读。所有准备下发到设备的命令先过 `ro_guard`，不是查询类命令直接拒，绝不静默放过。依据是等保 2.0 对变更管理的要求，写操作必须在有审计能力的那一层执行，也就是人在堡垒机里做。

二，采集和报告分开。以后换采集方式，报告层一行不用动。

三，命令和代码分开。命令写在 `config/commands.yaml`，加型号加命令改这张表，不用改代码。

## 怎么跑

Windows 上最省事是双击 `00_巡检菜单.bat`，七项菜单对应下面这些命令，不用记参数。

依赖装好了在 `/home/doloris/netops/venv`。

    cd /home/doloris/netops/probe
    P=/home/doloris/netops/venv/bin/python

    # 扫网段，看有哪些设备在线
    $P -m probe.cli sweep --network 192.168.1.0/24

    # 按 devices.yaml 逐台采集，存快照，出台账
    $P -m probe.cli collect

    # 再采一次，然后比两次的差别
    $P -m probe.cli collect
    $P -m probe.cli diff

    # 出 Word 巡检报告（给甲方那一层），--diff 带上变更清单
    $P -m probe.cli report --diff --org "某某单位" --report-no "IP-2026-011"

产物在 `snapshots/` 和 `output/`。

## 现在的状态

真机验过的（eNSP 里 S5700 真镜像，VRP 5.110）：

- SSH、Telnet、SNMP 三条采集路径都跑通。型号从 `display version` 解析出 S5700，配置回显 1912 字符 103 行、末尾没有分页符
- **只读硬证据**：连采两次，两份配置回显逐字节相同（sha256 一致、设备指纹一致），diff 报「没有变化」。这条是说「工具只读」唯一算数的证据
- **设备检出**：清单里多一台报「新增 1 台」，少一台报「下线 1 台」，报告第 5 节写「本次未扫到的设备，需确认是下线还是故障」
- **结论跟着数据走**：只有干净数据时写「可交付」，有下线时写「有变更需确认」，而且只读声明那一段会跟着改口，不再出现「结论说不能当盘点结论、声明说可以当资产记录」的自相矛盾
- **采集失败隔离**：清单里混一台连不上的，另一台照采、台账照出，控制台写明几台里采到几台

自测 `python -m unittest discover -s tests`，113 条，不需要任何设备。

没验过的：H3C、锐捷、思科的真机（eNSP 只有华为设备，命令表里那三组 `netmiko_os` 还是抄来的，没在真机上确认过）；三台以上异构拓扑；PDF 出口。

还没写的：PDF 出口。现在只出 .docx，转 PDF 得另装 LibreOffice 或 docx2pdf，这台机上没装。

## 不用 eNSP 也能测 SNMP

snmpsim 是一个纯 Python 的 SNMP 代理模拟器，pip 就能装，能同时模拟几千台设备。拿它验采集逻辑最省事，不用开虚拟机。

    ./venv/bin/pip install snmpsim pysmi
    ./venv/bin/snmpsim-command-responder \
        --data-dir=/home/doloris/netops/snmpsim_data \
        --agent-udpv4-endpoint=127.0.0.1:1161

data 目录里放 `.snmprec` 文件，一行一个 OID，格式是 `OID|类型码|值`。类型码 4 是字符串，2 是整数，67 是 TimeTicks，6 是 OID。

两个坑。snmpsim 依赖 pysmi，不装会报 ModuleNotFoundError。`--logging-level=error` 这个参数不认，带上它直接打 usage 然后退出，别加。

改了 snmprec 要清缓存重起，否则它还读旧数据。缓存在 `$TMPDIR/snmpsim/`。

## eNSP 的角色

eNSP 留着验 SSH 和 Telnet 的交互，那部分是 netmiko 和设备真实握手，模拟器替代不了。搭法见 `/home/doloris/netops/eNSP测试环境搭法.md`。


## 目录

    probe/
      ro_guard.py          只读守卫
      cli.py               命令行入口
      collect/
        base.py            数据结构与后端接口
        discovery.py       探活
        snmp.py            SNMP 采集
        ssh.py             SSH / Telnet 采集
      report/
        doc_report.py      Word 巡检报告（封面/结论/台账/异常/变更/只读声明/签字栏）
        snapshot.py        快照读写
        diff.py            两次对比
        inventory.py       Excel 台账
      config/
        devices.yaml       设备清单
        commands.yaml      命令模板（按品牌）

## 退出码

现场双击 bat 不用管，bat 自己会按退出码给提示。写脚本自动化的时候要认这三个：

- 0 正常。部分设备失败也算 0，失败的那几台在台账的「待核实」那一页
- 1 清单里有设备，但一台都没采到。快照和台账照样会写出来，别拿它去出报告
- 2 跑之前就被拦下了：清单缺字段或格式不对、命令表有错、快照读不了、网段写错、输出路径不对。控制台会写清第几条、哪台、哪个字段

## 已知的坑

**老 VRP5（V200R001 这一代）的 SSH 要在服务侧再声明一次用户，光在 `aaa` 里建用户不够。** 除了 `local-user admin password cipher xxx`、`privilege level 15`、`service-type ssh`，还必须加：

```
ssh user admin authentication-type password
ssh user admin service-type stelnet
```

少了这两条，密码明明是对的也一律 `authenticate fail`，而 `display current-configuration` 里不容易看出来，配置看上去完全正常。诊断靠设备侧的 `display aaa online-fail-record all`。

这也是排查时最容易被带偏的一条：先怀疑密码、怀疑隧道、怀疑 SSP 算法，实际上是被漏掉的两行。另外别连续试密码，华为默认失败几次就锁一段时间，锁上之后对的密码也不认。

**paramiko 装 5.x 连不上老华为设备。** eNSP 1.3 里的 S5700（VRP 5.110）只提供 `diffie-hellman-group1-sha1` / `group-exchange-sha1`、`aes128-cbc` / `3des-cbc`、`hmac-sha1` 这几样老算法，paramiko 5.x 已经把这些类整个删掉，握手直接抛 `IncompatiblePeer: no acceptable kex algorithm`。实测降到 **paramiko 2.12.0** 就通，netmiko 4.8.0 配 2.12 会报依赖冲突但仍能正常工作。真机上的老设备大概率也是这套老算法，所以这条不是模拟器的特殊情况。

pysnmp 7.x 不能沿用 4.x 的写法。`from pysnmp.hlapi import SnmpEngine` 在 7.x 上直接 ImportError，要用 `pysnmp.hlapi.v3arch.asyncio`。网上教程基本都是旧写法。

`telnetlib` 在 Python 3.13 已被移除。本项目走 netmiko 的 `*_telnet` 设备类型，不依赖 telnetlib，所以在 3.13 上也能跑。那是为了避免 SwitchAutoBackup 那个项目的坑。

## 许可

MIT，见 LICENSE。设备清单（`probe/config/devices.yaml`）不进仓库，样例见 `devices.yaml.example`。

仓库里 `probe/config/` 下那几份清单是 eNSP 测试环境用的，口令与团体字一律写的是占位符（`CHANGE_ME_PASSWORD`、`public`）。实测前要改成你自己设备上的值。真实环境别把口令写进清单提交到任何仓库，要么用环境变量注入，要么交给堡垒机那一层管——这个工具的定位就是只读盘点，不该持有长期凭据。
