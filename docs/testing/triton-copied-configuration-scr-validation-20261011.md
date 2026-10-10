# Triton 配置数组相等性修复与 macOS SCR 验收 — 2026-10-11

真实 SCR 运行暴露了相同配置再次更新时创建新 gRPC channel 的行为。
`server.ports` 经 ConfigAdmin 复制后是不同数组对象；原 options 的 Map 相等性
比较使用数组引用。两项确定性回归（options 相等/hash key、实际 gRPC channel
保留）在旧代码上失败，另一个变更值对照通过：**3 调用、2 失败、0 错误**。

生产修复 `9227d8ae38b0` 对 Map 值进行深比较，并按数组内容生成一致 hash；
真实端口/地址变更和缺失属性仍可区分。测试/helper 单独提交 `770f94762445`。
API、依赖版本、手写元数据与配置格式未改。

## 验证

- Maven 3.10.0 / JDK21 / JUnit5：完整 Triton 模块 **119/119**，0 失败/错误/跳过。
- 完整 workspace 中 IDEA 直接 Current File Run：新增回归 **3/3**，872 ms、正常退出。
- 独立 Mac 应用共 281 bundles。默认 Mac 运行集未包含 Triton，本次显式加入
  当前真实 Triton 产物和 observer；未替换生产服务，0 生产 overlay。
- Remote、Native、Container 三类实际 factory/SCR ACTIVE，使用生产服务绑定。
  Native/Container 用无效配置验证创建和删除，manager/channel 均未创建，未启动
  本地 Triton、命令或容器。Container 实际 orchestration provider 数量为 1。
- Remote 实际构造 gRPC Netty transport；未提供服务器时 readiness 返回 false。
  变更配置关闭旧 channel，无效配置关闭当前 channel，有效配置恢复；删除后
  服务/配置消失，最终 channel 终止。owned JVM 正常 SIGTERM 关闭，无强杀、端口释放。

构建、migration-m2 和实际添加的 JAR SHA256 一致：
`f5cd70f818d79255c72a3f560aab226b50655850c9a5421e5c4620ca91acb3d6`。
IDEA options 编译类与该 JAR 内字节码一致。301 个 probe 来源运行集/模板文件、
315 个原保护文件及 33 个个人持久配置文件未变。

## 失败现场与范围

两个早期 helper 归档保留：第一次未等待异步 modified 完成，第二次在服务注销
后立即检查 channel，早于 deactivate 完成。最终 helper 用实际配置值、live channel
及 channel 终止条件等待。它们属于验收 harness 修正，不能当作生产缺陷负证据；
生产负证据是前述两项确定性回归。

[JSON 证据](triton-copied-configuration-scr-validation-20261011.json) 包含报告、
源文件、截图、提交、产物及原始归档哈希。本轮 119/3 调用与应用断言存在重叠，
不累加到较早 5,521 次完整门禁。较早 CI 的固定提交未覆盖本轮生产修复。

真实 Triton 服务的 readiness/model/inference/metrics、native 进程、容器运行和
GPU/installed Debian 继续未验证。不追加 Linux，不扩展 YOFC/PLC4X，不修改
官方 OPC UA。inventory 仍有 **31 条 deferredValidation**，整体恢复未完成。
