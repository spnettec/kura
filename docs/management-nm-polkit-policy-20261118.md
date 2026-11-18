# Core NM polkit规则的安装与撤销

代码`38a983787e9b8ce9d6fbb446f5e5322de8762da1`。

实际移除观察到旧Root0644规则仍在，SHA `ff81d098ed539b00d0de3e83dfa81ea6a103aa5b59c1758c6aa6069cfa10609e`，仍授予kurad NM/ModemManager/wpa命名空间权限。新Root本地manage_network_polkit_policy固定路径和原规则精确字节，check/install/remove均检查所有父目录、Root所有权、非可写、普通单链接及稳定读；不跟随链接、不接受额外内容/超长/FIFO。未知本地规则保留并显式失败，原Root/key配对未放宽。

新规则完整fsync后以独占硬链接发布，再撤临时名，不能覆盖并发加入的site规则；既有相同规则不重写，已知代码0600可正规化为polkit可读0644。安装器在准入和账号创建前只读检查，卸载通过安装后的Root bin回调撤销已知规则。补齐原sudoers/legacy规则删除、组移除和原配置还原错误传播；dialout已无成员时不误当失败。未知site配置及所有历史治理场景仍需完整矩阵，不据此宣布全部授权清理闭环。

63项当前宿主合同/文件系统/manager注入/systemd policy回归通过；12项实际Linux Root权限/文件系统条件通过、无skip，包含精确原字节/幂等、未知内容、链接/硬链接、错误文件或父属主、可写文件或父目录、FIFO、超长、非法动作和已知代码模式。Linux测试只改policy目标到自有tmpfs，生产Root检查逐字不改；临时只读容器无宿主绑定/网络/Kura初始化。最初symlink测试的readlink自查改变atime已修为lstat测元数据、之后核链接文本，失败保留、不回填时间戳。Java/clock生产逻辑未改，旧JVM/crypto验收不重跑、不累加。


正常产品路径的实际升级、remove、retained reinstall及同一cap0/NNP1 subject授权0→1→0均通过，具体证据与范围见父工作空间console的`docs/reviews/core-retained-reinstall-policy-review-20261118.md`。只有已知disabled/Ubuntu ARM64 profile，完整provider/launcher/资源/legacy/中断/purge和全部12父项仍pending。原NM后端不变，无真实网络写入；Main仍需完整最小权限与typed broker工作。
