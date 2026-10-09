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
| P4 核心迁移 | 待 P3 验收。 |
| P5 Sibling / YOFC | 待 P4 验收。 |
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
mvn -Pmigration-pilot -pl :org.eclipse.kura.core.token.jwt -am test
mvn -Pmigration-pilot,osgi-it -pl :kura-osgi-tests -am verify
```

迁移验证另传 `-Dmaven.repo.local=/absolute/path/to/migration-m2`。该缓存有已记录的旧 runtime 产物，仍不是冷构建证明。P4/P5 尚未执行，生产脚本和其余模块仍处于混合构建期。
