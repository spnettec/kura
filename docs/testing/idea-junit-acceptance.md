# IDEA JUnit 验收（2026-10-10）

在 macOS 的 IntelliJ IDEA 2026.2.3 中，使用项目 Temurin JDK 21 和 JUnit 5.14.4，
由 IDEA JUnitStarter 直接执行以下测试，均正常退出（exit code 0）：

| 入口 | 测试数 | 结果 |
| --- | ---: | --- |
| `Kura plain JUnit` → `KuraExceptionMessageTest` | 7 | Run 通过 |
| `BundleRuntimeIT` | 6 | Run 通过 |
| `Kura Equinox JUnit` → `LegacyCoreRuntimeIT` | 8 | Run 和 Debug 均通过 |
| `Kura Configuration JUnit` → `ConfigurationServiceRuntimeIT` | 47 | Run 通过，exit code 0（2026-10-10 续接） |

根 `.run/` 中提交了四个共享 JUnit 配置。它们使用项目 JDK 和相对工作目录，不写入
本机 JDK 路径、个人配置或调试器断点。普通 JUnit 的 classpath 来自 core 模块；
Equinox 测试控制端来自 kura-osgi-tests 模块，业务代码仍通过真实 bundle 加载。

## 准备与运行

使用 Maven 3.10 / JDK 21 从根 POM 导入项目，并启用 `osgi-it` profile。首次运行、
修改 bundle 源码或执行 clean 后，先准备实际 bundle JAR：

```sh
mvn -Posgi-it -pl :kura-osgi-tests -am verify
```

使用独立 Maven 缓存时在命令中指定同一 `-Dmaven.repo.local=/absolute/cache`。
随后在 IDEA 选择共享配置并 Run 或 Debug。配置中的 Make 任务只编译 IDEA 模块；
被 Equinox 安装的 JAR 位于 `kura-osgi-tests/target/*-it-bundles` 和 `target/it-bundles`，
修改业务或夹具代码后必须重新执行 Maven 准备命令，避免调试旧 JAR。

## 实际调试检查

- 在 `LegacyConfigurationComponent.updated(Map)` 第 16 行设置断点，启动
  `Kura Equinox JUnit` Debug，命中真实 SCR 激活回调。
- 入参是 SCR 的 `ReadOnlyDictionary`，包含 23 项；赋值前组件属性为空。
- 求值 `FrameworkUtil.getBundle(this.getClass()).getSymbolicName()` 返回
  `org.eclipse.kura.testing.configuration.fixtures`。
- F8 单步到第 17 行，`this.properties` 变为包含 23 项的不可变 Map。
- 移除本次断点后重新 Debug，8 项全部通过，进程退出；没有遗留暂停的测试 JVM。

首次断点演示暂停数分钟，触发了夹具自身的有界 SCR 激活等待，结果为 1 失败、7 通过。
这是一次真实记录的调试失败，不计作通过。共享配置仅通过
`junit.jupiter.execution.timeout.mode=disabled_on_debug` 关闭调试时的 JUnit 超时；
服务等待、轮询和其他显式时限仍然有效。长时间暂停后可以重跑，测试时限没有为演示放宽。

本记录只覆盖表中的实际 GUI 入口。配置服务 47 项通过真实 Equinox/SCR/ConfigAdmin
夹具运行，使用 `kura-osgi-tests/target/config-it-bundles`；IDEA 汇总为 47/47 通过，
耗时 47.965 秒，进程退出码 0。它未验证完整部署装配或宿主 SystemService。
Linux GUI 结果见下节；全工作区回归见
[独立记录](full-workspace-validation-20261010.md)。其余通信场景、HTTP/MQTT
端点和 P7 仍按各自清单验收；Maven 通过不能作为所有测试已经在 IDEA GUI 运行的证明。

续接时还从导入的 `kura-endpoint-tests` 模块，在 Mac IDEA 中直接运行
`ConfigurationEndpointsIT`：HTTP/MQTT 参数化用例 **204/204 通过**，耗时
14 分 16 秒，测试进程已退出。新增共享配置
`Kura configuration endpoints JUnit`，供重复执行。此次启动用的是编辑器类级
Run，新增的共享配置未单独重跑；详见
`mac-idea-configuration-endpoints-validation-20261010.json`。该类使用受控的
ConfigurationService 等依赖，真实持久化配置服务与端点装配的组合验收仍待完成。

同一 Mac IDEA 导入工程又通过九个共享类级 JUnit 配置直接运行端点场景：

| 类 | IDEA 结果 |
| --- | ---: |
| `IdentityV1EndpointsIT` | 18/18 |
| `IdentityV2EndpointsIT` | 32/32 |
| `KeystoreEndpointsV2IT` | 16/16 |
| `ServiceListingEndpointsIT` | 55/55 |
| `SecurityEndpointsV1IT` | 16/16 |
| `SecurityEndpointsV2IT` | 14/14 |
| `SystemEndpointsIT` | 24/24 |
| `TamperDetectionEndpointsIT` | 18/18 |
| `WireGraphEndpointsIT` | 98/98 |

合计 **291/291**，九个类均被 IDEA 标为 Passed；没有失败或跳过。运行配置在
`.run/Kura * endpoints JUnit.run.xml`，均指向导入的 `kura-endpoint-tests` 模块、
JDK 21 和类级 Run。逐类结果及源码/配置哈希见
`mac-idea-rest-endpoints-validation-20261010.json`。另有隔离 Mac Equinox 运行集
通过证书校验的 HTTPS 与 Basic 认证实际读取 identity、system、serviceListing、
tamper、keystores 接口；见 `mac-rest-scr-endpoint-validation-20261010.json`。
IDEA 测试中的受控服务绑定与运行集只读请求是两组独立证据，仍需保留清单中对
真实 SCR 写入流程、已安装 Debian 装配和物理设备的相应边界。

## Linux IDEA JUnit 验收（2026-10-10）

在隔离 Ubuntu 24.04 ARM64 VM 的 IDEA 2026.2.3 中，直接打开宿主仓库的挂载路径：
`/home/heyoulin/kura-gui-acceptance/host-git/kura`。该路径解析到
`/mnt/mac/Users/heyoulin/iot-kura-develop/git/kura`，并非先前复制到 VM 的源码。
项目 SDK 为 Ubuntu OpenJDK 21.0.12.1，Maven home 为独立的 Maven 3.10.0，
本地缓存为 VM 内的 `kura-gui-acceptance/m2`。

| 共享入口 | 测试数 | 实际 GUI 结果 |
| --- | ---: | --- |
| `Kura plain JUnit` | 7 | Run 全通过，exit code 0 |
| `Kura Equinox JUnit` | 8 | Run 全通过，约 20 秒 |
| `Kura Equinox JUnit` | 8 | Debug 全通过，exit code 0，包含断点暂停 |

Debug 在 `LegacyCoreRuntimeIT.java:92` 命中；此时实际 SCR 组件激活检查已经通过，
变量中可见 60 个已安装 bundle 以及 `testServiceExists` 场景。单步跨过该场景到
第 93 行后，调试器求值 `runtime.bundle(FIXTURE).getSymbolicName()` 返回
`org.eclipse.kura.testing.configuration.fixtures`，`getState()` 返回 32（ACTIVE）。
移除本次断点并恢复运行后，八项场景全部完成；没有遗留测试 JVM。

右侧 Maven Profiles 启用了 `workspace`、`dev-runtime`、`osgi-it`、`endpoint-it`
和 `javadocs`。Maven 3.10 的 effective POM 确认前两者合并后 runtime 模块只出现
一次。sibling 导入后另行显示的 `releaseBuild` 和 `sign-artifacts` 未启用：前者
拒绝当前 SNAPSHOT 版本，后者需要签名密钥；`test-debug` 是旧 Tycho 配置。

首次 Equinox GUI 运行在完成全部场景前，IDEA 被 VM 的 4 GB cgroup 限额触发
OOM kill，该次运行不计为通过。`free` 显示的全局内存不能替代 cgroup 限额。
随后仅为 VM 的 IDEA 启动创建独立 VM options：堆 1 GB、代码缓存 256 MB、
`ActiveProcessorCount=4`。实际 JVM flags 已核实；以上通过结果来自调整后的完整
Equinox Run/Debug，未改变被测代码、超时、OSGi 元数据或 Kura 运行参数。

截图和校验和保存在本地
`/Users/heyoulin/iot-kura-develop/migration-baseline/linux-idea-gui-20261010`。
这些 GUI 执行不重复加入全工作区 Maven 报告总数。本节覆盖 Linux 的 JUnit
入口；完整 `Kura Linux` 应用启动/断点/停止重启已在
[应用验收记录](linux-idea-application-acceptance.md)中完成。其他延后场景及 P7 仍需完成。
