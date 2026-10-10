# 完整 Mac Camel fork 验收

2026-10-11；Maven 3.10.0、JDK21，完整 Mac 应用、独立认证 MQTT broker
和独立 HTTP responder。实际生产 Camel **4.20.0**、Kapua cloud stack、
ConfigurationService/SCR、Groovy、Vertx WebClient、registry/rebind 和文件 watcher
执行；没有替换成上游 router。

通过的实际消息与脚本行为：

- **9 条 MQTT 到达**：KuraPayload metric/body、中文 String、二进制 byte[]、
  两次外部云消息回调，以及四次脚本处理后的发送；QoS1、非 retained，独立
  observer 验证内容、nonce 和主题。
- **4 次 Vertx HTTP 请求**：实际 Groovy 脚本使用注入的 webClient 和 vertx，
  响应正文进入同一批云消息。
- initCode.file 优先于内联值；修改文件在原 CamelContext 上重绑脚本；
  内联脚本配置更新停止并替换旧 context；相同配置保留 context，改变 XML
  停止并替换旧 context。
- cloud PID、中文名称及描述保持 fork 行为。
- owned router、watcher、cloud stack 和 JVM 清理通过，端口释放，无强制退出。
  279 个运行集 artifact、33 个个人受保护文件及模板密钥库/日志哈希未变。

首轮 fixture 使用静态 `<process ref>`，路由保留原 Processor，导致热更新
断言失败。已改为稳定 dispatcher 对每条 Exchange 查询当前 registry，实际
生产 rebind/watcher 随后通过；没有生产代码修复。失败日志和退出证据保留。

本轮内联更新通过 ConfigurationService，**未执行浏览器 ACE 编辑保存**。
实际 JavaScript init 执行、修改后的控制台编辑/保存及 installed Debian 包
边界仍明确保留；不新增 Linux 验证。完整应用观察到 SecurityService provider
数量为 0，符合上游仅提供 API/REST 扩展点的核查。

见 JSON companion 的源文件/artifact 哈希和 archive。本轮 9 次消息/4 次 HTTP
验收不叠加到已有 5515 次 JUnit 统计。当前仍有 31 条 deferredValidation，
不宣告整体恢复完成。
