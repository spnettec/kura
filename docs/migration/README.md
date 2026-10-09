# Maven Bundle Plugin / IDEA 迁移实施记录

本分支按 P0–P7 分阶段迁移。**目前默认生产构建仍由 `build-all.sh` 的旧链执行，根 POM 是迁移入口，尚未完成切换。** 不将构建支持安装成功当作完整迁移完成。

## 已冻结的约束

- Maven 3.10 / JDK 21；management-ui 的 Java 11 编译例外保留。
- Maven Bundle Plugin 6.0.0；手写 MANIFEST、DS/metatype XML、嵌入路径和业务源码保留。
- sibling 保持独立仓库和交付物；PLC4X 从源码构建是显式前置步骤。
- JUnit 5 单测、Sling Mock 组件测试、真实 Equinox 集成测试分层执行。
- macOS/Linux 独立运行；开发数据置于 `~/.kura-dev/<profile>`，与 `target` 分离。
- 构建转换不改变 YOFC 的 i18n、已删除功能、Jackson/Milo 外部消费者边界。

## 阶段状态

| 阶段 | 状态 / 门槛 |
|---|---|
| P0 基线 | 已记录 16 仓库 SHA，保存 109 个现有 bundle 副本及元数据；docs 已通过旧 Tycho 链补齐。已通过独立启动补充运行基线。 |
| P1 构建基础 | parent/BOM 已在独立缓存由 Maven 3.10 安装成功，无 MILD；封装映射和测试组合仍在验证。 |
| P2 IDEA 启动试点 | macOS 试点通过：完整运行集解析、管理页 HTTP 200、激活与配置读取断点/单步、停止后重启通过；仍使用旧构建产物。 |
| P3 代表模块 | 试点通过：5 个 bundle 语义对比、14 项普通测试、6 项真实容器测试，以及替换新 JAR 后的完整运行验证。 |
| P4 核心迁移 | 已通过：51 个默认 bundle + docs；22 项普通测试、6 项真实容器测试及新核心运行验证。 |
| P5 Sibling / YOFC | 47 个原 Tycho sibling bundle 与 YOFC runtime 的构建、语义对比通过；YOFC / workspace 联调中。 |
| P6 交付与平台回归 | 待迁移；包括空缓存、双架构容器运行及双平台断点。 |
| P7 清理切换 | 最后执行；目前不删除旧 `.target`、`.launch` 或 Tycho 配置。 |

## 基线与回退

`baseline-20261009.json` 记录仓库 revision、artifact SHA256 和基线缺口。完整 JAR、MANIFEST、资源逐项 hash 和源码配置备份保存在本机工作空间外：

```
/Users/heyoulin/iot-kura-develop/migration-baselines/20261009-maven-bundle-complete/
```

该目录是本机回退资料，不是构建输入；迁移脚本不能依赖它。可在其他机器重新执行：

```bash
python3 tools/migration/capture_baseline.py --workspace /path/to/git \
  --output /path/outside/checkouts/baseline --report /path/to/baseline.json
python3 tools/migration/bundle_audit.py /path/to/new.jar --baseline /path/to/old.jar
```

比较允许构建标识及 Bundle-Version qualifier 变化；Import/Export/DS/fragment/资源/嵌入 JAR 的任何变化都使比较失败，需逐项审查。ECJ 与 javac 的 class 字节差异不当作资源缺失，另由编译、业务测试和真实 OSGi 类加载验证。

迁移验证缓存为 `/Users/heyoulin/iot-kura-develop/migration-m2`。P2 允许显式导入旧产物作启动试点；P6 必须使用另一个真正空的缓存并从 PLC4X 源码开始，不能把试点缓存当作冷构建证明。

## 已知基线问题

- Eclipse 生效配置含 277 个 bundle 条目。`org.eclipse.kura.docs` 原未打包，已通过旧构建的 `-Pjavadocs -pl org.eclipse.kura.docs -am install` 补齐（保留 MILD 仅用于此旧链）。
- Linux 的旧 `.launch` 含已删除的 Bluetooth 和旧测试模块；以当前桌面功能和硬件排除规则建立可审查的 Linux 清单，不复制这些失效模块。
- 项目知识 vault 未注册；代码图谱 MCP 连接返回 `Transport closed`，已通过同一工具的本地 CLI 恢复符号查询。

## P2 启动和调试试点（2026-10-09）

- Maven 3.10 / JDK 21 在隔离缓存完成 `kura-dev-runtime clean package`，无 Tycho/MILD。
- 277 个清单 bundle：269 ACTIVE、8 RESOLVED（含 fragment），无 INSTALLED 未解析 bundle。框架单独计数。
- HTTP 跳转后的管理页面返回 200；8080、8443、8444 均监听。WebConsole、WireGraph 和配置服务 ACTIVE。
- Eclipse 关闭时，IDEA 2026.2.3 使用共享 `Kura macOS.run.xml` 启动真实 Equinox。
- 命中 `Emulator.activate:47`，F8 单步至 50，能查看 SCR ComponentContext。
- Gogo 通过真实 ConfigurationService 调用配置查询，命中 `ConfigurationServiceImpl.getComponentConfigurationInternal:942`，F8 至 943；能查看 PID、实例和跨 bundle 调用栈。
- IDEA Stop 后 JVM 退出，端口释放；第二次 Debug 启动成功。Maven clean 后独立数据目录和既有 snapshot 保留。
- IDEA 的启动前任务在试点中只组装已安装 JAR；P5 才改成完整 workspace 增量构建。当前核心源码尚未全部导入为 Maven 模块，不能把试点当作最终 IDE 验收。
- Linux GUI、Docker 双架构运行、冷 Maven 仓库尚未验收。

旧 Gogo `close` 命令可停止 framework 并释放端口，但旧 bundle 的工作线程使 JVM 未退出；IDEA Stop / SIGTERM 可以正常退出。线程现场留在本机基线目录。该行为不是新构建已修复的项目。

## P3 代表模块（2026-10-09）

已转换 API、JWT、localization、localization.resources fragment、emulator。业务源码、原 MANIFEST、DS 和 metatype XML 均未修改。嵌入依赖进入 target/classes/lib，打包路径与基线一致。

- Maven 3.10 / JDK 21 / MBP 6.0.0，无 MILD，固定 qualifier `20261009pilot`。
- 5 个 JAR 的所有业务 headers、非 class 资源和命名类清单与冻结基线一致。允许包声明排序/空白、默认 Bundle-ClassPath `.` 的等价表示，以及构建标识变化。
- 每次打包在 target/osgi 中生成带统一 qualifier 的 MANIFEST 副本；源 MANIFEST 保持不变。
- JUnit 5.14.4、Mockito 5.24.0、Sling OSGi Mock 3.5.8、Surefire/Failsafe 3.6.0 已实际运行：14 项普通测试、6 项真实 Equinox 测试通过。
- 真实测试覆盖 configuration-policy=require、配置更新、注册 PID、实际 API 包提供者、动态 keystore 绑定/解绑、嵌入类加载和 localization fragment 附着。
- 四类负向 fixture 均能被发现：错误导入范围、缺少嵌入 JAR、缺少 DS 描述符、缺少必需引用。
- 本地化中文缺少注解时返回 `AssetMessages.activating`，已用冻结旧 JAR 单独复现，测试保留该行为，不改变 i18n 设计。
- 完整仿真加载这 5 个新 JAR，版本和 SHA 清单已核对：269 ACTIVE、8 RESOLVED、框架 STARTING，无 INSTALLED；管理页 HTTP 200。Ctrl-C 正常退出并释放端口。

测试当前入口：

```sh
mvn -pl :org.eclipse.kura.core.token.jwt -am test
mvn -Posgi-it -pl :kura-osgi-tests -am verify
```

迁移验证另传 `-Dmaven.repo.local=/absolute/path/to/migration-m2`。该缓存有已记录的旧 runtime 产物，仍不是冷构建证明。P4 已完成，P5 正在推进；生产脚本和 sibling 仍处于混合构建期。


## P4 核心普通 Maven 构建（2026-10-09）

默认根 POM 聚合公共构建支持与核心。`-Posgi-it` 加入容器测试；`-Pdev-runtime` 暂时组装已安装的完整运行集，P5 完成后由 workspace profile 取代。

- 51 个默认 bundle 与可选 docs bundle 全部转换，52 个产物的语义对比通过。生产 Java、源 MANIFEST、DS/metatype XML 没有改动。
- 保留 script.provider 的 27 个私有嵌入依赖（包括原 Graal/私有 Bouncy Castle 版本）、根目录路径及 SPI 声明；Linux native fragment 内容不变。
- 关闭 MBP 的自动导入版本范围、contract 和默认导出版本推导；保留手写声明。属性顺序及 token 引号的等价表示由审计工具规范化，版本范围和 mandatory/optional 变化仍会失败。
- Maven 3.10 / JDK 21、无 MILD：22 项普通测试（JWT 14、快照 4、XML 4），6 项真实 Equinox 测试通过。
- 快照测试检查默认加密、显式开关、损坏最新快照保留为 `.bad` 并回退旧快照；XML 测试检查 DOM/流式 CDATA 与数组类型往返。
- 固定 qualifier `20261009core`；完整仿真实际加载 44 个新核心产物，其余硬件 bundle 不在桌面清单中。269 ACTIVE、8 RESOLVED，无 INSTALLED、ERROR 或类加载异常；管理页面 HTTP 200，Ctrl-C 后退出。
- 文档 bundle 的冻结旧产物只有 MANIFEST 和许可文件；新构建保留相同内容，没有把原本未进入 JAR 的 javadoc 当作已有资源。
- 14 个第三方封装均可从原始 Maven JAR 重新构建，保留 p2.osgi.bundle 坐标及 Milo/DigitalPetri 外部兼容输出，产物语义对比通过。

```sh
mvn clean install
mvn -Pjavadocs,osgi-it install
```

本阶段仍使用有记录的迁移缓存；冷仓库、发行包、Linux GUI 与 Docker 验收不包含在上述结果中。

## P5 Sibling 转换（2026-10-09）

四批共 47 个 bundle 已由 Maven 3.10 / JDK 21 / MBP 6.0.0 构建通过，未使用 MILD。每个产物与冻结基线比较：包范围、服务声明、嵌入 JAR、许可资源、命名类清单一致；各仓库 `.deb` / 已有 `.dp` 中直接业务 bundle 的 SHA256 与本次产物一致。此项是包内容检查，尚不等于安装/卸载或容器运行验收。

- position/opcua/deployment：7 个；GPSD 沿用 kura-addons 的原 Maven 坐标。
- networking/wires/cloud：29 个；保留 NM 根目录及 lib 双份嵌入布局，少数已有注解组件单独生成 XML，禁止覆盖手写描述符。Sparkplug 生成源码统一留在 target。
- camel/artemis/container：9 个；保留 Camel/Artemis 根目录及 lib 布局、Container docker-java 3.2.12 和私有依赖。Artemis 使用处理后的原 MANIFEST 控制最终导出，防止嵌入 JAR 注解扩大导出面。
- triton/management-ui：2 个；Triton 保留 protobuf/gRPC 及 9 个 lib 依赖。Web2 使用 Java 11 编译、JDK 21 构建，GWT 两个模块显式列出，生成页面资源逐字节一致；5 个 Console 测试转为普通 JUnit 5 后通过。旧产物额外包含的 JakartaServlet 6 contract 由构建步骤明确保留。
- `kura-yofc-runtime` 继续自动 MANIFEST 模式，独立构建与产物对比通过。显式保留原 Jackson `[2.21,3)` 可选导入范围，公共 BOM 不收紧其运行兼容范围。

所有下载和生成内容均位于 target；手写源 MANIFEST、DS/metatype、生产 Java 未因以上转换改写。YOFC 的统一入口、完整 workspace 增量运行集仍在验证，不能据此宣布 P5 完成。
