# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Eclipse Kura 是一个面向 **IoT/边缘网关** 的 Java/OSGi 框架，版本 `6.0.0-SNAPSHOT`。不是单体应用，而是一个模块化边缘运行时平台。

## 构建命令

### 完整构建（三步顺序）

```bash
# 1. 构建目标平台（依赖基础）
mvn -f target-platform/pom.xml clean install

# 2. 构建核心模块
mvn -f kura/pom.xml clean install

# 3. 构建发行包（多架构安装/Docker 镜像）
mvn -f kura/distrib/pom.xml clean install -DbuildAll
```

或使用一键脚本：
```bash
./build-all.sh          # 跳过测试（默认）
RUN_TESTS=1 ./build-all.sh  # 包含测试
```

### 跳过测试
```bash
mvn -f kura/pom.xml clean install -Dmaven.test.skip=true
```

### 构建特定 Profile（Docker/目标架构）
```bash
mvn -f kura/distrib/pom.xml help:all-profiles  # 列出所有可用 profile
mvn -f kura/distrib/pom.xml clean install -Paarch64  # 仅构建 aarch64
mvn -f kura/distrib/pom.xml clean install -DbuildAllContainers  # 构建 Docker 容器
```

### 运行测试
```bash
mvn -f kura/pom.xml test  # 运行所有测试
mvn -f <module>/pom.xml test  # 运行特定模块测试
```

### 代码检查
```bash
mvn checkstyle:check  # Checkstyle 检查
```

## 环境要求

- **JDK 17**（注意：`org.eclipse.kura.web2` 模块使用 Java 11 编译目标）
- **Maven 3.9.x**
- **Docker/Podman**（仅构建容器时需要）

## 架构分层

```
target-platform/   → 依赖管理、P2 仓库、第三方 OSGi 化
kura/              → 核心平台源码
  ├── org.eclipse.kura.api          → 公共 API 接口
  ├── org.eclipse.kura.core*        → 核心服务（配置、网络、身份、系统等）
  ├── org.eclipse.kura.linux*       → Linux 系统适配（GPIO、USB、网络等）
  ├── org.eclipse.kura.nm           → NetworkManager 集成
  ├── org.eclipse.kura.driver.*     → 设备驱动（OPC UA、S7 PLC 等）
  ├── org.eclipse.kura.wire.*       → Wires 数据流编排系统
  ├── org.eclipse.kura.cloudconnection.* → 云连接器（MQTT、Sparkplug 等）
  ├── org.eclipse.kura.rest.*       → REST API 暴露层
  ├── org.eclipse.kura.web2         → GWT Web 管理控制台
  ├── org.eclipse.kura.container*   → 容器编排（Docker/Podman）
  └── org.eclipse.kura.ai.*         → 边缘 AI（Triton Server）
kura/features/     → 功能集合打包（eclipse-feature）
kura/distrib/      → 发行包（aarch64/x86_64、Docker 镜像、安装脚本）
kura/emulator/     → 本地仿真调试环境
kura/tools/        → 工具（含 kura-addon-archetype 扩展模板）
```

## 关键设计原则

- **OSGi Bundle 是基本交付单元**，不是 JAR/WAR。模块 packaging 为 `eclipse-plugin` 或 `eclipse-feature`
- **构建依赖 Tycho**，不是标准 Maven 打包。理解 Tycho/P2/Feature 的关系很重要
- **API 与实现分离**：开发插件时应依赖 `org.eclipse.kura.api`，而非直接依赖 `core*` 实现
- **扩展点机制**：通过 `kura/tools/kura-addon-archetype` 模板创建新插件
- **Web 前端使用 GWT**（`gwtbootstrap3`），不是现代 npm/React 生态

## 开发注意事项

1. **修改核心模块** 前务必确认会影响哪些 Feature 和发行包
2. **修改依赖版本** 需同步检查 `target-platform/pom.xml` 的兼容性
3. **驱动/Linux 模块** 的改动可能只在特定硬件上暴露问题
4. **`kura/org.eclipse.kura.protocol.modbus/`** 目录存在但未纳入主构建，属于历史遗留
5. **测试覆盖率较低**，大部分模块无 `src/test`，改核心逻辑需格外谨慎
6. **容器构建仅支持 x86**，不支持 ARM 上的 Docker 构建

## 常用开发模式

### 创建新插件/扩展
1. 使用 `kura/tools/kura-addon-archetype` 生成脚手架
2. 依赖 `org.eclipse.kura.api`，通过 OSGi Service 注册
3. 在 `kura/features/pom.xml` 中加入对应的 feature 模块

### 本地调试
使用 `kura/emulator/` 中的 Kura_Emulator 启动配置在本地仿真运行，无需真实网关设备。

### REST API 开发
REST 模块位于 `kura/org.eclipse.kura.rest.*`，基于 JAX-RS/Jersey。新增 REST 端点参考现有 `rest.provider` 模块结构。
