# Camel / Vertx 升级及公共 OSGi 封装

2026-10-11，当前 fork 版本变更：

| 依赖 | 原版本 | 当前版本 |
| --- | --- | --- |
| Camel | 4.20.0 | 4.22.1 |
| 公共及 YOFC 专用 Vertx | 5.1.4 | 5.2.1 |
| 配套 Netty | 4.2.16.Final | 4.2.19.Final |
| 公共 SnakeYAML Engine | YOFC 私有嵌入 | 3.0.1 独立 bundle |

Camel 官方列出 4.22.1 为当前 LTS，支持 Java21。
4.20.0 属于 [CVE-2026-42527](https://camel.apache.org/security/CVE-2026-42527.html)
影响版本；该问题取决于官方列出的 Java 序列化使用条件，4.22.1 包含修复。
依据：[官方发布说明](https://camel.apache.org/blog/2026/09/RELEASE-4.22.1/)、
[支持版本](https://camel.apache.org/download/)。此升级不构成“应用无漏洞”的结论。

Vertx 官方 5.2.1 于 2026-10-08 发布，配套 Netty 4.2.19.Final；
包含 HTTP、SSL、认证等修复。
依据：[5.2.1 发布说明](https://vertx.io/blog/eclipse-vert-x-5-2-1/)、
[5.2 更新说明](https://vertx.io/blog/whats-new-in-vert-x-5-2/)。
官方 Central POM 和 metadata 的归档见 JSON companion。

## 公共与 YOFC 打包

六个公共 bundle 仍使用 `p2.osgi.bundle` 坐标和原 BSN：
`io.vertx.core`、`core-logging`、`uri-template`、`web-common`、
`auth-common`、`web-client`。原手写 Import/Export 和其他元数据保留，
MANIFEST 更新 Bundle-Version；公共 core 另单独恢复缺失的 `Multi-Release: true`。
普通 Maven 使用现有 Maven Bundle Plugin
6.0.0 封装；P2 兼容入口保留 Reficio，并同步版本属性。本轮已构建并实际加载
普通 Maven 的六个公共封装，旧 Tycho/PDE 发布链没有单独验收记录。

YOFC 专用 auth/bridge/MQTT/web/SQL 等库仍沿用 `com.yofc.iot.runtime`
嵌入布局。核心 BOM、运行集、发行包、P2 兼容配置、Camel 和 yofc-iot 版本同步。
SnakeYAML Engine 使用其官方 OSGi bundle，公共提供给 Camel 和 YOFC。

Vertx 5.2 删除 `VirtualThreadSupport`，使 YOFC 首次编译失败。
生产兼容修复改用 `VertxInternal.isVirtualThreadAvailable()`，与当前 Vertx
部署能力检查一致。保留 VIRTUAL_THREAD / WORKER 选择和原 HTTP 行为。
最初实际 OSGi 实例返回 false。进一步核对发现，旧版和新版公共封装都保留了
`META-INF/versions/21` 类，却遗漏 Multi-Release 标记，因此加载旧 JDK 实现。
单独修复此属性及匹配的 Reficio P2 instruction 后，JAR 内容只有 manifest
变化，Java21 能力为 true，YOFC 真实 HTTP handler 已在虚拟线程运行。
官方实现依据：[Java21 JdkDependent](https://raw.githubusercontent.com/eclipse-vertx/vert.x/5.2.1/vertx-core/src/main/java21/io/vertx/core/impl/JdkDependent.java)。

## 已执行的验证

- Maven 3.10.0 / JDK21：六个公共封装、完整 Camel bundles/发行包、YOFC runtime
  和 yofc-iot 全模块构建通过。Camel 58 次 Jupiter 调用全部通过。
- 新隔离配置替换 39 个生产 artifact，并加载公共 Engine；XML/Java/YAML、
  JavaScript、定制 ACE 编辑保存、真实 MQTT/Vertx HTTP、YOFC EventBus/HTTP
  和公共 YAML class identity 通过。含浏览器的一轮为 17 MQTT / 8 独立 HTTP。
- Multi-Release 修复后单独重复实际运行路径：16 MQTT / 7 HTTP，包含真实
  YOFC 虚拟线程 HTTP；原 17 / 8 的浏览器运行作为独立 UI 证据保留。
- 无强制退出，端口释放，315 个受保护文件哈希未变。

见[实际运行证据](mac-complete-camel-custom-dsl-browser-validation-20261011.md)
和 [JSON companion](camel-vertx-upgrade-validation-20261011.json)。完整 workspace
门禁已通过：5,521 次调用，0 失败/错误，9 跳过，409 份报告与测试源码
匹配。14 个隔离 clone 使用主要升级的固定提交，后续 manifest-only
修复和 opt-in helper 有独立的新组装运行集证据，见
[本轮 CI 范围](current-workspace-ci-validation-20261011.md)。
2026-10-10 的
5515 次调用保留为历史证据。Groovy、Jackson、官方 OPC UA 和 PLC4X 保持原范围。

最新 [新组装运行集](mac-packaged-camel-vertx-validation-20261011.md) 直接加载
升级产物，0 生产 overlay、0 额外生产 bundle：16 MQTT / 7 HTTP 及实际
YOFC 虚拟线程通过。[直接 IDEA DSL Run](mac-idea-camel-dsl-validation-20261011.md)
为 XML、Java、YAML 3/3，JUnit5 / JDK21。两者不累加到 workspace 总数。
