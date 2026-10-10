# 新组装 Mac Camel / Vertx 运行集验收

2026-10-11，完整 CI 成功结束后，以干净 core `9ea935469252` checkout
安装已修复的公共 Vertx core 封装，并组装 `macos` 开发运行集。
Maven 3.10.0 / JDK21；运行集直接使用组装产物，**0 生产 overlay、
0 额外生产 bundle**。278 个生产 plugins，加 framework/launcher 为
280 个 inventory entries。

- 六个公共 Vertx bundle 均为 **5.2.1**；22 个 Netty 为 **4.2.19.Final**；
  公共 SnakeYAML Engine **3.0.1** 仅一份，YOFC OPCserver 无私有嵌入 Engine。
- Camel **4.22.1** 的 XML、Java、YAML 实际 SCR 配置/生产路由、独立
  GraalJS JSR-223、Groovy 文件优先级/热更新/内联更新和 context 生命周期通过。
- **16 条真实 MQTT 到达、7 次独立 Vertx HTTP**，真实 cloud PID/名称描述断言保留。
- Camel 与 YOFC 加载同一 Engine Class，YOFC Jackson YAML 中文往返通过。
- 实际 YOFC Vertx EventBus/HTTP 通过；Java21 capability 和 HTTP handler
  `Thread.isVirtual()` 均为 true，公共 core 的 `Multi-Release: true` 已实际加载。
- 清理通过、无强制退出、端口释放；315 个保护文件无变化，个人配置
  33 个文件无新增、删除或修改。SecurityService 实际 provider 数量为 0。

第一次 packaged probe 的失败日志保留：验收 helper 只迁移 template profile，
遗漏运行集声明的另一 kura.home，ownership guard 拒绝后退出。独立 helper
提交 `53c7c7ae` 修复 home 识别和迁移，保留 guard；实际重跑通过。
这不是生产打包缺陷。当前 helper 四个源码文件已归档并逐个核对 SHA256。

见 [JSON](mac-packaged-camel-vertx-validation-20261011.json)。本轮没有重复
浏览器保存；[升级后的独立 ACE 证据](mac-complete-camel-custom-dsl-browser-validation-20261011.md)
为 17 MQTT / 8 HTTP。结果不互相累加或计入 workspace JUnit 总数。
installed Debian、外部安全策略 provider、硬件/GPU 与部署网关保持未验证。

个人保护比较覆盖 33 个配置、快照、脚本和密钥文件；与原基线一致排除 logs。
四个现有日志的修改时间均早于基线，未清理。最终推送后再次核对保护范围，
无变化。
