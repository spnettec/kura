# 当前完整 workspace 门禁 — 2026-10-11

macOS arm64，Maven 3.10.0 / Temurin JDK21，JUnit5；`RUN_TESTS=1`、
`RUN_IT=1`、`BUILD_DOCKER=0`。实际 CI wrapper 在 14 个固定提交的干净
隔离 clone 中执行，退出码 **0**。

- **5,521 次调用、0 失败、0 错误、9 跳过**。
- **409 份报告**，0 excluded；原报告、发布副本和当前对应测试源码的
  SHA256 全部核对，0 mismatch；clone 的 HEAD 和干净工作区也已核对。
- Cloud 实际 Equinox/SCR **13/13**，包含文件密钥库 WSS 正反证书路径及
  文件持久化重启；7 个相关测试/配置文件与当前源码一致。
- 9 个跳过为两个未提供 KURA_SYSTEM_PATH_FIXTURE 的 system 用例、一个
  Linux clock 用例，以及六个现有 YOFC 外部数据库/硬件用例。沿用现有边界。

## 提交与证据范围

本次 CI 的 core 是 `578b32b17084`，Camel 是 `ae9ece56188a`；14 个
完整提交、409 份报告清单、日志及哈希记录在 [JSON](current-workspace-ci-validation-20261011.json)
及其中指向的本地归档。后续公共 Vertx 的 Multi-Release 清单/Reficio
修复、opt-in 验收 helper 和文档变更有独立证据：
[新组装运行集](mac-packaged-camel-vertx-validation-20261011.md)、
[IDEA 三种 DSL](mac-idea-camel-dsl-validation-20261011.md)。
不把较早 CI 记为后续 HEAD 的完整重跑。

IDEA 3 次、MQTT/HTTP 运行断言不加入上述 JUnit 总数。远端 Jenkins、
Docker 镜像、旧 P2 发布、installed Debian 和硬件验收保持各自边界。
2026-10-10 的 5,515 次调用保留为历史记录。inventory 仍是 465 reviewed、
0 unreviewed、0 deferredScenarios、31 deferredValidation，整体恢复未完成。

19 个原仓库最终核对均干净。15 个发布的 codex 分支与 fork HEAD 一致；
PLC4X 的本地 codex 分支没有远端同名 ref，其未改变的 HEAD 与已有 fork
`heyoulin` 分支一致。三个本地 management 仓库无 remote，保持原状。

## 2026-10-11 后续 Sparkplug 中断修复

此前未验证的连接等待中断差异已单独复现并修复；模块 155/155、真实容器
13/13、IDEA Run 3/3 通过，见 [新证据](sparkplug-interrupted-reconnect-validation-20261011.md)。
原记录与完整 CI 数字保留其固定提交范围，不将后续修复记为完整门禁重跑。

## 2026-10-11 Triton 数组配置及真实 SCR 后续

相同端口数组经复制后误判为配置变更的问题已单独复现并修复。完整模块
119/119、IDEA 3/3 通过；实际 Mac Remote/Native/Container 工厂 SCR 配置生命周期
及 remote channel 更新/关闭通过，未启动 Triton/GPU/native 进程/容器。
见 [验收记录](triton-copied-configuration-scr-validation-20261011.md)。
旧完整 CI 保留固定提交范围，未覆盖此后续私有生产修复；结果不相加。
