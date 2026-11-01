# 独立 Equinox 开发运行目录

此模块提供完整 workspace 的独立开发运行目录。`runtime.json` 固定现有桌面仿真的 bundle、Maven 坐标和启动级别，Maven 只从仓库收集明确列出的 JAR。它不读取 Eclipse、PDE workspace 或 `.target`。`workspace` profile 聚合约定的所有 sibling 与 YOFC；缺少仓库时 Maven 明确失败。

要求 JDK 21、Maven 3.10（公共入口兼容 3.9）、Python 3.9+。`.run` 沿用 IDEA 当前项目的 Maven 设置；使用隔离仓库时，在 Maven 设置中指定 Local repository，CLI 对应设置 `KURA_MAVEN_REPO`。

```sh
mvn -f build-support/pom.xml install
mvn -Pworkspace -pl :kura-workspace,:kura-dev-runtime -am install -DskipTests -DskipITs
kura-dev-runtime/run.sh --no-build
```

指定隔离缓存时，先将公共 parent/BOM 和所需产物安装到该缓存；然后：

```sh
KURA_MAVEN_REPO=/absolute/path/to/repository kura-dev-runtime/run.sh
```

IDEA 从仓库根 POM 导入，在 Maven 面板启用 `workspace` profile，配置项目 JDK 21，选择共享的 `Kura macOS` 或 `Kura Linux`，点击 Run/Debug。启动前 Maven 组装失败会阻止启动。业务代码由 bundle 自己的类加载器加载，可在激活和业务方法设断点。

共享应用启动配置同时传入 `-DskipTests -DskipITs`：Surefire 和 Failsafe 3.6 分别使用
这两个开关。即使 Maven 面板同时选中了 `osgi-it`，启动前仍只做增量打包。
测试验收另外执行 `mvn -Posgi-it verify` 或 `RUN_TESTS=1 RUN_IT=1 ./build-all.sh`。

## 独立 agent 的 Netplan 网络配置

默认 `none` 继续使用现有仿真运行集。显式选择 `netplan` 时，在相同核心、sibling 和 YOFC
清单上加入 `org.eclipse.kura.management.bridge` 与 `org.eclipse.kura.netplan`，启动前固定
`kura.networking.provider=netplan` 和原网络配置 PID 的外部归属。旧 NM、linux.net、防火墙、
threat manager 不允许同时进入该变体（NM 内含 ModemManager/GNSS 实现）；清单冲突直接失败。
`network-providers.json` 是此选择的来源，Maven 收集两个变体明确列出的 artifact，默认不激活新 provider。

Netplan 运行集位于 `target/runtime-netplan/`，默认数据目录为 `~/.kura-dev/<profile>-netplan`，
与原 `target/runtime/` 及数据目录分开。联调建议指定新的隔离数据目录：

```sh
KURA_DEV_HOME=/absolute/isolated/kura-home \
KURA_MANAGEMENT_SOCKET=/run/kura-management-agent/control.sock \
KURA_MANAGEMENT_AGENT_USER=root \
  mvn -f kura-dev-runtime/pom.xml package \
  -Dmaven.repo.local=/absolute/cache -Dkura.dev.profile=linux -Dkura.dev.network-provider=netplan

KURA_DEV_HOME=/absolute/isolated/kura-home KURA_DEV_NETWORK_PROVIDER=netplan \
  kura-dev-runtime/run.sh --no-build
```

macOS 使用 `-Dkura.dev.profile=macos`，并指定实际 agent socket 和 OS 用户。
`KURA_HTTP_PORT`、`KURA_HTTPS_PORT` 和 `KURA_CLIENT_AUTH_PORT` 同原机制；构建、prepare/run 时
须传入相同环境。`run.sh --network-provider netplan` 也会让前置 Maven 和启动器选择相同变体。
Maven clean 会检查两个运行目录，任一 JVM 运行或暂停时均拒绝清理。

本机桥接默认验证 agent 的 OS 用户 `root`，不使用 Kura Web 账号。agent 侧仍须登记实际 Kura UID；
未配置 `AGENT_KURA_NETWORK_INTERFACES` 时拒绝网络委托，显式空值仅供观测，非空值仅能是已受管接口子集。
启用此 Kura profile 不会修改 Netplan、授予接口管理权或自动停用 NM/cloud-init。
这是明确的开发运行变体；正式 deb 选择、包生命周期及实际发行矩阵另行验收。

`target/runtime/` 内包含 launcher、framework、plugins、生成配置与 `inventory.json`（坐标、bundle 版本、SHA256）。可直接比对清单确认加载来源。停止 Run/Debug 后再执行 package/clean；即使 JVM 暂停在 Jetty 启动之前，工具也拒绝替换正在使用的目录。

用户数据默认保存在 `~/.kura-dev/macos` 或 `~/.kura-dev/linux`，可以设置 `KURA_DEV_HOME`；不允许放在本模块的 target 内。已有 snapshot/密钥不会因初始化或 Maven clean 被覆盖。日志位于数据目录的 `logs/`。

IDEA 应用配置中的环境变量只传给启动的 JVM；`Before launch` 的 `Run Maven Goal`
不会继承其中的 `KURA_DEV_HOME`。使用非默认数据目录时，先在终端显式传入
`KURA_DEV_HOME` 执行上面的 Maven 组装命令，并核对 `target/runtime/jvm.args`
中的 `kura.home`、`kura.data` 和 `kura.snapshots`，然后在个人复制的本地
IDEA 配置中移除运行前 Maven 步骤再启动。不要在应用运行时重组装同一个
`target/runtime`。
隔离的 Mac IDEA 启动与重启验收记录见
[2026-10-10 验收证据](../docs/testing/mac-idea-application-restart-validation-20261010.json)。

支持 `KURA_HTTP_PORT`、`KURA_HTTPS_PORT`、`KURA_CLIENT_AUTH_PORT`（首次默认 8080/8443/8444）。已有 profile 默认沿用快照端口；显式环境变量覆盖会写入编号更大的快照，保留原文件、密钥及其他配置。端口占用会直接报错。初始模板禁止自动连接外部 MQTT，并禁用桌面不具备的时钟、看门狗和 GPS。

CLI 调试可以运行 `python3 kura-dev-runtime/tools/runtime.py run --debug-port 5005`，仅监听本机，等待调试器连接。正常停止使用 Ctrl-C；Gogo `close` 只停框架，旧组件线程可能仍存活。

显式导入旧仿真数据时，先停止旧运行进程。支持包含 `user/snapshots` 的标准 Kura 数据目录，以及 Eclipse 仿真器的 `snapshots/`、`user/security/`、`camel/` 布局。目标必须为空；只复制 user/data、快照及 Camel 路由和脚本，不复制框架缓存、旧 bundle 或 PDE 元数据。旧目录保留不动。快照须为可读 XML；加密快照须先用原环境导出。快照和 Camel 文本中的绝对路径按原数据根目录重定位；从另一台电脑拷贝的目录可额外指定 `--old-home /原电脑/数据目录`。

```sh
KURA_DEV_HOME=/new/isolated/data python3 kura-dev-runtime/tools/runtime.py import-data \
  --source /old/kura-data --old-home /previous/machine/kura-data
```

导入是显式操作，不会在正常构建中自动读取旧 Eclipse 数据。导入后保留原业务配置，启动前请核对连接目标；自动测试和默认全新 profile 使用本地模拟端点。

导入到默认 profile 前，先把已有 `~/.kura-dev/macos` 整体改名备份，再以该路径为目标导入。导入后的布局为：

| 内容 | macOS 默认路径 |
|---|---|
| 配置快照、账户和 Wires 配置 | `~/.kura-dev/macos/user/snapshots/` |
| HTTPS / SSL 密钥库 | `~/.kura-dev/macos/user/security/` |
| Camel 路由和初始化脚本 | `~/.kura-dev/macos/camel/` |
| 数据库及其他运行数据 | `~/.kura-dev/macos/data/` |
| 日志 | `~/.kura-dev/macos/logs/` |

共享的 `Kura macOS` IDEA 配置默认读取此目录，无需修改 `.run`。旧配置若使用 443/4443，可在首次 prepare 时显式映射到开发端口；会生成新快照，不覆盖导入的原快照：

```sh
KURA_HTTP_PORT=8080 KURA_HTTPS_PORT=8443 KURA_CLIENT_AUTH_PORT=8444 \
  python3 kura-dev-runtime/tools/runtime.py prepare --profile macos
```
