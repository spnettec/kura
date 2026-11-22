# Main 单元布局的维护前准入

2026-11-18，源码 `e99df17793799a6e506ef37b5c1a82e7140193ba`。

此前 `Lifecycle.enter` 先创建维护围栏、停止 key 辅助服务，移除流程到保存 Main 选择时才拒绝 linked 等不支持的布局。一次已知不支持的操作也会改变服务现场。现在有既存 Main 且没有原维护围栏时，先从实际 systemd 查询 UnitFileState，仅接受既有六种选择。linked、linked-runtime、alias、indirect、generated、transient、空值及查询失败均在初始化、创建新围栏和 stop 之前拒绝。

对于 schema2 包的 static Main，另用已有 Root manifest 的 generation.unitSha256 校验固定 vendor 单元；手工去掉 `[Install]` 形成的未配对 unit 不能冒充包支持的 static。检查不读取 key、不接受新路径或新的信任来源，也不放宽 Root 配对。Main 不存在时不引入完整 reader 依赖，独立冷恢复基础服务仍可维护；有原围栏时保留其原意图，避免把 unpack 中间态当成一次新准入。后续原 HMAC、账号、代码与维护门禁继续有效。

相关宿主回归 66 项选择、65 通过、1 项既有 Linux renameat2 用例在 macOS skip，不把 skip 算通过。新 Git 检出/JDK21/Maven3.10.1/private 缓存依次重建 support、Core/tools、distrib，ARM64 包 `6.0.0~git202611180255.e99df17-1`，SHA256 `f99692a65cd768936864f4705b68f2e508a54d58ca57969fe134a1e659ddb0a1`，203550910 字节。39 个 key/generation 文件、3 个 key 单元、Main 配对、精确嵌入的新 lifecycle、clock guard 和 Root 载荷/父目录已核对。

同一原 7fd 夹具正常升级一次 exit0，38 原输入保留，新增一份正常 package-history。随后完整观察的 linked、linked-runtime、未配对 static 三项实际 dpkg remove 各一次按预期 exit1：39 份原数据及所选代码/链接完整指纹精确，5 个辅助单元属性和活跃进程起始 ticks 精确，Main 未启动；无新围栏、retained、upgrade stage 或 key/clock 业务。每项只在拒绝观察完成后恢复夹具自己选择的原 vendor 布局，未把夹具恢复算成产品迁移。

首次 linked 另有不完整观察：socket 属性采集错误先于 dpkg；修正后实际 remove 已知拒绝，但 CLI 脱敏消息断言出错，调用前辅助服务快照没有持久化。该次不计完整矩阵通过，不回填快照。保留原失败和日志、确认39份数据与无围栏后，仅恢复夹具布局；修正采集后的独立 linked-observed 是新观察，未重发任何 UNKNOWN/原 UUID 业务。详见 console 审查。

拒绝测试使 dpkg 的 operator selection 成为 deinstall，这是尝试移除的真实结果。三项观察之后单独恢复夹具原 install 选择；Main 一直 disabled/inactive/PID0。最终完整 generation 与 clock canonical/actor/effective unit 配对通过，原 clock UID995/GID988/目的及所有账号和数据保留，39 输入/15 正常回执，原容器正常停止 exit0。

本结果证明不支持布局会在维护改动前拒绝，**不证明合法旧 static 包迁移、linked 自动接管或完整安装矩阵完成**。合法旧包转换、purge、通用中断与半配置恢复、完整 Core/OSGi/当前合法 Main 业务及六组件/provider/launcher/资源/平台矩阵继续内部 pending；完整12父项不缩减，仅原3 external deferred。原 UNKNOWN/丢失 CSR 不重发、换号或跨 Root 查询，已闭环密钥/备份/归档/轮换/恢复/900秒不重放。无 push/JDK27/活动 runtime 清理。

审查：`kura-management-console/docs/reviews/core-main-layout-admission-review-20261118.md`。回执：父工作空间 `.management-close-20261116/source-cohort-20261117/core-main-static-linked-20261118/`。
