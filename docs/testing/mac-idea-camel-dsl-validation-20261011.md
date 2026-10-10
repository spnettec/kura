# Mac IDEA 直接运行 Camel 三种 DSL

2026-10-11，用户解锁后，在 `kura-camel` 的实际 IDEA 项目中同步 Maven，
打开 `ForkDslRoutesProviderTest` 并直接 Run 当前文件：
**XML、Java、YAML 共 3/3 通过，0 失败、0 错误、0 跳过，退出码 0**。
耗时 1.283 秒。

IDEA 控制台 classpath/启动命令已确认 Temurin JDK21、JUnit5 runner、
Camel **4.22.1** 与 SnakeYAML Engine **3.0.1**。测试源码 SHA256 与当前
文件一致；AX 控制台文本、截图和源码均已保存并核对哈希。
见 [JSON](mac-idea-camel-dsl-validation-20261011.json)。

这次直接 IDEA Run 与 Maven 58 次 Camel 调用分别记录；不相加。
没有新增 DSL Debug 验收结论；原 Sparkplug/application Run/Debug/restart
证据保持原测试与提交范围。installed Debian 和部署环境边界仍待验证。
