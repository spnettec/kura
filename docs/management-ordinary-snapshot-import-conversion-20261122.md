# 普通快照导入的跨格式合同（2026-11-22）

发布路径 `publish-ordinary-snapshot` 把已停止 Main 的暂存恢复输入发布为普通快照。
此前仅接受与普通目录当前格式一致的输入；本合同把格式差异定义为确定性转换，
同时保留既有拒绝与原号续接语义。

## 目标格式

普通目录的当前格式由 `SnapshotStorePolicy` 从 `framework/kura.properties` 与
`user/kura_custom.properties` 的 `kura.snapshots.encrypt` 得出（`plain` 或 `aes-gcm`）。
正式 Main 按同一设置读取全部普通快照：明文策略下密文文件被重命名为 `.bad`，
加密策略下受保护启动明确拒绝改名、加密或回退。因此发布文件必须与该格式一致，
差异方向不再拒绝，而是在发布内转换。

## 允许的转换

- 暂存 `plain` + 策略 `aes-gcm`：用计划绑定的当前代密钥按 Main 写路径
  （`aesEncryptingStream`：ASCII 头 + Base64 + GCM）加密后发布。
- 暂存 `aes-gcm` + 策略 `plain`：用同一密钥解密后发布明文。
- 格式一致：按原字节发布（既有行为）。

XML 文档内容永不改写：legacy/`BASE64_LOGICAL_V1` 密码与容器表示仍由正式 Main
在加载时转换（既有 `snapshot-conversion-resume`、`legacy-snapshot-cm`、
`controlled-legacy-snapshot` 的验证范围）。

## 拒绝（不落意图、不写任何文件）

转换在意图落盘前以内存方式完成，因此失败只留下干净拒绝：

- 输入 artifact 摘要不等于计划 `snapshotSha256`；
- 按计划 `passwordPolicy` 解码失败（密钥缺失/不配、解密失败、结构或密码合同不符）；
- 转换输出超过 32 MiB（密文 Base64 膨胀约 4/3， oversized 明文放不进普通目录上限）；
- 转换工具不可用或以错误退出。
既有拒绝不变：代密钥/cohort 变化（`COHORT_CHANGED`）、目录身份变化（`CONFLICT`）、
策略工具失败（`SNAPSHOT_POLICY_MISMATCH`）、快照编号落后时钟。

## 记录与续接

意图、就绪与回执新增 `publishedSha256`、`publishedSize`、`publishedMode`
（无转换时等于源摘要/大小/计划格式）；pending 与目标文件的指纹一律用发布值。
计划核对与回执血缘继续使用源 `snapshotSha256`。转换后流程与已验证的原子发布一致：
就绪前 SIGTERM 沿原号 `UNKNOWN`；改名后回执前 SIGTERM 得到
`ORDINARY_SNAPSHOT_PUBLISHED_UNCONFIRMED`，同号补回执，原 inode 与摘要保持。

## 受保护启动读取已发布件

计划 `guarded` 块在已发布时新增 `publishedSha256`/`publishedSize`/`publishedMode`。
启动请求属性新增 `snapshot.published.sha256` 与 `snapshot.published.mode`：
受保护 Main 按发布摘要校验普通目录文件并按发布格式读取；`snapshot.sha256` 与
`snapshot.mode` 保持源值，CM_APPLIED、启动回执、写释放决定与健康回执的血缘摘要
链全部不变。发布摘要与源摘要不同的启动请求必须成对携带两个字段，缺一即拒。

普通装载准入（`admitNormalLoad`）绑定的是 Main 实际读取的工件，即发布摘要；
受保护探针在该阶段报告的 `snapshotSha256` 因此是发布摘要。CM_APPLIED 阶段的
准入与其证据仍使用源摘要，两个阶段各自与自己的文件一致。

## 与既有证据的边界

2026-11-22 之前的同格式发布、提交前中断 `UNKNOWN`、提交后丢回复续查等现场
按原围栏冻结，不重放。本合同自 Core `9df46c228f` 起生效，验证见
`.management-close-20261116/core-rtc-hotplug-20261120/snapshot-import-conversion/`。
