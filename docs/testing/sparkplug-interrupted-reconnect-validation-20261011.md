# Sparkplug 连接等待中断修复与验收 — 2026-10-11

交接计划要求先确认 interrupted reconnect 差异是否适用。官方固定版本
[e500a68d](https://github.com/eclipse-kura/kura/blob/e500a68d7b3f4a970aca3e13c038947269278827/kura/org.eclipse.kura.cloudconnection.sparkplug.mqtt.provider/src/main/java/org/eclipse/kura/cloudconnection/sparkplug/mqtt/transport/SparkplugMqttClient.java)
在恢复中断标志后抛出连接异常；fork 原实现继续创建 Paho 客户端。

使用真实 Moquette/Paho 连接和自有虚拟线程复现三种场景：首次连接前已中断、
真实断连后重连前已中断、生产 `Thread.sleep` 等待期间中断。
修正测试清理后，旧生产代码 **3 失败、0 错误**；初次清理错误单独保留。

修复在恢复中断标志后立即抛出 `KuraConnectException`，保留中断原因，
停止创建或替换 Paho 客户端。生产提交 `817b5a37d08b`，测试提交
`2fc64e91eb32`，两者分别提交。

## 验证结果

| 范围 | 测试调用 | 失败 / 错误 / 跳过 |
| --- | ---: | --- |
| 完整 Sparkplug 模块 Maven install | 155 | 0 / 0 / 0 |
| 真实 Equinox/SCR 云运行时 | 13 | 0 / 0 / 0 |
| 原生 IDEA Current File Run | 3 | 0 / 0 / 0 |

Maven 3.10.0、Temurin JDK21、JUnit5。IDEA 正常退出，3/3 用时 4.975 秒，
classpath 使用当前模块 `target/classes` 和 `target/test-classes`，无新增 Debug 结论。

模块产物、migration-m2 安装产物及容器 `it-bundles` 的 Sparkplug JAR
SHA256 均为 `c2bccde6aee93fdf5a3a4dafaf5daa86abb963a67a2034828cdc6e403d79c6cb`。
IDEA 编译类与上述 JAR 内修复类也匹配。容器 13 项覆盖 WSS 文件密钥库、
证书正反路径、持久化重启、Sparkplug/REST/工厂正常行为；中断行为本身由新增
3 项模块/IDEA 测试验证。7 个 runtime helper/配置与上一轮一致并重新归档。

## 证据范围

[JSON](sparkplug-interrupted-reconnect-validation-20261011.json) 记录源码、提交、
报告、截图及哈希。原始归档位于
`/Users/heyoulin/iot-kura-develop/migration-baseline/sparkplug-interrupted-reconnect-20261011`。

较早 5,521 次调用的完整 CI 固定提交未包含此生产修复及新增测试；本轮是对应
修改的模块、真实容器和 IDEA 验证。各组调用存在重叠，不相加。
此前 callback 空消息/NDEATH 修复保持独立历史范围。

API、手写 OSGi 元数据、cloud PID/名称描述、网络 D-Bus Update/Activate 和
快照行为未改。不追加 Linux/硬件或 YOFC/PLC4X 测试，不清理原运行集/个人配置。
inventory 仍为 **465 reviewed、0 unreviewed、0 deferredScenarios、31 deferredValidation**；
外部实现、部署包和硬件边界继续保留，整体恢复未完成。
