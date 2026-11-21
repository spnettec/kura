#!/bin/sh

# Kura should be installed to the @kura.install.dir@ directory.
export PATH=/bin:/usr/bin:/sbin:/usr/sbin:/usr/local/bin:/opt/jvm/bin:/usr/java/bin:$PATH
export MALLOC_ARENA_MAX=1
# Keep PID, logs and generated runtime files private regardless of caller mask.
umask 077

DIR=$(cd $(dirname $0)/..; pwd)
cd $DIR

# YOFC-KURA-ORDINARY-JVM-ARGS-V1
# Optional administrator-owned argument file. With no setting the historical
# launcher remains unchanged; this is independent of management-agent presence.
set --
if [ -n "${KURA_JVM_ARGS_FILE:-}" ]; then
  case "$KURA_JVM_ARGS_FILE" in
    /*) ;;
    *) echo "KURA_JVM_ARGS_FILE must be absolute" >&2; exit 1 ;;
  esac
  if [ ! -f "$KURA_JVM_ARGS_FILE" ] || [ -L "$KURA_JVM_ARGS_FILE" ] || [ ! -r "$KURA_JVM_ARGS_FILE" ]; then
    echo "KURA_JVM_ARGS_FILE must be a readable regular file" >&2
    exit 1
  fi
  set -- "@$KURA_JVM_ARGS_FILE"
fi

# set up the configuration area
# Use the same credential for the installed service and direct launchers.
. "${DIR}/bin/kura_credential_env.sh" || exit 1

python3 -I -B "${DIR}/bin/kura_framework_config.py" "${DIR}" /tmp/.kura/configuration || exit 1

KURA_RUNNING=`ps ax | grep java | grep "org.eclipse.equinox"`

if [ -z "$KURA_RUNNING" ] ; then
    # A failed console redirection in the child would publish the PID of a dead process.
    exec 4>>/var/log/kura-console.log || exit 1
    # Open the PID file before starting a process that maintenance must be able to find.
    exec 3>/var/run/kura.pid || exit 1
  nohup python3 -I "${DIR}/bin/kura_key_store.py" exec-java "$@" \
        -Xms@kura.mem.size@ -Xmx@kura.mem.size@ \
        -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/var/log/kura-heapdump.hprof \
        -XX:ErrorFile=/var/log/kura-error.log \
        -XX:+IgnoreUnrecognizedVMOptions \
        --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
        --add-modules=ALL-SYSTEM \
        -Dkura.os.version=@kura.os.version@ \
        -Dkura.arch=@kura.arch@ \
        -Dtarget.device=@target.device@ \
        -Dorg.eclipse.kura.core.crypto.secretKey="$KURA_CRYPTO_SECRET_KEY" \
        -Declipse.ignoreApp=true \
        -Dkura.home=${DIR} \
        -Dkura.configuration=file:${DIR}/framework/kura.properties \
        -Dkura.custom.configuration=file:${DIR}/user/kura_custom.properties \
        -Ddpa.configuration=${DIR}/packages/dpa.properties \
        -Dlog4j.configurationFile=file:${DIR}/log4j/log4j.xml \
        -Dlog4j2.disable.jmx=true \
        -Djdk.tls.trustNameService=true \
        -Dtruffle.UseFallbackRuntime=true \
        -Dosgi.console=5002 \
        -Declipse.consoleLog=true \
        -jar ${DIR}/plugins/org.eclipse.equinox.launcher-@org.eclipse.equinox.launcher.version@.jar \
        -configuration /tmp/.kura/configuration >&4 2>&1 4>&- 3>&- &

    KURA_PID=$!
    if ! printf '%s\n' "$KURA_PID" >&3; then
        kill "$KURA_PID" 2>/dev/null
        wait "$KURA_PID" 2>/dev/null
        exit 1
    fi
    exec 3>&-
    echo "Kura Started (pid=$KURA_PID) ..." >&4
else
    echo "Failed to start Kura. It is already running ..." >> /var/log/kura-console.log
fi
