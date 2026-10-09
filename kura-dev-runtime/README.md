# 独立 Equinox 开发运行目录

此模块处于 P2/P3 迁移试点。`runtime.json` 固定现有桌面仿真的 bundle、Maven 坐标和启动级别，Maven 只从仓库收集明确列出的 JAR。它不读取 Eclipse、PDE workspace 或 `.target`。尚未迁移的 bundle 仍须先由原构建安装。

要求 JDK 21、Maven 3.10（公共入口兼容 3.9）、Python 3.9+。当前试点的 `.run` 使用工作空间外 `../../migration-m2`；它明确包含旧产物，不能用作 P6 冷构建证据。

```sh
mvn -f build-support/pom.xml install
mvn -f kura-dev-runtime/pom.xml package
kura-dev-runtime/run.sh --no-build
```

指定隔离缓存时，先将公共 parent/BOM 和所需产物安装到该缓存；然后：

```sh
KURA_MAVEN_REPO=/absolute/path/to/repository kura-dev-runtime/run.sh
```

IDEA 从仓库根 POM 导入，配置项目 JDK 21，选择共享的 `Kura macOS` 或 `Kura Linux`，点击 Run/Debug。启动前 Maven 组装失败会阻止启动。业务代码由 bundle 自己的类加载器加载，可在激活和业务方法设断点。

`target/runtime/` 内包含 launcher、framework、plugins、生成配置与 `inventory.json`（坐标、bundle 版本、SHA256）。可直接比对清单确认加载来源。停止 Run/Debug 后再执行 package/clean；即使 JVM 暂停在 Jetty 启动之前，工具也拒绝替换正在使用的目录。

用户数据默认保存在 `~/.kura-dev/macos` 或 `~/.kura-dev/linux`，可以设置 `KURA_DEV_HOME`；不允许放在本模块的 target 内。已有 snapshot/密钥不会因初始化或 Maven clean 被覆盖。日志位于数据目录的 `logs/`。

首次初始化支持 `KURA_HTTP_PORT`、`KURA_HTTPS_PORT`、`KURA_CLIENT_AUTH_PORT`（默认 8080/8443/8444）。已有配置的端口调整和显式 Eclipse 数据导入尚在实现中；此试点请使用新 profile 数据目录验证其他端口。端口占用会直接报错。初始模板禁止自动连接外部 MQTT，并禁用桌面不具备的时钟、看门狗和 GPS。

CLI 调试可以运行 `python3 kura-dev-runtime/tools/runtime.py run --debug-port 5005`，仅监听本机，等待调试器连接。正常停止使用 Ctrl-C；Gogo `close` 只停框架，旧组件线程可能仍存活。
