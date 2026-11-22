# 同一非 Root 身份的普通命令入口

2026-11-18：为后续 Core capability 收敛补齐普通命令执行前置条件，尚未部署到运行现场。

## 行为

过去普通命令始终经 `/usr/bin/su` 切换到配置的 command user。已经按目标 UID、cap0、`NoNewPrivileges=1` 运行的 JVM 不能依赖 setuid su 再取得身份切换权限。现在仅在下列内核条件全部成立时，复用现有固定 `/usr/bin/env`、超时与命令参数边界直接执行：

- 配置的 command user 与 `ProcessHandle` 返回的 OS 用户名完全相同；不信任可修改的 `user.name`。
- `/proc/self/status` 与 `/proc/thread-self/status` 的身份、组、五类 capability、NNP 全部一致。
- 四种 UID/GID 均为同一个非零有效 ID，附加组不包含 Root 组；不存在保留的 Root UID/GID。
- CapInh、CapPrm、CapEff、CapBnd、CapAmb 全部为零，NoNewPrivs 为 1。缺失、重复、无效字段或读取失败均拒绝进入新路径。

其他情况保留原 su 路径，包含不同 command user、Root、仍持有 capability 的旧 Core，以及非 Linux 开发环境。不会自动修改 command user。目标用户名在一次命令构造开始时固定；请求环境仍只交给目标 payload，不交给 su 或用于选择可信启动程序。显式 shell 模式仍按调用者选择执行 shell；普通 argv 的空字符串、引号、换行、等号和环境变量均保持为数据。

## 当前验证

从 Core Git 基线 `50855bca2fa1ebc7fb74725849fec4a3e8df4605` 加本次明确暂存的差异导出全新源目录，没有复制旧 target。JDK21.0.13/Maven3.10.1 从源码重建 test-support、API、util、Core 并打包；33 项选择 JVM 检查全部通过、无跳过，其中新增 9 项测试方法。Core JAR SHA256 为 `262076b9349aa423a372cc6a5ebd2fb0bf73b41316196856ba990d1c4a236e98`；新增类 major 65。

新建且不挂载任何 Kura 状态的 Linux ARM64/JDK21 容器，8 个条件通过：

- 非 Root 同用户、五 cap0、NNP1；覆盖实际 UID、普通 argv/空参数/环境字面量、工作目录、显式 shell、超时与一次异步完成。
- 同条件伪造 `user.name=root`，仍根据 OS 身份准入。
- Root/cap0/NNP1、Root 伪造用户名、同用户 NNP0、非零 bounding capability、Root 附加组、不同目标用户名，均拒绝新路径。

非零五类 capability 的逐项拒绝在 JVM 合同测试覆盖；真实容器的非零 capability 负例为 CapBnd=0x400，不能外推五类真实 cap 组合全部已验。

第一次 Linux 夹具在复制 payload 时被只读 rootfs 拒绝，JVM 没有启动。失败容器/记录保留；修正夹具先在从未启动的专用容器暂存公共测试文件，封存成本地镜像，再运行网络关闭、只读 rootfs、受限内存/PID 的测试容器。未重用第一次失败结果。测试 base 为本地精确 image ID，运行依赖使用新编译的 Core/API 与声明的 commons-exec1.4.0、commons-io2.21.0、slf4j-api2.0.11。

原始回执位于父工作空间 `.management-close-20261116/source-cohort-20261117/core-unprivileged-executor-20261118/`，包含候选源码树/补丁、构建与 Surefire、新旧夹具及每个真实内核条件。容器只用于此执行器，不代表完整 Core/provider 启动。

## 后续仍需完成

此改动仅消除同 UID 普通命令对 setuid su 的依赖。完整 typed privileged broker、网络/时钟/日志/模块/文件移动/系统更新等 provider 的委派、不同 command user 和 launcher、资源/平台/安装升级移除恢复矩阵仍为内部待办。

`kura.service` 尚未降低权限，原运行中的 Core 仍为 11 ambient/13 bounding caps、NNP0；Root 文件配对、密钥 writer lease、Root 安装检查和所有运行数据均未修改。没有将此候选安装到原三现场或 E，也没有重放密钥/业务/UNKNOWN/900 秒验收。完整 12 父项仍未闭环。
