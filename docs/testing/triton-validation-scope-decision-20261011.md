# Triton 后续验收范围调整 — 2026-10-11

用户回复“Tiiton就不测了”，本任务不再追加或重跑 Triton 测试。
清单中的 9 条真实服务、模型/推理/metrics、native/container/GPU 待验收边界
转为 `excludedValidation`，决定为 `excluded-by-user`，不记为验收通过。

已恢复的测试源码、生产修复和历史证据保留：完整模块 119/119、IDEA 3/3、
实际 Mac 三类工厂 SCR/配置及 remote channel 生命周期的结论保持原范围。
这些结果不证明已排除边界通过。本次没有运行测试或修改生产代码。

当前清单：**465 reviewed、0 unreviewed、0 deferredScenarios、22
deferredValidation、9 excludedValidation**。另外 22 条部署/硬件及外部
SecurityService 验收仍待执行，整体恢复未完成，不追加 Linux 验证。

见 [范围决定及逐项记录](triton-validation-scope-decision-20261011.json)、
[原 Triton 验收证据](triton-copied-configuration-scr-validation-20261011.md) 和
[权威清单](upstream-test-inventory.json)。此前报告中的 31 条统计属于本决定前的历史范围。
