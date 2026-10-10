# JUnit 5 真正的 Equinox 容器测试

```sh
mvn -Posgi-it -pl :kura-osgi-tests -am verify
```

`process-test-resources` 将固定清单中的真实 JAR 收集到 `target/it-bundles`。准备好后 IDEA 可直接运行 `BundleRuntimeIT`（工作目录为本模块）。普通 `mvn test` 不启动容器集成测试。

测试控制端只有 JUnit 和 Equinox API；业务依赖用 POM 类型建立 reactor 顺序，业务 JAR 不在控制端 classpath。通过真实 bundle 加载的接口调用服务和创建测试代理，不向 system packages 导出 Kura 包，不添加通配导入。

每个测试使用独立 framework storage。失败保留 `target/osgi-it/<test>-*/`，包含 bundle 状态、未解析 requirement/候选提供者、SCR 配置策略、组件状态和未满足引用；标准输出/错误保存在 Failsafe 报告。成功时停止框架、释放取得的服务并删除临时 storage。

`EquinoxRuntime.register` 创建的 keystore 代理只服务测试框架，RSA 密钥在测试内生成，不连接现场 PLC、云端或真实业务系统。

当前 64 项真实容器测试包括原有 6 项 JWT/fragment/负向打包测试，以及 47 项配置测试
（46 个上游场景 + 1 个本地明文快照/CDATA 场景），另有 1 项通信服务存在性测试和 8 项旧核心配置/清单协议场景。它们不替代完整 Kura 仿真、发行包和硬件验收。

配置测试另行准备 `target/config-it-bundles`，包含实际 configuration、crypto、XML、
metatype 及测试夹具 bundle。上游场景在已安装的测试 bundle 中执行，控制端仍没有业务
Kura JAR。SystemService 只提供隔离目录、快照数量和加密开关；CM、SCR、密码与快照服务
都由实际 bundle 提供。根 `osgi-it` profile 自动把测试夹具纳入 reactor，默认生产构建不包含它。

准备 bundle 后，IDEA 可运行 `ConfigurationServiceRuntimeIT`（工作目录为本模块）。
macOS IDEA 已直接运行 `BundleRuntimeIT` 的 6 项和 `LegacyCoreRuntimeIT` 的 8 项，
并验证真实 SCR 回调断点与单步；尚未在 GUI 执行全部 62 项。共享运行配置和准备步骤见
[`docs/testing/idea-junit-acceptance.md`](../docs/testing/idea-junit-acceptance.md)。
配置场景说明见 `docs/testing/configuration-runtime-test-restoration.md`。

`CommServiceRuntimeIT` 使用 `target/comm-it-bundles` 中的真实 core.comm 和 jSerialComm，
只验证当前 CommConnectionFactory 的 SCR 注册及包绑定，不打开串口。

`LegacyCoreRuntimeIT` 另使用 `target/legacy-core-it-bundles` 中的 JSON/keystore 依赖，
通过实际 SCR 绑定的处理器测试 CONF-V1 和 INVENTORY-V1。Felix DeploymentAdmin 在
独立 framework 中安装并卸载临时测试包；SystemService 的 OS 包列表受控。此套件的
传输入口是 RequestHandlerRegistry，不代表 MQTT 端到端验证。详见
`docs/testing/legacy-core-protocol-restoration.md`。完整 64 项容器测试已在 Maven 下通过。

`SystemServicesRuntimeIT` 增加 2 项真实 SystemService/SystemAdminService 注册测试，
使用 `target/system-it-bundles` 中的实际 core.system 和 JUL 桥接 bundle。配置目录
临时隔离，PrivilegedExecutorService 只提供拒绝执行命令的边界；不运行系统管理命令。
