# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Eclipse Kura 是一个面向 **IoT/边缘网关** 的 Java/OSGi 框架，版本 `6.0.0-SNAPSHOT`。本仓库（"monorepo"）只保留**核心运行时 + API + 基础服务**，其余功能（云连接、网络、Web UI、Wires、Container、AI 等）都已经拆分为**独立的 sibling 仓库**，各自独立打包成 `.deb` 加载到 Kura 之上。

## 多仓库布局

工作树同级目录下并存的仓库（执行构建时按需 clone）：

```
git/
├── kura/                  ← 本仓库：核心 + API + 基础服务 + kura-core.deb + docker 镜像
├── kura-artemis/          ← Artemis MQTT broker bundles
├── kura-camel/            ← Apache Camel 集成 + Wires Camel 组件
├── kura-cloud/            ← 云连接器：Sparkplug、Kapua、Raw MQTT、EclipseIoT、cloudcat
├── kura-container/        ← Container 编排（docker-java 3.2.12 + Jackson 2）
├── kura-deployment/       ← 部署代理 + hook + REST packages
├── kura-management-ui/    ← GWT Web2 管理控制台
├── kura-networking/       ← linux.net + nm + 防火墙 + 威胁管理 + REST
├── kura-opcua/            ← OPC UA 设备驱动
├── kura-position/         ← GPS / 定位
├── kura-triton/           ← 边缘 AI（Triton Server）
├── kura-wires/            ← Wires 数据流编排 + 资产 Cloudlet + Wires REST
└── kura-yofc-runtime/     ← yofc-iot 运行时支持库（fastjson2 + javacan + yofc-only vertx 包）
```

Sibling 的 bundles 通过 Import-Package 从 monorepo 的 `org.eclipse.kura.api` 拉接口，**编译期只依赖本仓库构建出的 m2 artifact**，sibling 之间无相互依赖。

## 已彻底移除（不要从上游回迁）

- **GPIO** — `kura.gpio` API、`core.status` 中 GPIO 集成、`jdk.dio` 全部删除（用 plc4j 替代）
- **Command** — `command.provider` 实现 + API + web2 "Command" 标签 + i18n 全删
- **Bluetooth** — `kura.bluetooth.le*` 全套 impl + API 删除，无 sibling 接管
- **历史驱动** — `s7plc`、`block`、`ibeacon` 驱动全删；OPC UA 驱动迁到 sibling
- **Modbus** — `org.eclipse.kura.protocol.modbus` 早已废弃，已彻底移除

monorepo 内目前**只保留** `org.eclipse.kura.driver.helper.provider`（被 wires + management-ui 通过 `DriverDescriptorService` 消费）。

## 构建命令（Maven Bundle Plugin 迁移后）

当前默认入口为普通 Maven，旧 Tycho/PDE 文件仅按实际兼容消费者保留。
以实际 POM、`build-all.sh` 和 `docs/migration/README.md` 为准，不恢复旧构建链。

```bash
mvn clean install                  # 公共 parent/BOM、封装与核心
BUILD_DOCKER=0 ./build-all.sh        # 完整工作空间，默认跳过测试
RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 ./build-all.sh
```

脚本顺序：公共构建支持/第三方封装 → 核心及可选 Equinox 测试 → sibling
及可选 HTTP/MQTT 测试 → YOFC → 核心发行包/开发运行集 → 可选 Docker 双架构镜像。
必需 sibling 缺失会失败，不再跳过。PLC4X 从源码独立构建并安装到相同 Maven
缓存，是显式前置步骤，不纳入 Kura reactor，也不扩展其测试。

直接 Maven 使用 `-Dmaven.repo.local=/absolute/cache`；脚本使用
`KURA_MAVEN_REPO=/absolute/cache`。sibling 根 POM 已包含自己的发行模块。

```bash
mvn -f path/to/module/pom.xml test -Dtest=ClassName
mvn -Posgi-it -pl :kura-osgi-tests -am verify
mvn -f kura-endpoint-tests/pom.xml verify
mvn -f kura/distrib/pom.xml help:all-profiles
mvn -f kura/distrib/pom.xml install -Parch-aarch64,!arch-x86_64
```

先安装对应核心/sibling fixture 后再单独跑 endpoint。Surefire/Failsafe 报告
位于各模块的 `target`；不再从旧 `kura/test` 统计。`-DskipTests` 不替代
Failsafe 的 `-DskipITs`，跳过全部测试时需同时指定。

Jenkins 调用 `tools/ci/verify-workspace.sh`，要求预置专用多仓库 workspace、
Maven 3.10/JDK 21 和 PLC4X 缓存；不假设 Eclipse 的工具名/凭据存在。
不自动重跑或忽略失败，只发布本次且能匹配当前源码的测试报告。
见 `docs/migration/ci-migration.md`；本地检查不代表远端 Jenkins 已验收。

## 环境要求

- **JDK 21** — 核心/运行集使用 Java 21。
  - 例外：`kura-management-ui/bundles/org.eclipse.kura.web2` 保留 Java 11 编译目标（GWT 约束）。
- **Maven 3.10**，Maven Bundle Plugin 6.0.0，JUnit 5。
- **Docker** — 仅构建镜像时需要；默认脚本构建 ARM64 和 AMD64。
- IDEA 应用仍运行时禁止 clean/重组装同一个 `target/runtime`。
  `~/.kura-dev/<profile>` 中个人快照、密钥和配置不重置、不入 Git。
- 2026-10-10 用户要求不再追加 Linux 验证；继续使用 macOS 验收。
  未实际执行的硬件/系统 D-Bus 验证不能据此记为通过。

## Monorepo 模块（本仓库 kura/）

```
build-support/     → 普通 Maven parent/BOM、第三方封装、OSGi 测试支持
kura-dev-runtime/  → 独立 Equinox 运行集
kura-osgi-tests/   → 真实容器测试
kura-endpoint-tests/ → HTTP/MQTT 端点测试
target-platform/   → 保留的 P2/PDE 兼容输出（不在默认构建）
kura/
  ├── org.eclipse.kura.api                    → 公共 API（含 container/* 接口供 sibling 引用）
  ├── org.eclipse.kura.core*                  → 核心服务（configuration/identity/keystore/inventory/system/status/...）
  ├── org.eclipse.kura.asset.provider         → 资产抽象（被 wires sibling 消费）
  ├── org.eclipse.kura.driver.helper.provider → DriverDescriptorService（被 wires + management-ui 消费）
  ├── org.eclipse.kura.linux.clock|usb|watchdog|position.spi → Linux 适配
  ├── org.eclipse.kura.db.{h2db,sqlite}.provider → DB 服务
  ├── org.eclipse.kura.rest.*                 → 基础 REST（configuration/identity/inventory/keystore/security/system/...）
  ├── org.eclipse.kura.localization*          → i18n 资源（YOFC 已在 bundle 层级与上游分叉）
  ├── org.eclipse.kura.{json,xml}.marshaller.unmarshaller.provider
  ├── org.eclipse.kura.http.server.manager    → HTTP 服务
  ├── org.eclipse.kura.useradmin.store
  ├── org.eclipse.kura.script.provider
  ├── org.eclipse.kura.log.filesystem.provider
  ├── org.eclipse.kura.event.publisher
  ├── org.eclipse.kura.configuration.change.manager
  ├── org.eclipse.kura.util / test-util       → 工具 + 测试支持
  ├── kura-pde-deps / target-definition       → 保留的旧 PDE 兼容配置
  ├── emulator/                               → 本地仿真启动配置
  ├── distrib/                                → kura-core.deb + docker 镜像
  └── tools/                                  → kura-addon-archetype 等
```

## Sibling 安装路径约定

- **kura-core.deb** → `/opt/eclipse/kura/plugins/{1,1s,2,2s,3,3s,4,4s,5,5s,6,6s}/`
- **每个 sibling .deb** → `/opt/eclipse/kura/siblings/<name>/<level>/`
  - 例如 `kura-wires` 落在 `/opt/eclipse/kura/siblings/wires/{3s,4s,6s}/`
  - dpkg 文件追踪互不冲突，可独立 `apt install/remove`

`gen_config_ini.sh` 先扫 `plugins/` 再扫 `siblings/*/`，按 JAR 文件名去重（默认 `kura-first`，可改 `sibling-override`）。

Sibling 安装顺序通过 `/opt/eclipse/kura/framework/sibling-install-order` 注册表追踪；卸载时 sibling 的 postrm 会从注册表移除自身。

## 关键设计原则

- **OSGi Bundle 是基本交付单元**；生产模块 packaging 为 `bundle`，保留手写 MANIFEST、DS/metatype 和嵌入布局
- **普通 Maven + Maven Bundle Plugin 构建**；不要重新引入 Tycho 或用自动推导覆盖手写 OSGi 元数据
- **API 与实现分离**：插件开发依赖 `org.eclipse.kura.api`，不要直接依赖 `core*` 实现
- **Sibling 通过 Import-Package 拉 monorepo API**，**不要**把 sibling 的实现包反向引入 monorepo
- **扩展点机制**：通过 `kura/tools/kura-addon-archetype` 模板创建新插件
- **Web 前端 GWT**（`gwtbootstrap3`），不是现代 npm/React 生态

## 开发注意事项

1. **修改 API（`org.eclipse.kura.api`）** 会同时影响所有 sibling，需要在所有 clone 都构建一遍验证
2. **修改 monorepo 核心** 前确认会影响哪些 sibling/feature/发行包
3. **修改依赖版本** 需同步检查 `target-platform/pom.xml` 兼容性
4. **驱动/Linux 模块** 的改动可能只在特定硬件上暴露问题
5. **测试覆盖率较低**，大部分模块无 `src/test`，改核心逻辑要格外谨慎
6. **容器构建支持 ARM64/AMD64**，各镜像必须配套同架构 deb
7. **不要在 monorepo 内增加面向特定 sibling 的代码**——如果 wires/container/cloud 需要新功能，加在对应 sibling 里
8. **CloudConnection bundles 已与上游分叉**（i18n 层面），上游 `CloudConnection*` 提交要手动合并，不要批量 cherry-pick
9. **Localization bundle 与上游分叉**，禁止 cherry-pick 上游 `664f0878e5` (#5891)

## Snapshot 行为

### 卸 sibling 后的孤儿配置项

卸任意一个 sibling（kura-wires / kura-cloud / kura-opcua / kura-networking / kura-camel / kura-container / kura-deployment / kura-position / kura-triton / kura-artemis / kura-management-ui）之后，它注册过的 ConfigurableComponent 在 `snapshot_0.xml` 里的条目**不会自动清理**。Kura 重启时 `ConfigurationServiceImpl.loadLatestSnapshotInConfigAdmin()` 会遍历这些条目，找不到对应 `factoryPid` 的 `ManagedServiceFactory` 就抛 `KuraException`，上层 catch 成 `WARN` 后继续：

```
WARN  Error creating configuration with pid: <pid> and factory pid: <factoryPid>
```

要点：

- **不会阻断启动**——所有 sibling 同行为，由 monorepo `ConfigurationServiceImpl` 统一处理
- **孤儿条目会不断 round-trip**：`buildCurrentConfiguration()` 把它们和有效配置合并写回新 snapshot，`snapshot_N.xml` 越来越胖
- **Web UI 不显示孤儿条目**（缺 OCD 元数据）
- **清理只能手动**：装回 sibling 后通过 UI 删 → 触发 `snapshot()` 重写干净版本；或直接编辑 `snapshot_0.xml`
- **自定义编排已防御**：`WireGraphServiceImpl` 找不到引用 component 时静默跳过那条 wire（不抛异常）；写 OSGi 服务时遵循同样模式

### snapshot 加密开关（YOFC 特性，与上游不同）

上游 Kura 强制使用 `CryptoService` master key 加密 snapshot。YOFC fork 通过 `/opt/eclipse/kura/framework/kura_custom.properties` 中的 `kura.snapshots.encrypt` 控制：

| 取值 | 行为 |
| --- | --- |
| `kura.snapshots.encrypt=true`（默认） | 加密写出，与上游一致 |
| `kura.snapshots.encrypt=false` | 明文 XML，方便排障 / sibling 互换 |

读取处：`ConfigurationServiceImpl`（搜 `kura.snapshots.encrypt`）。

**与 kura-networking / kura-firewall-only preinst 的关联**：两个网络包的 `preinst` 都会检查 `snapshot_0.xml` 第一行是不是 `<?xml ...?>`——加密文件首字符不是 `<`，preinst 立刻 `exit 1` 拒装。所以生产环境要么在首次 `start kura` 之前装好网络包，要么把 `kura.snapshots.encrypt` 关掉。详见 memory `project_snapshot_encrypt_toggle`。

**禁止 cherry-pick** 上游硬编码加密路径的 commit（会回退到强制加密），跟 `[[project_cloudconnection_i18n]]` 同样属于 YOFC 设计偏离区。

### Snapshot XML 解析失败 — 改名而非删除

`ConfigurationServiceImpl.loadLatestSnapshotConfigurations()` 加载最新快照时，如果 XML 解析失败（`DECODER_ERROR`），原逻辑是 `deleteSnapshotId(id)` 直接删除 → 递归试上一个。如果连续多个快照损坏会导致数据丢失。

**已改为 `renameSnapshotToBad(id)`** — 将 `snapshot_N.xml` 重命名为 `snapshot_N.xml.bad`，保留现场。重命名失败时 fallback 到删除。

### Snapshot XML 写入 — CDATA 自动包裹

`XmlJavaComponentConfigurationsMapper.marshal()` 写出 `<esf:value>` 时，如果值含有 `<`、`>` 或 `&`，自动用 `<![CDATA[...]]>` 包裹。这样 `initCode`、`xml.data` 等内联代码可以直接嵌入原始源码，不会因转义问题导致快照 XML 解析失败。

## 上游同步策略

- 不能用 `git merge -s ours` 来跳过单个 commit——会把 ancestor 也吞掉
- YOFC 设计偏离 upstream 的 commit 通过 plumbing `commit-tree` 显式构造合并节点（详见 memory）
- Sibling 拆分 + GPIO/Command/Bluetooth/Driver 等的删除已写进 upstream skip list

## 常用开发模式

### 创建新插件/扩展

1. 用 `kura/tools/kura-addon-archetype` 生成脚手架
2. 依赖 `org.eclipse.kura.api`，通过 OSGi Service 注册
3. 如果是 monorepo 内 bundle，在 `kura/pom.xml` 加 `<module>`；如果是新功能领域，考虑直接做成 sibling

### 本地调试

IDEA 导入根 POM，按需启用 workspace/osgi-it/endpoint-it profiles，使用 `.run/` 中共享应用与 JUnit 配置。应用启动前增量构建，开发运行集见 `kura-dev-runtime/README.md`。旧 Eclipse 安装与 workspace 保留，不自动卸载。

### REST API 开发

REST 模块位于 `kura/org.eclipse.kura.rest.*`（基础）或各 sibling 的 `rest.*` bundle，基于 JAX-RS/Jersey。新增端点参考现有 `rest.provider` 模块结构。

## 其他

- 本文件即 `AGENTS.md`（Claude Code ≥2.1.28 与 Codex / Cursor / Aider 等其他 agent 均原生读取，已不再需要 CLAUDE.md + symlink 方案）
- `PROJECT_ANALYSIS_REPORT.md` 是历史快照，不是权威来源；以 pom / 实际代码为准

# Codebase Memory MCP — Code Intelligence

This project is indexed by **codebase-memory-mcp**. Always use it BEFORE grep/find or reading files when you need to understand or locate code. The skill at `~/.claude/skills/codebase-memory/` contains the full decision matrix and workflow.

## Quick Reference

| Question | Tool |
|----------|------|
| Who calls X? | `trace_path(direction="inbound")` |
| What does X call? | `trace_path(direction="outbound")` |
| Find by name | `search_graph(name_pattern="...")` |
| Dead code | `search_graph(max_degree=0)` |
| Impact of changes | `detect_changes()` |
| Architecture overview | `get_architecture(aspects=["all"])` |
| Read source | `get_code_snippet(qualified_name="...")` |

## Exploration Workflow

`list_projects` → `get_graph_schema` → `search_graph` → `get_code_snippet`

> If the repository hasn't been indexed yet, run: `codebase-memory-mcp cli index_repository '{"repo_path": "/path/to/repo"}'`
