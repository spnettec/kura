# 独立 Equinox 开发运行目录

此模块提供完整 workspace 的独立开发运行目录。`runtime.json` 固定现有桌面仿真的 bundle、Maven 坐标和启动级别，Maven 只从仓库收集明确列出的 JAR。它不读取 Eclipse、PDE workspace 或 `.target`。`workspace` profile 聚合约定的所有 sibling 与 YOFC；缺少仓库时 Maven 明确失败。

要求 JDK 21、Maven 3.10（公共入口兼容 3.9）、Python 3.9+。`.run` 沿用 IDEA 当前项目的 Maven 设置；使用隔离仓库时，在 Maven 设置中指定 Local repository，CLI 对应设置 `KURA_MAVEN_REPO`。

```sh
mvn -f build-support/pom.xml install
mvn -Pworkspace -pl :kura-workspace,:kura-dev-runtime -am install -DskipTests
kura-dev-runtime/run.sh --no-build
```

指定隔离缓存时，先将公共 parent/BOM 和所需产物安装到该缓存；然后：

```sh
KURA_MAVEN_REPO=/absolute/path/to/repository kura-dev-runtime/run.sh
```

IDEA 从仓库根 POM 导入，在 Maven 面板启用 `workspace` profile，配置项目 JDK 21，选择共享的 `Kura macOS` 或 `Kura Linux`，点击 Run/Debug。启动前 Maven 组装失败会阻止启动。业务代码由 bundle 自己的类加载器加载，可在激活和业务方法设断点。

`target/runtime/` 内包含 launcher、framework、plugins、生成配置与 `inventory.json`（坐标、bundle 版本、SHA256）。可直接比对清单确认加载来源。停止 Run/Debug 后再执行 package/clean；即使 JVM 暂停在 Jetty 启动之前，工具也拒绝替换正在使用的目录。

用户数据默认保存在 `~/.kura-dev/macos` 或 `~/.kura-dev/linux`，可以设置 `KURA_DEV_HOME`；不允许放在本模块的 target 内。已有 snapshot/密钥不会因初始化或 Maven clean 被覆盖。日志位于数据目录的 `logs/`。

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
