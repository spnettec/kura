# IDEA JUnit 验收（2026-10-10）

在 macOS 的 IntelliJ IDEA 2026.2.3 中，使用项目 Temurin JDK 21 和 JUnit 5.14.4，
由 IDEA JUnitStarter 直接执行以下测试，均正常退出（exit code 0）：

| 入口 | 测试数 | 结果 |
| --- | ---: | --- |
| `Kura plain JUnit` → `KuraExceptionMessageTest` | 7 | Run 通过 |
| `BundleRuntimeIT` | 6 | Run 通过 |
| `Kura Equinox JUnit` → `LegacyCoreRuntimeIT` | 8 | Run 和 Debug 均通过 |

根 `.run/` 中提交了两个共享 JUnit 配置。它们使用项目 JDK 和相对工作目录，不写入
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

本记录只覆盖表中的实际 GUI 入口。其余配置/通信容器测试、HTTP/MQTT 端点套件、
Linux GUI IDEA、全工作空间回归和 P7 清理仍需各自验收；此前 Maven 的 62 项通过
不能作为所有测试已经在 IDEA GUI 运行的证明。
