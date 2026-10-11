# 新 Mac IDEA 测试/调试环境配置指南

面向在新 Mac 上做 Kura 开发测试的开发人员。照本文从零开始即可运行单元测试、
端点测试和完整网关调试，**不需要**任何迁移期归档目录。

## 1. 前置要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| macOS | — | 开发测试只面向 Mac |
| JDK | Temurin 21 | 核心/运行集都用 Java 21；仅 `kura-management-ui`（GWT）保持 Java 11 编译目标 |
| Maven | 3.10 | 公共入口兼容 3.9 |
| python3 | 3.9+ | `kura-dev-runtime/tools/runtime.py` 使用 |
| IntelliJ IDEA | 近年版本 | 需捆绑/外置 Maven 支持 |

## 2. 仓库布局与一次性的 Maven 下载

把各仓库 clone 到**同一父目录**并列放置（工作空间没有 umbrella 仓库）：

```
<工作空间>/
├── kura/            ← 核心 monorepo（本指南主文档在这里）
├── kura-cloud/      ← Sparkplug / Kapua / Raw MQTT 等云连接
├── kura-camel/      ← Camel 集成
├── kura-networking/ ← 网络 / 防火墙
├── plc4x-yofc/      ← PLC4X 定制（Maven 前置依赖）
└── ...（其余 sibling 按需）
```

**Maven 缓存直接用默认 `~/.m2/repository`**：IDEA 与 CLI 都无需任何 override，
首次构建自动全量下载（一次性）。唯一不能从远端获得的是 `plc4x-yofc`
产物，缺失时先安装（下面脚本会检测并提示）：

```sh
cd <工作空间>/plc4x-yofc
mvn install -DskipTests
```

> 迁移期的 `migration-baseline`、`migration-baselines`、
> `migration-cold-m2-20261009`、`test-restoration` 目录都是原机器上的
> 证据归档/对照快照，**新机器一概不需要**。

## 3. 快速开始

```sh
cd <工作空间>/kura
tools/ide/setup-idea.sh            # 环境检查 + 使用说明（默认 ~/.m2）
tools/ide/setup-idea.sh --build-runtime   # 需要提前组装 target/runtime 时
```

脚本只做检查、提示与本地生成，不修改任何已提交文件；`--dry-run` 可预览动作。
可选参数：`--m2 <dir>` 使用隔离缓存（此时 IDEA 需在
Settings → Build, Execution, Deployment → Build Tools → Maven → Local repository
指向同一目录）；`--isolated-home <dir>` 生成使用隔离数据目录的本地启动配置（见 §5）。

然后在 IDEA 中：

1. 打开各仓库根 `pom.xml` 作为项目（kura、kura-cloud、kura-camel、kura-networking），等待 Maven 导入完成。
2. kura 项目在 Maven 面板勾选 `workspace` profile（sibling 聚合与运行目录组装依赖它）。
3. Project SDK 选择 JDK 21。
4. Run/Debug Configurations 里选择仓库内置的共享配置（见 §4），Run 或 Debug。

## 4. 已内置的共享运行配置（`.run/`，随 git 自动加载）

各仓库 `.run/*.run.xml` 已提交进 git，全部使用 `$PROJECT_DIR$` 宏，无机器专属路径：

| 仓库 | 配置 |
| --- | --- |
| kura | 各端点 JUnit（configuration / identity V1·V2 / keystore V2 / security V1·V2 / service listing / system / tamper / wire graph / http）、BundleRuntimeIT（Equinox）、Kura Equinox / Comm Equinox / plain JUnit、Kura macOS（完整网关 JAR Application） |
| kura-cloud | CloudFactoryRuntimeIT 三个入口：core protocol / Sparkplug / TLS 运行时；Sparkplug interrupted reconnect 单测 |
| kura-camel | Camel DSL 单测（XML / Java / YAML 三 DSL 的 ForkDslRoutesProviderTest） |
| kura-networking | 网络枚举 JUnit |

`Kura macOS` 是完整网关启动配置：Before launch 会自动执行
`-Pworkspace -pl :kura-workspace,:kura-dev-runtime -am install -DskipTests -DskipITs -Dkura.dev.profile=macos`
组装 `kura-dev-runtime/target/runtime`，然后以 `launcher.jar` + `@jvm.args`
启动 Equinox。在 bundle 激活和业务方法上直接设断点即可调试。
组装失败会阻止启动（最常见原因是缺 plc4x 产物）。

## 5. 数据目录与 jvm.args / kura.properties 的生成机制

- 用户数据默认在 `~/.kura-dev/macos`（可用 `KURA_DEV_HOME` 覆盖，**不允许**放在模块 target 内）。
- `target/runtime/jvm.args` 与 `target/runtime/configuration/kura.properties` 由
  构建期 `tools/runtime.py assemble` 生成：git 中提交的是模板
  （`src/main/resources/kura.properties` 里的 `@KURA_DEV_HOME@` 占位符）与生成器本身；
  生成结果只指向 `target/runtime` 和数据目录，换机器/换目录重新组装即重新生成，
  不会携带其他机器的路径。
- IDEA 运行配置里设置的环境变量**不会**传给 Before launch 的 Maven 步骤。
  要用非默认数据目录：先在终端
  `KURA_DEV_HOME=<目录> tools/ide/setup-idea.sh --isolated-home <目录>`
  （脚本会用该目录组装运行时，并在 kura 的 `.idea/runConfigurations/` 生成
  带 `KURA_DEV_HOME` 环境变量、无 Before launch 步骤的本地启动配置；
  `.idea` 已被 git 排除，仅本机生效）。
- 端口默认 8080/8443/8444，可用 `KURA_HTTP_PORT` / `KURA_HTTPS_PORT` /
  `KURA_CLIENT_AUTH_PORT` 覆盖；已有 profile 会沿用其快照端口。

## 6. 如何新增运行配置并分享给团队

1. Run → Edit Configurations → `+` 选择类型（截图示例为 JAR Application）。
2. 按类型填写；两个常用模板：
   - **JUnit**：module 选被测模块（Maven artifactId）、Test class 填全限定类名、
     Working directory 选模块目录、VM options 填 `-ea`。
   - **完整网关 JAR Application**：Path to JAR =
     `$PROJECT_DIR$/kura-dev-runtime/target/runtime/launcher.jar`；
     VM options = `@"$PROJECT_DIR$/kura-dev-runtime/target/runtime/jvm.args"`；
     Program arguments = `-configuration "$PROJECT_DIR$/kura-dev-runtime/target/runtime/configuration" -consoleLog -console`；
     Working directory = `$PROJECT_DIR$/kura-dev-runtime/target/runtime`；JRE = 21；
     Before launch 加 Run Maven Goal（命令见 §4）。
3. 勾选右上角 **Store as project file** —— 配置自动存入仓库 `.run/` 目录，
   随 git 提交分享给所有开发人员。
4. 提交 `.run/*.run.xml`；机器本地的 `.idea/` 已被 git 排除，不会误提交。

## 7. 常见问题

- **模块名标红 / Main class 找不到**：Maven 导入未完成；等索引与依赖解析结束再运行。
- **Before launch Maven 失败**：多为缺 `plc4x-yofc` 产物，按 §2 安装；或 `workspace` profile 未勾选。
- **不要在运行中 clean**：Kura 运行或调试暂停时不要对 `kura-dev-runtime` 执行 package/clean，工具会拒绝替换正在使用的目录；先停止 Run/Debug。
- **快照与密钥**：数据目录里已有的 snapshot/密钥不会被初始化或 Maven clean 覆盖。
- **GWT**：`kura-management-ui` 保持 Java 11 编译目标，不要提到 21。

详细运行目录/数据导入说明见 `kura-dev-runtime/README.md`。
