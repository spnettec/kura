# CLAUDE.md

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

## 构建命令

### 三阶段一键脚本（推荐）

```bash
./build-all.sh              # 跳过测试（默认）
RUN_TESTS=1 ./build-all.sh  # 包含测试
```

执行顺序：
1. **Stage 1** — `target-platform/pom.xml` + `kura/pom.xml`（产出 monorepo bundles 到 ~/.m2）
2. **Stage 2** — 同级目录下存在的每个 `kura-*` sibling（顺序无关；缺失则跳过）
3. **Stage 3** — `kura/distrib/pom.xml`（产出 kura-core.deb + docker 镜像；docker-base 从 ~/.m2 拉 sibling jar 烘焙进 installer.sh）

**Stage 3 必须在 Stage 2 之后**，否则 docker 镜像里的 sibling jar 会缺失。

### 分步手工构建

```bash
# 1. 目标平台
mvn -f target-platform/pom.xml clean install

# 2. monorepo 核心
mvn -f kura/pom.xml clean install

# 3. 各 sibling（如有 clone）
mvn -f ../kura-wires/pom.xml clean install
mvn -f ../kura-wires/distrib/pom.xml clean install
# ...其余 sibling 同样模式

# 4. kura-core.deb + docker
mvn -f kura/distrib/pom.xml clean install -DbuildAll
```

### 跳过测试 / 特定 Profile

```bash
mvn -f kura/pom.xml clean install -Dmaven.test.skip=true
mvn -f kura/distrib/pom.xml help:all-profiles            # 列出所有 profile
mvn -f kura/distrib/pom.xml clean install -Paarch64
mvn -f kura/distrib/pom.xml clean install -DbuildAllContainers
mvn -f kura/distrib/pom.xml clean install -Ptarget-definition  # 仅迭代 P2 target
```

### 运行测试

```bash
mvn -f kura/pom.xml test                       # 全量
mvn -f <module>/pom.xml test -Dtest=ClassName  # 指定单测（Tycho Surefire）
```

Surefire 报告位于 `kura/test/*/target/surefire-reports/`。
CI（Jenkinsfile）使用 `-Dsurefire.rerunFailingTestsCount=3` 掩盖偶发性失败。

### 代码检查

```bash
mvn checkstyle:check  # 根目录 checkstyle_checks.xml / suppressions.xml
```

### CI 行为参考（Jenkinsfile）

- `temurin-jdk17-latest` + `apache-maven-3.9.6`
- target-platform 阶段附加 `-Pno-mirror -Pcheck-exists-plugin`
- 仅修改 `*.md` / `*.txt` 时跳过整个构建
- Sonar 扫描排除 `org.eclipse.kura.web2/**`（已迁到 sibling）、`...freedesktop|w1/**` 中的生成代码

## 环境要求

- **JDK 17** — monorepo 全部 `maven.compiler.source/target=17`，CI 使用 `temurin-jdk17-latest`
  - 例外：`kura-management-ui/bundles/org.eclipse.kura.web2` 编译目标仍是 Java 11（GWT 约束，**不要随意提升**）
  - 注意：仓库中 `jdk21` 命名的提交只改了 `docker-alpine-x86_64-nn` 运行时镜像，**不是**构建目标语言级别
- **Maven 3.9.x**（CI 用 3.9.6）
- **Docker/Podman** — 仅构建容器时需要

## Monorepo 模块（本仓库 kura/）

```
target-platform/   → P2/依赖管理、第三方 OSGi 化
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
  ├── kura-pde-deps / target-definition       → Tycho P2 配置
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

- **OSGi Bundle 是基本交付单元**，不是 JAR/WAR；packaging 为 `eclipse-plugin` 或 `eclipse-feature`
- **Tycho 构建**，不是标准 Maven 打包；理解 Tycho/P2/Feature 的关系很重要
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
6. **容器构建仅 x86 支持**，ARM 上的 Docker 构建未支持
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

使用 `kura/emulator/` 中的 Kura_Emulator 启动配置在本地仿真运行，无需真实网关设备。

### REST API 开发

REST 模块位于 `kura/org.eclipse.kura.rest.*`（基础）或各 sibling 的 `rest.*` bundle，基于 JAX-RS/Jersey。新增端点参考现有 `rest.provider` 模块结构。

## 其他

- 仓库根的 `AGENTS.md` 是指向本文件的 symlink（兼容 Codex / Cursor / Aider 等其他 agent），只维护本文件即可
- `PROJECT_ANALYSIS_REPORT.md` 是历史快照，不是权威来源；以 pom / 实际代码为准

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **kura** (20172 symbols, 55202 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/kura/context` | Codebase overview, check index freshness |
| `gitnexus://repo/kura/clusters` | All functional areas |
| `gitnexus://repo/kura/processes` | All execution flows |
| `gitnexus://repo/kura/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
