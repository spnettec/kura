# 定制 Camel 脚本、三种 DSL 与控制台验收

2026-10-11，macOS arm64、Maven 3.10.0、Temurin JDK21、JUnit5。
以本 fork 的脚本、Vertx、OSGi 和控制台行为为准。

## 修复与公共依赖

- GraalJS JSR-223 引擎由独立 bundle 提供。Camel consumer 的 host interop
  和公开 ScriptRebind 已修复，实际 JavaScript 调用和 registry 重绑通过。
- 实际 YAML 路由暴露了缺失的 `camel-yaml-dsl-common`、
  `camel-yaml-dsl-deserializers` 和 SnakeYAML Engine 类加载问题。
  两个 Camel DSL 库保持原嵌入布局；Engine **3.0.1** 提升为公共
  `org.snakeyaml.engine` bundle，Camel 显式导入，YOFC OPC UA server 使用
  provided 依赖。实际两个消费者加载同一个 Class，YOFC Jackson YAML 中文
  read/write round trip 通过。
- 英文名称为 **Camel Router**，中文为 **Camel 路由器**；描述列出
  XML、Java、YAML。保留原 PID、类名、配置键和动态 ACE editor 标记。
  本次只修改并验收英文、简体中文。

## 当前升级版本的实际结果

Camel **4.22.1**、公共封装及 YOFC 专用 Vertx **5.2.1**、Netty
**4.2.19.Final**。恢复的断言和新增定制测试合计 **58 次 Jupiter 调用**，
零失败、零错误、零跳过。此前 IDEA 9/9 是其原版本的独立证据。

三次升级后的完整隔离 Mac 应用运行分别通过：

| 运行 | MQTT 到达 | 独立 Vertx HTTP | 实际 ACE 编辑保存 |
| --- | ---: | ---: | --- |
| 三种 DSL、JavaScript、公共 Engine、YOFC Vertx | 16 | 7 | 未执行 |
| 同上，加实际浏览器脚本编辑保存 | 17 | 8 | 通过 |
| 修复公共 core 的 Multi-Release 标记，实际虚拟线程 HTTP | 16 | 7 | 沿用前一轮独立 UI 证据 |

这些运行重叠，数量不相加，也不计入 JUnit 总数。真实生产 cloud stack 的
外部消费回调、KuraPayload、中文 String、byte[]、QoS1、主题及消息 nonce
均由独立认证 broker/observer 检查。Groovy 文件优先级、同 context 热重绑、
内联配置更新、相同配置保留 context、改变路由停止并替换 context 通过。
Java/YAML 通过真实 SCR 配置切换，分别执行生产、脚本及外部 MQTT 回调路径。
cloud PID、中文名称和描述断言保留。

升级后的中文控制台实际切换 JavaScript → Groovy，在 ACE 粘贴脚本，点击
验证（未发现错误）、应用并确认。保存后重新加载的脚本内容和禁用的应用
按钮已观察；随后真实 Vertx/MQTT 消息验证新脚本执行。英文/中文名称还有
独立双语 UI 截图证据。

YOFC 的实际 OSGi Vertx 服务完成 EventBus request/reply 和真实 HTTP 请求。
前两轮因公共封装遗漏 Multi-Release 标记而返回 false，执行 Worker 回退。
恢复这一标记后，JDK21 实际加载版本化实现，能力检测为 true，真实 HTTP handler
的 `Thread.isVirtual()` 也为 true。后续探针要求这一能力，避免再把错误的
Worker 回退当作完整 Java21 支持通过。

所有 owned JVM、router、cloud stack、broker 清理通过，端口释放，无强制退出。
原运行集、个人配置和模板密钥库/日志的 **315 个受保护文件哈希未变**。

## 证据与剩余边界

[JSON 证据](mac-complete-camel-custom-dsl-browser-validation-20261011.json)
记录六次独立运行的结果、源码/产物哈希及截图；失败 fixture 和生产问题的
原始日志保留在归档中。[升级记录](camel-vertx-upgrade-validation-20261011.md)
说明官方版本依据、公共封装及兼容修复。

inventory 248–252 的 JavaScript 和 ACE 子边界已关闭，只保留 installed
Debian sibling package 验收。当前仍为 **465 条 reviewed、0 unreviewed、
0 deferredScenarios、31 条 deferredValidation**。外部 SecurityService provider、
Linux/NetworkManager、硬件/GPU 和部署网关边界保持未验证，整体恢复仍在进行。
