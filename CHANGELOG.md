# 版本记录

交付包一律 `probe_v<主>.<次>.zip`，不带日期。日期在包里的 CHANGELOG 和快照时间戳上，文件名只认版本号。

## v0.2  2026-10-24

第一次真机验收的版本，在华为 S5700（VRP 5.110，eNSP 1.3.00.100 + VirtualBox 5.2.44）上跑通三条采集路径。

新增
- 只读守卫单测 13 条，覆盖十五条固定用例、采集层是否真调守卫、diff 的三种情形
- 采集层在连设备之前整表校验命令，命令表里混进写命令也带不到设备上
- `collect --devices`，一个现场一份清单，换客户不改代码
- 台账从 `display version` 解析品牌、型号、运行时长
- diff 输出配置行级证据（例如 `+vlan batch 20`），并区分「采不到回显」与「配置被删」两种情况
- Word 报告的结论按事实三档判定，可交付 / 需核实 / 有变更需确认
- 屏蔽 paramiko 的 TripleDES 弃用警告刷屏
- 命令手册、客户说明、跨机隧道方案、笔记本本地跑法四份文档

修正
- `paramiko` 钉死 2.12.0。老华为设备只提供 `diffie-hellman-group1-sha1`、`aes128-cbc`、`hmac-sha1`，paramiko 3 以后删掉了这些实现，握手直接报 `no acceptable kex algorithm`
- 采集失败的原因改成人话，不再吐 `Pattern not detected: '(?:Chang...'` 这类原文
- 重打包时把 `demo/snapshots` 误排除的问题（示例报告出不来）

实测
- SSH、Telnet、SNMP 三条路径取数成功，配置回显 1549 字符、无分页残留
- 密码写错、团体字写错都能隔离到待核实，不影响同批其它设备
- 连续两次采集 diff 为 0，设备上加 `vlan 20` 后 diff 报变更并给出行级证据

## v0.1  2026-10-22

骨架版。分层（collect / report / config / tests）、只读守卫、探活、SNMP 采集、快照、diff、Excel 台账、Word 报告七段、合成示例数据。
