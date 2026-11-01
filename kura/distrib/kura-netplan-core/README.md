# Netplan 核心发行入口

2026-11-01。显式启用的 Ubuntu 24.04+ 原型包，保留原 `kura-core` 入口。
不是完整生产迁移发行；agent 正式包、旧镜像迁移及双系统/双架构矩阵仍待交付。

在核心仓库执行，选择真实目标架构，不使用 clean：

```sh
mvn -B -f kura/distrib/pom.xml -Pnetplan-package,arch-aarch64,!arch-x86_64 \
  -pl kura-netplan-core package -Dmaven.repo.local=/Users/heyoulin/.m2/repository
```

amd64 选择 `-Pnetplan-package,arch-x86_64,!arch-aarch64`。当前实际运行证据仅 Ubuntu 24.04 arm64。
必须选择 `-pl kura-netplan-core`；仅启用 profile 不会从父 reactor 删除旧发行模块。
产物在本模块 `target/kura-core-netplan_*.deb`；不要误装保留的首轮失败版本。
本次最终验证版本为 `6.0.0~netplan20261101-3`，实际 SHA 见 console 的 evidence manifest。

新包继承现有分级 bundle 清单，但只选择程序、framework、日志配置和初始数据模板。
不会打入旧 installer、NetworkManager/ModemManager unit 绑定、polkit、iptables 安装脚本或 Linux clock writer。
相同身份且字节相同的重复 bundle 只保留一份，内容不同则失败。

程序及四个数据链接由 dpkg 管理，root 拥有：`/opt/eclipse/kura`。
快照、keystore、用户数据及 packages 放在 `/var/lib/kura-netplan`，用户 `kura-netplan` 拥有。
初始模板在 `/usr/share/kura-netplan/defaults`，只有首次初始化时复制；升级不复制覆盖已有数据。
`/etc/kura-netplan/runtime.json` 为 conffile。安装时随机生成本机 32 字节 crypto key、keystore 密码和初始 admin 密码；
后者仅存于 root 可读的 `/etc/kura-netplan/bootstrap-admin`。这些凭据只属于本机 Kura，与 agent/console 登记独立。
HTTPS 证书为本机生成的自签测试证书，生产证书配置仍需部署流程完成。
XML 生成固定 `esf` 前缀以兼容当前解析器；中断初始化或保留数据缺失原密钥时拒绝重建。

安装/升级均不自动 start/enable，不停用系统时间服务、不改 Netplan/NM/cloud-init，不授权网络接口。
升级和卸载前停止 `kura-netplan.service`，需要管理员完成独立 agent 身份/UDS 权限配置后显式启动。
配置中的 socket 默认 `/run/kura-management-agent/control.sock`，agent OS 用户默认 root。
当前 agent 原型必须显式配置允许的 Kura UID 和 socket 组；安装本包本身不授予这项权限。
未连接 agent 时，网络操作和涉及确认网络镜像的快照保存按既有契约拒绝，不能认为断连下本地配置持久化已验收。
HTTP/HTTPS/client-auth 初始端口为 8080/8443/8444，JVM 无 capability；后续端口配置不能假设有低端口绑定权限。

普通 remove 保留 `/var/lib/kura-netplan`、`/etc/kura-netplan`、`/var/log/kura-netplan`。
重装必须使用保留的密钥和快照。purge 仅删除以上三处及
`/etc/systemd/system/kura-netplan.service.d`；不删除 agent 身份、系统网络配置、旧发行保留区或用户家目录。
系统账号保留，避免 UID 被其他账号复用。旧安装目录、symlink、旧 unit 或旧 retained-state 存在时拒绝自动迁移。
与旧 `kura-core`、`kura-networking`、`kura-firewall-only` 冲突；版本化 Provides 不是旧 sibling 生命周期兼容验收。

维护脚本由单一 `tools/lifecycle.py` 生成，postrm 自包含，不依赖已移除的包文件。
13 项本地回归覆盖数据保留、密钥缺失、中断、符号链接、purge 范围、重复 bundle 和 XML 前缀。
真实 dpkg 证据、首轮失败与修复、环境限制见 console `docs/phase2-netplan-package-validation-20261101.md`。
