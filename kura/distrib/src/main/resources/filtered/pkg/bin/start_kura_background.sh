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

mkdir -p /tmp/.kura/configuration
${DIR}/bin/gen_config_ini.sh ${DIR}/framework/config.ini ${DIR}/plugins ${DIR}/siblings > /tmp/.kura/configuration/config.ini

KURA_RUNNING=`ps ax | grep java | grep "org.eclipse.equinox"`

if [ -z "$KURA_RUNNING" ] ; then
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
        -Declipse.consoleLog=true >> /var/log/kura-console.log 2>> /var/log/kura-console.log \
        -jar ${DIR}/plugins/org.eclipse.equinox.launcher-@org.eclipse.equinox.launcher.version@.jar \
        -configuration /tmp/.kura/configuration &

    #Save the PID
    KURA_PID=$!
    echo "Kura Started (pid="$KURA_PID") ..." >> /var/log/kura-console.log
    echo $KURA_PID > /var/run/kura.pid
else
    echo "Failed to start Kura. It is already running ..." >> /var/log/kura-console.log
fi
