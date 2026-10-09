# Maven 构建的第三方 OSGi 封装

默认构建 14 个明确的兼容 artifact，清单在 `catalog.json`：12 个当前桌面运行需要的封装，以及两个保留外部消费者的 DigitalPetri artifact。Milo 保持 1.1.2，与 YOFC 私有嵌入的 1.1.4 分开。

每个模块从 Maven 获取明确的上游 JAR，只解包该 artifact，使用 Maven Bundle Plugin 6.0.0 与审查过的元数据模板重新打包。不会嵌入传递依赖，不解析 P2，不修改业务模块源 MANIFEST。原有 `p2.osgi.bundle` GAV 和 bundle 数字版本保持兼容。

模板来自旧封装产物。无版本导入使用 MBP 的 `version=!` 指令，阻止插件推导出新的范围；该指令在最终 MANIFEST 中消失。`-nodefaultversion` 阻止无版本导出被自动赋予 bundle 版本。Vert.x Core 禁用自动多版本元数据生成，与旧运行包行为一致。

14 个产物已逐个对比旧 JAR：包范围、能力、资源、命名类均相同。只允许构建工具字段和非 OSGi 的 `Private-Package` 工具说明变化；包导入/导出仍逐项严格检查。

旧 P2 的其他兼容输出还保留在原 target-platform 目录，尚未执行 P7 清理。不能将这 14 个模块误认为原 P2 站点所有外部消费者的完整清单；清理前仍需逐项核对。当前默认开发运行只需要这组封装。
