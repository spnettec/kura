# Jackson / YAML / JAXB 打包边界核对（2026-10-09）

迁移保持 Jackson 2/3 并存，不统一升级、替换或扩展业务包导出。

| 使用方 | 原有方式 | 迁移结果 |
|---|---|---|
| Kura 核心 / 既有第三方 | Jackson 2.22；Jakarta JAXB 4.0.2 | 版本、JAR 与原包一致 |
| YOFC / Vert.x | Jackson Core/Databind 3.2，annotations 2.22 | 保持原包及导入范围 |
| YOFC OPC UA YAML 配置 | 私有 `lib/jackson-dataformat-yaml-3.2.0.jar` + `lib/snakeyaml-engine-3.0.1.jar` | 两个嵌入 JAR 逐字节一致；未改成外部导入 |
| 核心发行目录的独立 YAML/JAXB 扩展 | `plugins/6/jackson-dataformat-yaml-3.2.0.jar`、`jackson-module-jaxb-annotations-3.2.0.jar` | 原样保留，不额外向公共运行集补库 |

对照源是默认 Maven 仓库中 **11:15 生成的迁移前 gateway ZIP/deb**，已另存至工作空间外 `migration-baselines/original-distribution-1115/`。不是以新构建反推旧行为。原包 216 个 JAR 的路径和 SHA256 与转换前记录全部一致；其中 Jackson、JAXB、SnakeYAML 的字节均未因迁移改变。

通过原发行包的 JAR 和原 Equinox 3.24.100，在隔离 framework storage 中运行真实解析器，独立的 YAML/JAXB 扩展同样分别缺少 `org.snakeyaml.engine.v2.*` / `javax.xml.bind` 公共包提供者。新 Docker 的相同诊断因此不能归因于迁移，也不代表 OPC UA 缺少 YAML 库：OPC UA 使用自己 bundle 的私有嵌入类。

这是原发行目录中额外扩展的解析状态，区别于业务功能故障。原仿真清单没有加载这两个独立扩展，全部目标 bundle 可解析。迁移保留该差异；发行验收必须单独报告这两个状态，不能声称全部发行 JAR 均已解析，也不能通过扩大导出或补公共依赖掩盖差异。

实验性新增 SnakeYAML Engine/JAXB API/Activation 公共依赖已撤回，未提交。后续若要清理重复扩展或正式启用独立扩展，应作为另外的交付边界变更评审。
