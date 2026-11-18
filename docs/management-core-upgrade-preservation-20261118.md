# Core 升级保留服务选择与真实数据

2026-11-18。实现 `b49eb6cb204f2e7b4ac00322b45187354bf44847`（Main 自启选择及失败传播）、`e1c40469d9807c0518a34b1f9e24b033df2d5d98`（历史数据及属主保留）。不是完整六组件/provider/launcher/所有安装模式的关闭。

## 服务选择

原 `kura_install.sh` 在升级时无条件 enable Main，而旧 prerm 的 upgrade 分支保留服务及其 enable/mask 链接。用户手工 disabled 或 enabled-runtime 因而可能被改成永久自启。当前脚本在模板发布前观察标准 vendor/admin/runtime 位置是否已有 Main unit；已有时保留链接，不调用 enable。全新安装仍在 reload 成功后 enable；reload、首次 enable 失败均传播。升级消息不再无条件承诺下次重启自启。

5项合同检查覆盖新装、disabled/enabled/enabled-runtime/static/masked/masked-runtime、其他标准位置或失效链接、reload/enable失败。它们使用临时文件系统和模拟 systemctl，不冒充所有实际 systemd 配置。保留数据重装、其他位置/平台、完整启动和故障矩阵继续待验。

## `.data` 与真实属主

第一次真实升级暴露原数据恢复顺序：新安装流程先创建 `.data/manage_kura_users.sh`、`.data/snapshot_0.xml`，之后 cp -a -n 不覆盖新文件，又无条件刷新恢复快照。本次默认场景中两副本字节/属主/模式相同，mtime 被刷新；不同历史内容可能被新默认值覆盖。原失败检查和实际差异保留，没有回填时间戳或重写先前回执。

当前恢复使旧 `addon-data` 优先，连脚本形状的历史文件也按数据保留。实际可执行 addon code 由独立 Root `libexec/addons` 配对发布，不从 `.data` 认领或执行。已有恢复快照不再重写；只填真正缺失且不是数据链接的副本，并传播复制失败。移除恢复后对 user/data/packages/log 的递归 chown；cp -a 保持原数字属主/模式，后续 code-only 权限核对只处理安装代码。

5项合同检查覆盖历史内容优先、缺失恢复副本及元数据、已有数据链接不跟随、复制失败保留输入、不执行数据 chown。只证明相应恢复块，不代替其他 provider、standalone 路径或所有 purge/恢复组合。

## 实际同现场升级

使用前轮首装现场 `7fd8c6a0967a58a95c123785e5feff68cd0ce74e370d00ee875f9e215ac08d7e`，原 clock 账号目的 `2a388683-4a21-4616-95bd-41efbf631da0`、UID995/GID988及全部原凭据保留。该现场第一次首装后仅为停放被夹具 disabled；本次没有在升级后补做 disable 来制造通过。无 SYS_TIME、外部网络或个人/runtime 挂载，Core Main 从未启动。

两个源码均从新真实 Git 检出，以 JDK21/Maven3.10.1/private Maven cache 重建 support/Core/全部工具/distribution，无旧 target 或共享项目缓存写入。

| 实际包 | SHA256 | 验证范围 |
| --- | --- | --- |
| `6.0.0~git202611180028.b49eb6c-1` | `ca68e097f655747594944bfdb28e15f613e8f6ee645c267c5eac3982b0669fd3` | 从9066包唯一一次升级成功；Main仍disabled/PID0；外部17文件完整指纹、4份权威用户文件逻辑字段精确；2历史副本mtime刷新如实记录 |
| `6.0.0~git202611180039.e1c4046-1` | `5df08c91871b3f922811b7f14bf226ea964b9b9bbe856196c72afff0ebdb66d5` | 从b49包唯一一次升级成功；带历史标记的2副本及Root0600数据canary保留；原25输入验证通过 |

第二次升级前先在本新夹具归档两份原副本，再明确追加公开历史标记，并创建 Root/Root0600 的公开数据文件；权威 user/snapshots 和实际密钥未改。该动作不是客户数据验收或旧证据恢复。升级后18份外部密钥/账号/旧回执的 dev/inode/uid/gid/mode/nlink/size/mtime/ctime/SHA 精确；7份 Core 用户/数据/历史文件的 uid/gid/mode/nlink/size/mtime/SHA 精确，复制导致的 inode/ctime 差异记录在私有观察中，不称全元数据一致。自查 NOATIME，atime未断言。两次各新增1份正常 package-history，旧回执保留。

最终仍 installed、Main disabled/inactive/PID0/NRestarts0，actor inactive/PID0；clock namespace/operations未创建、业务请求0。最终 actor cohort `a16faa5ed0f60733a92a7fdf3a1f1a564b63200f1b81e20e63f207e0a5578ac4`，manifest文件SHA `1798b28daab00890252b27ef75a3addbe2a0bdc2dd0f8fe60c0329c7ceaa623c`。新历史标记、Root数据和全部凭据留在同一已正常停止容器，不清空、不重初始化或误启Main。安装日志/指纹在本地0700/0600目录，不进Git/知识库。

回执：父工作空间 `.management-close-20261116/source-cohort-20261117/core-clock-actor-current-runtime-20261118/`。只证明 Ubuntu ARM64 默认 Core、inactive/disabled Main 的两次包升级及上述数据；完整 Core/OSGi、当前完整包的实际 actor/消费者业务、其他服务状态、六组件/全部provider/launcher/安装重装移除purge恢复/资源平台、RTC/Chrony/其余typed brokers与12父项继续内部 pending。仅原3 external deferred；不重放旧UNKNOWN、闭环密钥或900秒，不push/JDK27/清活动runtime。
