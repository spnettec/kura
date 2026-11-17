# Java NTP 的独立时钟 actor

2026-11-18，实现基线 `b72fa0de7f02ac36c1832c22ba06a4d37df954d5`，固定安装别名修复 `0f409edde9d33929c4de650765c86f4aab004d0a`，有效 systemd 配对修复 `9066ce7996f14332c34e21649bce235cadd0edba`。Java NTP 的壁钟写入从 JVM 的通用 privileged executor 移到独立 typed actor。RTC 和 Chrony 的完整委派仍待实施，不能据此移除整个 Core 的 CAP_SYS_TIME 或宣称完整最小权限完成。

## 权限与代码配对

- actor 为独立锁定账号 `kura-clock`，不是 Root；五类 capability 仅 CAP_SYS_TIME，NNP1。它不加入 `kura-key-control`，不读取密钥服务或 Core 数据。
- Core 原代码保持 Root 所有及原受限读组。安装器将四个 clock helper、两份 unit 和实际 Clock JAR 配对后复制到 `/usr/libexec/kura-clock-broker/`，Root 所有、clock 组只读。actor 校验封闭文件集合、JDK21 类版本/consumer capability、内容摘要、已安装 unit 文件及 PID1 的实际加载来源，拒绝额外代码、override/drop-in 和不配对文件；完整平台/profile 矩阵继续待验。
- actor 看不到整个 `/opt/eclipse/kura`、`/etc/kura` 及密钥/agent 状态；Core 看不到 clock 私有状态和 actor 专用代码。原密钥服务仍为 cap0，没有扩权。
- systemd 创建 Root 所有的固定 UDS listener。Core helper 核对 PID1/Root listener；actor 核对当前 `kura.service` 的 systemd MainPID、真实 UID、直接子进程及固定 `python3 -I -B` helper 命令。Root 调用者和同 UID 的其他进程也不获得此接口。
- Core 配置的数据目录由 `SystemService.getKuraDataDirectory()` 提供；新 sender 记录在其 `clock-broker/` 子目录，不使用历史 `.data` 脚本。

## 原请求与 UNKNOWN

接口只接受校时偏移，不接受 shell、argv、环境或文件路径。actor 在真正执行时将偏移加到当前 realtime，补偿 prepare/commit RPC 耗时；样本按同一 boot 的 monotonic 时间限定为30秒，过期、跨 boot 或溢出给出确定失败且不写时钟。

Core 先持久保存原 namespace/请求号/偏移/cohort，再发一次 prepare。actor 持久准备但不写时钟；Core 在首次 commit 发送前另存 `issued` 记录，actor 在 syscall 前另存 commit-intent。已有 ID 永远返回原状态，不能重新执行。确定 APPLIED/FAILED 后，Core 先保存完成回执再释放 pending；未确认状态保留原文件。

丢 prepare 回复后仅查询同一 Root 的原 ID；只有已证明未提交、且本地从未发出 commit 的原 PREPARED，才可完成首次 commit。commit 一旦发出，即使查询仍显示 PREPARED 也不重发。UNKNOWN/UNSEEN 不换号、不再 prepare、不绕到其他 Root，也不回落到 `date`。旧样本恢复结果不冒充当前样本已校时。

任何未决记录阻止新写，日志满也关闭新准入，不自动 prune。当前上限4096条；未决核定/取消、容量归档和用户界面仍为内部待办，不能靠删日志恢复准入。RTC 仅在壁钟已确认更新时才继续，避免把旧时间写入硬件。

## 包生命周期

当前源码已加入独立账号原目的/分步记录、Root 所有 code cohort、安装、维护、恢复 socket 和移除保留路径。preinst/prerm 的内嵌 guard 在改代码前仅调用原已配对的 clock setup；未决事务拒绝继续。维护保留原 namespace，停止并检查 actor/socket；remove/purge 保留账号、原日志、维护目的及 Core sender 数据。已有账号缺原管理凭据、未知代码或损坏记录均拒绝认领。

安装器修复 `umask 077` 造成新代码前缀700的问题，新建前缀显式755；既有目录不自动 chmod/chown，链接和非目录拒绝。Root 代码目录与真实运行数据仍分别处理。

正常发行包安装使用固定 `/opt/eclipse/kura -> kura_*_linux` 别名。actor 与内嵌维护 guard 仅接受该路径的 Root 所有单跳链接，目标须是同一 `/opt/eclipse` 下匹配版本名的真实 Root 目录，且 group/other 不可写；绝对目标与单个相对文件名均可。其他父目录、code leaf、串联链接、其他目标和属主继续拒绝。8项独立 Linux 文件系统检查通过，没有创建 clock namespace、请求或执行校时。

完整 Core deb/六组件的实际安装升级移除恢复及所有故障点尚需继续验证；单个组件场景不能替代它们。

## 本轮证据

新 Git 源码导出、JDK21.0.13/Maven3.10.1：57项选择 JVM 检查通过，无跳过（Core33、Clock24）；当前 Python 合同/包装检查38项通过。JVM 验证的生产 Java/manifest/DS 与提交一致；后续 Python/安装器修正另有当前合同与实际 VM 证据。没有覆盖旧 Surefire 或重放闭环密钥/900秒验收。

现有 Ubuntu26.04 ARM64 Parallels VM 的全新组件现场，JDK21.0.12.1：实际生产 `ClockServiceImpl` 从新 Clock JAR 加载，JVM UID993/GID971/五cap0/NNP1；actor UID992/GID970/仅CAP_SYS_TIME/NNP1，均无自动重启。显式一次 guest-only +1ms，ClockEvent1；壁钟跨度1537ms、monotonic跨度1536.314333ms，RPC耗时没有成为校时倒退。宿主及共享 OrbStack 内核没有执行校时。

- namespace：`a23fb4e9-1621-4d82-9d53-7b9a1d94e391`
- 原请求：`c35584c9-c3ba-45b6-8305-673e7b576353`，APPLIED/errno0，prepare、commit、Root回执和Core完成记录一致，pending为空。
- 请求摘要：`d0552dafee426a3e0b60d0f6700b0a8664c396d4ea135d40c2729f1c2f7259cb`
- 实际 cohort：`e2d5a2663d17c617c4c4097cefe536d02565dc7a138d20a34b191a208e46881e`
- 实际 Clock JAR：`b3cba7f6eef762e4f59a21106246bebbb633f64d9f6e95e1a810390274e1b36a`

Root和同UID的非Main进程均得到UNAUTHORIZED；额外代码和unit override均被拒绝为UNPAIRED_CODE，仅移除本次自建且核验原字节的测试文件，原配对恢复。namespace/原事务文件核对一致，事务数保持1。公开 canary 在同UID/同cap/NNP的独立观察进程中，直接路径与Root/cap0进程的 `/proc/PID/root` 路径均EACCES，没有读取任何真实密钥或canary字节。此为 canary 拒绝边界，不外推完整文件系统隔离证明。

组件 JVM、actor、socket 已经正常停机，原数据与维护记录保留；Parallels 按正常 guest poweroff 回到 stopped。原始回执在父工作空间 `.management-close-20261116/source-cohort-20261117/core-clock-broker-20261118/`。

首次空目录预检拒绝、GECOS冒号拒绝、代码父目录不可遍历及观察器错误均留原记录。GECOS修正沿原安装目的/原已创建组继续；在失败时尚无 clock namespace/dispatch。此后的实际 +1ms 只执行了一次。首次canary回执中的事务计数字段是固定值，不能独立作为计数证明；随后 authorization/pair-checks/stopped 原始观察才是实际事务数及原文件不变的依据。

## 当时完整发行包核对（0f409）

从 `0f409edde9` 的新真实 Git 检出，以独立 Maven 缓存重建 build-support、Core/全部工具和 ARM64 distribution，没有复用旧 target，也没有向个人共享 Maven 缓存安装本项目产物。JDK21.0.13/Maven3.10.1。包为 `6.0.0~git202611172245.0f409ed-1`，203543034字节，SHA256 `e88f83022083f033b155a76c8db00d8cc2cfe02e8cfaa0e21ceae6ba99aa6313`。

7个 clock 配对载荷及父目录的 Root uid/gid、不可由 group/other 写入的权限、当前 helper/unit 摘要均通过；preinst/prerm 内嵌 guard 与当前源码完整字节一致，四份维护脚本 shell 解析通过，Main 的 socket 依赖/私有目录遮蔽已包含。包仍使用既有版本目录暂存，再由安装器建立固定 canonical 别名。

- 包内 manifest 文件 SHA256：`7b87879baefa45b68cb50169aaa8787e3699747536eda0e279cecc8728f27b3f`
- 包内 Clock JAR：`a08892896ce8cda65ff77c4a1ba34b82e4d9ce46987735d6f5f299515a35b438`
- 两个生产类 `ClockServiceImpl`、`ClockPrivilegeClient` 与实际 VM 所用 JAR 中的类逐字节相同，major65；JAR/完整 cohort 因构建元数据和别名修复不同，不能称该完整包已实际安装或运行验收。

首次无 `.git` 导出被发行 Git 插件拒绝，首次真实检出因缺本 checkout 的 offline-recovery target 被拒绝；随后完整重建 Core/tools。早期 b72 包未含固定别名修复，仅保留历史。检查器对版本目录、最终换行和 systemd 多个 Requires/After 行的错误假设也保留原失败；按实际拥有方修正检查器后通过，没有改包来迁就检查。

22:45 UTC 原三现场、个人25文件、C9私有及进程/计数、D29私有及原 Main3135只读核对精确；E原配对、身份20/Core6/local7/material5/switch9/transport7和原 native29323/Core29609/key4714/recovery4640/NM4668保持，原ON revision5e6e429f…精确。18仓文档前只有本轮预期 Core 提交及新文档，其他17仓与前检查点一致，冻结完整12父项 SHA 不变。

## 有效 unit 配对与首次实际安装（9066）

此前仅检查少数目录，不能覆盖 systemd 的完整加载来源。[systemd unit 加载规则](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)包括 control/attached/generator、名称前缀与类型级 drop-in；[PID1 接口](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html)提供 FragmentPath、DropInPaths、NeedDaemonReload 等属性。当前实现从 PID1 取得实际 UnitPath，核验已有目录的 Root 所有及不可由 group/other 写入；权限拒绝不会当作不存在。

每个加载位置都拒绝本 unit 的替代 fragment、drop-in、wants/requires/upholds，以及适用的前缀/类型级 drop-in。原固定 `/lib -> /usr/lib` 兼容保留。已加载 unit 必须是原名称、loaded、固定 vendor fragment、无 SourcePath/DropInPaths、非 transient，且无待 daemon-reload 状态；manager 异常、超时、缺失/重复字段均关闭准入。新增运行期检查不修改原密钥服务配对规则。

安装器在账号/状态/代码变更前先检查全部 unit 输入。新 fragment 发布后只执行文件核对；resume 先保留原维护 gate，daemon-reload、核对真实加载配置、启动 socket 并再次核对成功，最后才删除原 gate。失败保持原目的及状态，不用旧加载配置宣布恢复。

49项 Python 合同/包装检查通过，新增11个方法；Java/manifest/DS 未改变，未重跑或累加前轮57项 JVM。测试驱动 `817ff3cfa2` 修正 inactive unit 被 GC 后重新加载的问题：仅使用 UID65534/cap0/NNP1 的 sleep holder 和 After= 引用，验证真实待重载状态，actor/socket 仍不启动。

新空 systemd255.4 Ubuntu24.04 ARM64 容器的60个真实条件通过（37拒绝/23接受或恢复），覆盖12个实际加载目录、真实 set-property --runtime、全局/前缀 drop-in、替代 fragment、依赖目录以及改回原字节但尚未 reload。无 SYS_TIME、网络或宿主运行数据挂载，clock namespace/请求均0，actor/socket 从未启动。该容器已正常停止并保留。

从 Git `9066ce7996` 的新真实检出，以 JDK21/Maven3.10.1 和独立 Maven 缓存重建 support、整个 Core/tools/distribution。新 ARM64 包 `6.0.0~git202611172300.9066ce7-1`，203543854字节，SHA `c6a53072155e9ee89c1fe2ecad85901474962112b0cd92d7eba5422376bb918e`。原7载荷/父目录 Root 权限、摘要、内嵌 guard、维护脚本和 Main 依赖遮蔽核对通过；生产两类与原实际 VM 字节相同。协议中的 actor cohort 是 canonical JSON 不含最后换行的摘要；原包核对回执的 `clockCohortSha256` 字段则是整个 manifest 文件摘要，不能相互替代：

- 当前 actor cohort：`cc0a32d51cf6ce61014da827e4297d8058ddf3c0d3021cb4a34614a6643efaf7`
- 当前 manifest 文件：`57b7f686f16bf5d6f61ecdd4171b6e71f798c277d8bb9b5c1c9cf886f97e442c`
- 当前 Clock JAR：`28ea41f1450847bee71ac1dae667661139386ecef0054db060b5b947bd65b11b`

第二个全新、按真实 Depends/Pre-Depends 准备的 Ubuntu ARM64/JDK21 容器，完整包单次 dpkg 首装 exit0、installed。实际固定版本别名、两套代码/账号/加载配置配对通过，socket listening/NConnections0/NAccepted0；Core Main 与 actor 均 inactive/MainPID0/NRestarts0。专用 clock UID995/GID988、仅自己的组，状态0700、只有原空 admission.lock，没有 namespace/operations。此为完整包实际首装及维护脚本路径，**不是完整 Core/OSGi 或当前 actor 权限运行验收**。

原 clock 维护目的 `5e33127e-7433-4070-8f77-fe60c3f77480`、namespace null，实际 quiesce 后加入本次自建 control override。一次 resume 明确 UNPAIRED_CODE/exit1，原 gate 字节及 dev/inode/uid/gid/mode/nlink/size/mtime/ctime/SHA 精确、socket 保持 inactive。仅撤销核过原字节的自建 override 后，由产品自身 reload/核对/启 socket，沿同一原维护目的恢复成功，没有手动 reload 或新维护目的。Core/密钥/账号23份文件的上述字段精确（自查 NOATIME，未断言 atime），Core/密钥/NM原进程保持；没有发送 clock 或密钥业务请求。完成后只为停放本新夹具禁用 Main，正常停止容器并保留全部数据；默认首次安装原本 enabled，普通 boot 未验。

首次 PID1 exit255、宿主复制501:20和新父目录777被配对拒绝、未建立 stale 条件、安装宿主驱动缺 os 导入均留原失败。前者在载荷前退出，复制修正仅处理核过封闭集合的本次新代码；os 异常发生在实际 dpkg 前，核实安装/状态均不存在后沿原容器/包执行唯一一次 dpkg。没有删数据凑通过或重放已闭环请求。回执在 `.management-close-20261116/source-cohort-20261117/core-clock-effective-units-20261118/`；安装日志和私有指纹仅在该处0700/0600目录，不进Git/知识库。

23:16 UTC 原3/个人25/C9及进程计数/D29原Main3135、E原配对/身份20/Core6/local7/material5/switch9/transport7与原所有进程/ON revision再次只读精确。Parallels仍 stopped，原 +1ms及其 namespace/ID 未再使用。当前包的其他平台、完整 Core/OSGi、升级/移除/恢复及完整六组件/provider/launcher、RTC/Chrony、最小权限与全部12父项继续内部 pending；仅原3 external deferred。

## 后续

继续当前源码发行包核对、完整 Core/OSGi 和安装升级移除恢复、真实 syscall 拒绝与崩溃矩阵、clock UNKNOWN 管理/容量、RTC/Chrony，以及其他网络、日志、模块、文件移动、系统更新等 typed broker/provider/launcher。原三现场和E没有部署本候选；E真实Core仍11 ambient/13 bounding caps、NNP0。完整12父项保持内部 pending，仅原3 external deferred，G034未封存、未正式发布，目标 active。
