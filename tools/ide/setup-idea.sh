#!/usr/bin/env bash
# 新 Mac IDEA 测试/调试环境检查与生成（只面向 macOS）。
# 完整流程见 kura/docs/testing/idea-test-setup.md。
# 幂等：不修改任何已提交文件与已有 IDEA workspace.xml；生成的隔离验收配置写入
# .idea/runConfigurations/（该目录被 git 排除，仅存本机）。
#
# 用法：
#   tools/ide/setup-idea.sh [--m2 DIR] [--build-runtime] [--isolated-home DIR] [--dry-run]
#
# 新机器不需要本工作空间以外的任何目录：Maven 缓存默认 ~/.m2/repository
# （首次构建自动全量下载，一次性）；plc4x-yofc 缺失时按提示先安装即可。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KURA_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WS_ROOT="$(cd "$KURA_ROOT/.." && pwd)"

M2_REPO=""
ISOLATED_HOME=""
BUILD_RUNTIME=0
DRY_RUN=0

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --m2) M2_REPO="$2"; shift 2 ;;
    --isolated-home) ISOLATED_HOME="$2"; shift 2 ;;
    --build-runtime) BUILD_RUNTIME=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    *) echo "未知参数: $1（--help 查看用法）" >&2; exit 2 ;;
  esac
done

info() { printf '%s\n' "$*"; }
warn() { printf '警告: %s\n' "$*" >&2; }
die()  { printf '错误: %s\n' "$*" >&2; exit 1; }

execute() {
  if [[ "$DRY_RUN" -eq 1 ]]; then info "[dry-run] 将执行: $*"; else "$@"; fi
}

maven_args=(-f "$KURA_ROOT/pom.xml" -Pworkspace -pl :kura-workspace,:kura-dev-runtime
  -am install -DskipTests -DskipITs -Dkura.dev.profile=macos)
if [[ -n "$M2_REPO" ]]; then
  maven_args+=("-Dmaven.repo.local=$M2_REPO")
fi

info "== 1/4 环境检查 =="
[[ "$(uname -s)" == "Darwin" ]] || die "本脚本仅支持 macOS（开发测试只面向 Mac）"
command -v mvn >/dev/null || die "未找到 mvn，请安装 Maven 3.10"
MVN_VERSION="$(mvn -v 2>/dev/null | head -1 || true)"
info "Maven: $MVN_VERSION"
if /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
  info "JDK 21: $(/usr/libexec/java_home -v 21)"
else
  warn "未找到 JDK 21（Temurin 21），IDEA 项目 SDK 与运行都需要它"
fi
command -v python3 >/dev/null || die "未找到 python3（kura-dev-runtime/tools/runtime.py 需要 3.9+）"
for repo in kura-cloud kura-camel kura-networking; do
  [[ -d "$WS_ROOT/$repo" ]] || warn "缺少 sibling 仓库 $WS_ROOT/$repo（相关 .run 配置在其项目中，缺省不影响 kura 本体）"
done
info ""

info "== 2/4 Maven 缓存检查 =="
if [[ -z "$M2_REPO" ]]; then
  info "使用默认缓存 ~/.m2/repository（IDEA 与 CLI 均无需任何 override）"
  M2_REPO="$HOME/.m2/repository"
else
  info "使用指定缓存 $M2_REPO（IDEA 需在 Settings > Build Tools > Maven > Local repository 指向它）"
fi
if compgen -G "$M2_REPO/org/apache/plc4x/plc4j-api/*/plc4j-api-*.jar" >/dev/null; then
  info "plc4x 产物已存在"
else
  warn "Maven 缓存中缺少 plc4x-yofc 产物，Kura 构建会失败。请先执行："
  warn "  cd $WS_ROOT/plc4x-yofc && mvn install -DskipTests${M2_REPO:+ -Dmaven.repo.local=$M2_REPO}"
fi
info ""

if [[ "$BUILD_RUNTIME" -eq 1 ]]; then
  info "== 3/4 组装开发运行目录 target/runtime =="
  # 与已提交 .run 配置的 Before-launch 目标完全一致；生成 jvm.args 与
  # configuration/kura.properties，路径只指向 target/runtime 和 ~/.kura-dev/macos。
  execute mvn "${maven_args[@]}"
  info ""
else
  info "== 3/4 跳过运行目录组装（IDEA 中运行 Kura macOS 配置会自动组装；或加 --build-runtime）=="
  info ""
fi

info "== 4/4 IDEA 配置 =="
RUNTIME_DIR="$KURA_ROOT/kura-dev-runtime/target/runtime"
if [[ -f "$RUNTIME_DIR/launcher.jar" ]]; then
  info "开发运行目录已就绪: $RUNTIME_DIR"
else
  info "target/runtime 尚未组装：IDEA 中首次运行 Kura macOS 时 Before launch 会自动组装"
fi
if [[ -f "$RUNTIME_DIR/jvm.args" ]] && grep -q 'migration-baseline' "$RUNTIME_DIR/jvm.args" 2>/dev/null; then
  warn "当前 target/runtime/jvm.args 仍指向上轮验收的旧目录（migration-baseline），"
  warn "重新执行 --build-runtime 或 IDEA Before launch 即可按当前机器/默认 profile 重新生成。"
fi

# 隔离数据目录的验收启动：先在终端组装（环境变量会传给 Maven，进而传给
# runtime.py assemble），再写入本地 IDEA 运行配置（env 与组装一致）。
if [[ -n "$ISOLATED_HOME" ]]; then
if [[ -d "$ISOLATED_HOME" ]]; then
  ISOLATED_HOME="$(cd "$ISOLATED_HOME" && pwd)"
elif [[ "$DRY_RUN" -eq 1 ]]; then
  ISOLATED_HOME="$(python3 -c "import os,sys; print(os.path.abspath(sys.argv[1]))" "$ISOLATED_HOME")"
else
  ISOLATED_HOME="$(mkdir -p "$ISOLATED_HOME" && cd "$ISOLATED_HOME" && pwd)"
fi
  [[ "$ISOLATED_HOME" == "$KURA_ROOT"/* ]] && die "隔离数据目录不能放在 kura 仓库内（Maven clean 会清掉开发数据）"
  info "隔离数据目录: $ISOLATED_HOME"
  execute env KURA_DEV_HOME="$ISOLATED_HOME" mvn "${maven_args[@]}"
  RUN_DIR='.idea/runConfigurations'
  RUN_FILE="$KURA_ROOT/$RUN_DIR/Kura macOS isolated acceptance.run.xml"
  mkdir_cmd=(mkdir -p "$KURA_ROOT/$RUN_DIR")
  execute "${mkdir_cmd[@]}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] 将生成: $RUN_FILE"
  else
    cat > "$RUN_FILE" <<EOF
<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="Kura macOS isolated acceptance" type="JarApplication" factoryName="JAR Application">
    <option name="JAR_PATH" value="\$PROJECT_DIR\$/kura-dev-runtime/target/runtime/launcher.jar" />
    <option name="VM_PARAMETERS" value="@&quot;\$PROJECT_DIR\$/kura-dev-runtime/target/runtime/jvm.args&quot;" />
    <option name="PROGRAM_PARAMETERS" value="-configuration &quot;\$PROJECT_DIR\$/kura-dev-runtime/target/runtime/configuration&quot; -consoleLog -console" />
    <option name="WORKING_DIRECTORY" value="\$PROJECT_DIR\$/kura-dev-runtime/target/runtime" />
    <option name="ALTERNATIVE_JRE_PATH_ENABLED" value="true" />
    <option name="ALTERNATIVE_JRE_PATH" value="21" />
    <envs>
      <env name="KURA_DEV_HOME" value="$ISOLATED_HOME" />
    </envs>
    <method v="2" />
  </configuration>
</component>
EOF
    info "已生成: $RUN_FILE（.idea 被 git 排除，仅本机生效）"
    info "该配置不含 Before launch 组装步骤：改用隔离目录重新组装时，先在终端带 KURA_DEV_HOME 执行 mvn 组装，再重启。"
  fi
fi
info ""

info "== 完成。IDEA 中的使用步骤 =="
info "1. 用 IDEA 打开各仓库根 pom（kura、kura-cloud、kura-camel、kura-networking），等待 Maven 导入；"
info "   kura 项目需在 Maven 面板启用 workspace profile。"
info "2. 项目 SDK 选 JDK 21；未用默认缓存时，Maven Local repository 指向 --m2 指定的目录。"
info "3. Run/Debug 选择共享配置：JUnit 各端点/单测，Kura macOS（完整网关，调试 bundle 业务代码）。"
info "4. 新增配置：按 Run/Debug Configurations 配好后勾选 Store as project file，"
info "   即存入仓库 .run/ 目录，随 git 分享给所有人。详细说明见 kura/docs/testing/idea-test-setup.md。"
