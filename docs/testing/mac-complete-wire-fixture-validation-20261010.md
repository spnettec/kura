# 完整 Mac 运行集：历史 Wires fixture SCR 验收

2026-10-10；Maven 3.10.0、Temurin JDK 21、Bundle Plugin 6.0.0。
验收专用模块位于 `kura-wires/acceptance/full-runtime-fixture-probe`，不进入默认 reactor 或生产 Debian 包。

## 已实际通过

- 完整运行集 279 个 bundles，真实 `SystemServiceImpl`、ConfigurationService、SCR/OCD、DriverDescriptorService、WireGraphService 和 WireAdmin。
- 直接编译现有 migrated `ChannelDescriptorTestDriver` 源码；工厂实例 SCR ACTIVE，`test.property` OCD 默认值和实际配置更新正确，34 个 channel attributes 中的 8 个最小值均正确。
- 两个历史 emitter/receiver 等价验收实例 SCR ACTIVE；实际 SCR/OCD 返回一入一出端口及空 OCD。按当前 YOFC API 委托生产 WireSupport，真实 Producer/Consumer 回调按序收到 3 个含独立 nonce 的 WireEnvelope。
- 独立 HTTPS 客户端验证本次 localhost 证书及主机名，未认证请求返回 401；4 次已认证读取均为 200，核对同一批驱动描述符、driver OCD、emitter 定义和两组件一条 wire 的 graph snapshot。
- owned graph、driver/emitter/receiver 配置和服务全部删除；WireAdmin 无残留。JVM 已退出，无强制终止，18480/18443/18444 已释放。
- 原运行集 279 个 artifact 哈希匹配；个人 profile 的 33 个受保护文件、模板两个密钥库及停机日志均未改变。

这些是 executable acceptance 断言，独立于 JUnit 5 报告；不叠加到此前 5515 次 workspace invocation。

## 本次环境设置与诊断记录

完整运行集模板的 HTTPS 密钥库为空。本次仅在新 owned profile 的密钥库副本生成 localhost 密钥/证书；未修改模板。
通过真实 ConfigurationService 把该 profile 的 REST `allowed.ports` 设置为 18443；生产默认值仍是 443/4443。

所有失败运行均保留，且均已清理 owned 状态、退出 JVM、释放端口：
metatype XML 短文件名、未配置 HTTPS 证书、未放行验收端口、错误的 emitter REST DTO 名称预期，以及把 `/graph` 当成 GET 读取端点。
最终断言按生产 DTO 校验空 `componentOCD` 和六个端口数值，并使用实际 GET `/graph/snapshot` 读取接口。
编译阶段的依赖名及当前 YOFC Object/emit API 调整日志也一并归档；未据此改动生产代码。

## 清单边界

inventory indices 459、460、462、463 的 Mac historical fixture SCR/metadata/callback 边界已有上述证据，`deferredValidation` 仅保留 installed Debian sibling package acceptance。
当前仍是 465 条 reviewed、0 unreviewed、0 deferredScenarios，31 条 deferredValidation（31 个字符串）。
其他未实际执行的 deployed gateway、Linux/D-Bus、physical watchdog、Triton/GPU 等边界继续保留；不宣告整体完成。

最终 archive：`/Users/heyoulin/iot-kura-develop/migration-baseline/mac-complete-wire-fixtures-accepted-20261010`。
原始结果、源码/fixture/helper/log 哈希、6 次运行诊断和隔离对账见 [JSON](mac-complete-wire-fixture-validation-20261010.json)。
