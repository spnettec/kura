# JUnit 5 真正的 Equinox 容器测试

```sh
mvn -Posgi-it -pl :kura-osgi-tests -am verify
```

`process-test-resources` 将固定清单中的真实 JAR 收集到 `target/it-bundles`。准备好后 IDEA 可直接运行 `BundleRuntimeIT`（工作目录为本模块）。普通 `mvn test` 不启动容器集成测试。

测试控制端只有 JUnit 和 Equinox API；业务依赖用 POM 类型建立 reactor 顺序，业务 JAR 不在控制端 classpath。通过真实 bundle 加载的接口调用服务和创建测试代理，不向 system packages 导出 Kura 包，不添加通配导入。

每个测试使用独立 framework storage。失败保留 `target/osgi-it/<test>-*/`，包含 bundle 状态、未解析 requirement/候选提供者、SCR 配置策略、组件状态和未满足引用；标准输出/错误保存在 Failsafe 报告。成功时停止框架、释放取得的服务并删除临时 storage。

`EquinoxRuntime.register` 创建的 keystore 代理只服务测试框架，RSA 密钥在测试内生成，不连接现场 PLC、云端或真实业务系统。

当前 6 项真实测试包括 JWT 配置/动态绑定、本地化 fragment/fallback，以及四类负向打包 fixture。它们不替代完整 277 bundle 仿真、发行包和硬件验收。
