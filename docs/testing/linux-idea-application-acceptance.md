# Linux IDEA 完整应用验收（2026-10-10）

在隔离 Ubuntu 24.04 ARM64 VM 中，使用 IDEA 2026.2.3、OpenJDK 21.0.12.1 和
Maven 3.10.0，直接打开宿主仓库的挂载路径。项目、五个 Maven Profiles 和
JUnit 入口的准备见 [IDEA JUnit 验收](idea-junit-acceptance.md)。
本次完整应用 Debug、Stop、Run 重启和再次 Stop 均已完成。

## 实际 GUI 操作及结果

- 共享 `Kura Linux` 配置的启动前任务完成 123 个 reactor 模块的增量安装；
  参数同时包含 `-DskipTests -DskipITs`。应用仍使用原有 2 GB 堆配置。
- Debug 命中 `Emulator.activate(ComponentContext)` 第 47 行，入参来自真实 SCR。
  求值 `componentContext.getBundleContext().getBundle().getSymbolicName()` 返回
  `org.eclipse.kura.emulator`。F8 到第 50 行后，实例字段已经获得该 ComponentContext。
- 移除断点并恢复后，HTTP 返回 200；Gogo `ss -s INSTALLED` 为空。
  `ss` 共 278 行（含 framework）：269 ACTIVE、8 RESOLVED、1 STARTING。
  277 个业务 bundle 中保留正常 fragment 的 RESOLVED 和 event.publisher 的延迟启动状态。
- Gogo 查询确认实际 ConfigurationService 和 WireGraphService 已注册。
  完整启动日志没有 ERROR、ClassNotFoundException、NoClassDefFoundError 或 BundleException。
  默认未连接 MQTT、尚未配置 JWT 密钥和匿名 Web 会话等既有 WARN 仍存在。
- IDEA Stop 使 Debug JVM 退出，8080/8443/8444 全部释放。随后点击 Run 再次完成
  预构建及启动，HTTP 再次返回 200，无 INSTALLED bundle；再次 Stop 后 JVM 和端口均释放。
  两次 Stop 都显示 exit code 130 / SIGINT，这是主动停止结果。
- 重启前后两份 snapshot 和两个 keystore 的 SHA-256 完全一致。使用的是 VM 内
  `~/.kura-dev/linux` 测试数据，没有改写宿主的个人开发数据。

## 发现及修复

Failsafe 3.6 的 integration-test/verify 使用 `skipITs`，不使用 Surefire 的
`skipTests`。当 IDEA Maven 面板选中 `osgi-it` 时，原启动前任务会额外运行集成
测试；本次旧参数触发的 Linux CRL 13 项全部通过，耗时约 420 秒。共享 macOS/Linux
应用启动配置和 CLI 增量构建现已同时传入两个开关，正常 `verify` 和全量测试命令
保持不变。新配置已经经过上述完整 Debug 和 Run 预构建验证。

首次完整应用预构建时，GWT 编译器及其 worker 与 IDEA 同时运行，IDEA 在 VM
临时 6 GB cgroup 限额下被 OOM kill；该次不计为 GUI 通过。成功的两次应用验收
临时使用 8 GB VM 限额和 1 GB IDEA 堆，未降低应用堆、GWT worker 数或测试时限。
OOM kill 累计数在成功验收前后均为 2（含此前 JUnit 首次失败）。退出 Linux IDEA
后已恢复原 4 GB VM 限额，只恢复共享 `.idea` 中两个平台相关的 Maven 路径，
保留五个 Profiles，并使用宿主 Maven 重新组装 macOS runtime。

## 证据与范围

原始截图、完整运行日志、Gogo 服务状态、runtime inventory、数据校验和及失败
证据归档在本地 `migration-baseline/linux-idea-gui-20261010`。精确路径和文件
SHA-256 见 [机器可读验收记录](linux-idea-application-acceptance.json)。
本次 GUI 执行不重复加入全工作区 Maven 的 5280 次测试调用统计。

Linux GUI 的完整应用及 JUnit 入口现已验收。真实硬件/系统 D-Bus、尚待补齐的
云服务与 Wires 集成场景，以及 P7 模板、CI 和旧配置清理仍需分别完成。
