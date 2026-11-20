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

## 2026-11-18 保留卸载候选与实际失败

从新Git/private Maven缓存/JDK21/Maven3.10.1顺序重建support、Core/tools、distrib。4b候选ARM64包 `6.0.0~git202611180104.4b8171c-1`，SHA256 `2014aec537e4789f3fa201615f93bc713a3ea8e2a30046dde9bbb12eecf1e2a1`。Root载荷/内嵌guards/维护shell/Main依赖通过；两clock生产类与既有VM字节一致，不把原VM或旧中间产物作为构建输入。此包现在是**已知卸载失败候选**。

沿原容器 `7fd8c6a0967a58a95c123785e5feff68cd0ce74e370d00ee875f9e215ac08d7e` 的e1安装、原账号和数据继续。唯一一次真实dpkg升级exit0；原26输入中19个外部文件完整指纹、7份Core数据/历史逻辑字段保留，新增1正常package-history，总27。Core拷回产生inode/ctime差异如实保留，不断言atime。Main保持disabled/inactive/PID0/NRestarts0，无事后补disable；clock namespace/operations不存在，key业务/startups均0。

随后唯一一次真实 `dpkg --remove kura-core` exit1。已经发布完整retained副本、保存disabled选择，clock/key listeners已移除且维护围栏保留；失败在新增prerm错误地调用已被postinst删除的`install/manage_kura_users.sh`，**没有进入账号回调**。这是本轮引入的路径错误；原已安装Root helper实际为`bin/manage_kura_users.sh`，源码b509d5d3f7已恢复此路径并新增回归。原失败日志保留，不将该remove或未执行的reinstall/purge记为通过；源码修正尚未重建/安装。

失败后只读复核原27输入：20个外部文件完整指纹、7份Core数据/历史逻辑字段及各自retained副本一致，历史两标记和Root0600数据canary保留。产品`--check-retained-main-state`沿原Root/fence/HMAC/账号校验通过，原clock目的/UID995/GID988保持；所有账号数字身份相同，0 clock业务、0 key业务、0 Core启动。包状态仍installed 4b。原remove维护ID `1fab699a-6544-4f65-87f3-cf24a0691c05`、`/var/lib/kura-retained`、原canonical数据、维护clock状态均保留。随后同容器正常停止exit0，不能重当空主机、清retained或改维护ID，也不能盲重发remove。

此次包内key archive只是该次正常移除的数据恢复副本，未调用已闭环的Root备份/归档/轮换/恢复/续期验收。私有日志/指纹仍只在本地0700/0600，不进Git或知识库。


后续需沿同一失败维护目的精确续接，实际保留重装/purge/中断/legacy及全部boot状态仍内部pending。Root配对不放宽，不能把已知失败4b包用于自动验收。

## 2026-11-18 原维护续接及正常38a移除/重装

原1fab失败在同一自有7fd夹具精确续接，随后14f正常保留重装由产品完成原维护；该局部修复不算通用中断恢复。38a修复残留NM授权、严格已知Root规则及错误传播，从新Git/private缓存/JDK21构建，正常单次升级/移除/同包保留重装均exit0。新正常remove维护4f52e089-e745-4f1b-83e6-ac2fe8059252由产品以同ID完成，原29输入22外部完整/7Core逻辑字段保持，新增1正常回执，总30，Main disabled/未启、原UID/密钥/历史.data及Root canary保持。实际polkit同一UID997/cap0/NNP1 subject授权0→1→0、daemon未重启、无网络写；探针已清理。

原容器健康停止exit0，保留全部数据/身份；原1fab/4f52验收不重做。63宿主回归及12真实LinuxRoot条件通过，不累加旧JVM/crypto。详见`management-nm-polkit-policy-20261118.md`及console实际审查；purge/legacy/其他boot状态/通用中断/完整六组件及12父项仍内部pending。

## 2026-11-18 实际四服务选择

97补runtime disable并传播清理失败；原有凭据/回执完整时只识别固定Root/dev/null Main mask，拒绝key bootstrap/真实override。44令clock安装仅把严格Main mask+明确PID0/inactive视为off，不接受clock helper masked、不读key、不放宽代码配对。135选择134过/1既有Linux-only归档用例在macOS skip，7 nativeRoot mask/key及6实际shipped preRemove条件通过；不累加旧选择。实际enabled-runtime/enabled在97、masked-runtime/masked在完整44各自单次正常remove/reinstall通过、每次同目的完成，38输入/原UID/密钥/.data历史/Root canary保持，Main始终未启。97 masked-runtime已知clock拒绝原2041仅有界修复后完成，不计正常产品/通用中断通过；随后完整44 masked upgrade及独立正常模式通过。详见`management-main-boot-choices-20261118.md`及console实际审查。四profile验证后才单独恢复夹具disabled停放，正常停止保留；所有完成目的不重做。

本轮overlay重挂仅st_dev变、30原文件其余九字段精确，原失败/旧基线保留，当前boot新基线独立记录，产品Root/namespace检查未改。static/linked实际Core、purge/通用中断/旧态及完整矩阵仍内部pending。

## 旧 Networking 与 Core 原位联合升级

旧 Networking 可能仍在运行合法的已安装版本，但没有新版 Core 所需的 typed provider 证明。新版 Networking 的 `preinst` 又要读取已解包的新版 Core broker。核对两包的发行摘要后，由 Root 从不可被其他用户写入的目录传入两份归档的规范绝对路径，先传 Core，再传 Networking。

```sh
sudo env KURA_NETWORKING_COHORT_SHA256='<已审批的 Networking SHA-256>' \
  /usr/bin/dpkg --install /root/approved/kura-core.deb /root/approved/kura-networking.deb
```

该入口仅用于已安装 Networking 因旧版未声明证明文件而缺少 typed 证明的 Core 升级。Core 在实际调用它的同 Root、同挂载命名空间 dpkg 进程中核对两个有序路径、Core 目标版本、Networking 新旧版本、归档摘要、九个 provider 合同和只读 ModemManager 策略。当前包已声明但缺失的证明、已存在的错误证明和游离的兼容包继续拒绝。归档检查只读取文件，不执行，也不产生可跨事务使用的批准记录。普通 Main 启动仍检查实际已配置的 Networking、每个 provider 证明及已装文件。实际 dpkg 返回错误时，按同 Root 的原围栏和包状态核定中断点。
