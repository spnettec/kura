# Main服务选择与安装器停止状态

代码97dbbc06e9/44b4281923。

实际PID1/systemd255.4-1ubuntu8.18命令探针显示，普通disable只清/etc的enable链接，enabled-runtime在/run仍保留；追加disable --runtime后两类enable链接均清，永久和runtime的/dev/null mask均保持。97改prerm按顺序同步disable两层，任一步失败在删除vendor unit前传播；补齐logrotate/cron和临时目录清理失败传播。真实shipped preRemove回调在6个受控unit profile条件通过，未初始化Core或网关journal；static/linked只作命令行为观察，完整Core对应路径仍待验。

原KeyStore.prepare一律拒绝/etc、/run的Main覆盖项，连Root显式/dev/null mask也拒绝。97只识别这两个固定路径下单链接、Root所有、父目录为物理Root目录且组/其他用户不可写、目标精确/dev/null、读前后稳定的屏蔽链接；必须已有合法canonical凭据及原回执。缺钥/缺回执不引导新钥，普通unit/其他目标/父链接或可写/错属主/多链接继续拒绝，mask增删/替换使stable失败。原regular-file reader、generation/UNKNOWN/Root配对未放宽；屏蔽项不作为key source，不读取目标。

实际97 masked-runtime重装继续暴露clock_setup.properties对Main LoadState=masked直接UNSAFE_UNIT。44只在Main固定Root/dev/null mask且明确inactive/MainPID0/ControlPID0时接受停止状态；clock service/socket自身masked、Root代码替换、非零/缺失PID仍拒绝。clock安装器仍不读取数据key，原code/effective-unit配对不变，Main从未被强制unmask或启动来取得产品通过。

最终选择135项宿主Python回归，134通过、1项不可变Root归档renameat2在macOS显式skip；不把skip算通过，不重放此前Linux归档/密钥/900秒验收。7个实际Linux Root mask/key条件通过（只在重定位的单元测试凭据目录，无网关journal/操作/PKI），6个实际shipped preRemove/systemd条件通过，不与重叠选择累加。第一次native测试因PID1继承umask000、夹具父目录可写而正确拒绝，原失败及目录保留；新独立夹具显式umask077，生产检查未改。


实际原ARM64单现场enabled-runtime/enabled在97包各一次正常remove/reinstall通过，masked-runtime/masked在完整44包各一次通过，mask字段及原身份/密钥/历史data保持，Main未启动。97 masked-runtime原失败已同ID2041在有界配对clock代码修复后完成，不作为未修改产品/通用中断恢复通过。详细证据与限制见console的`docs/reviews/core-main-boot-choice-matrix-review-20261118.md`；static/linked/legacy/purge/通用中断及全六组件/provider/launcher矩阵和12父项继续pending。
