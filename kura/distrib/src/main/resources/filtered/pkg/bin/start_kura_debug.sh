#!/bin/sh

export PATH=/bin:/usr/bin:/sbin:/usr/sbin:/usr/local/bin:/opt/jvm/bin:/usr/java/bin:$PATH
export MALLOC_ARENA_MAX=1
# Keep PID, logs and generated runtime files private regardless of caller mask.
umask 077

DIR=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$DIR" || exit 1

# set up the configuration area
# Use the same credential for the installed service and direct launchers.
. "${DIR}/bin/kura_credential_env.sh" || exit 1

python3 -I -B "${DIR}/bin/kura_framework_config.py" "${DIR}" /tmp/.kura/configuration || exit 1

KURA_RUNNING=`ps ax | grep java | grep "org.eclipse.equinox"`

if [ -z "$KURA_RUNNING" ] ; then
        exec python3 -I "${DIR}/bin/kura_key_store.py" exec-java -Xms@kura.mem.size@ -Xmx@kura.mem.size@ \
        -Xlog:gc*:file=log/kura-gc.log:time:filecount=10,filesize=100m \
        -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=log/kura-heapdump.hprof \
        -XX:ErrorFile=log/kura-error.log \
        -XX:+IgnoreUnrecognizedVMOptions \
        --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
        --add-modules=ALL-SYSTEM \
        -Xdebug -Xrunjdwp:server=y,transport=dt_socket,address=*:8000,suspend=n \
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
        -Dosgi.console \
        -Declipse.consoleLog=true \
        -jar ${DIR}/plugins/org.eclipse.equinox.launcher-@org.eclipse.equinox.launcher.version@.jar \
        -configuration  /tmp/.kura/configuration
else
        echo "Failed to start Kura. It is already running ..."
fi
