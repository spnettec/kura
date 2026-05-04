ARG base_image_version=latest
FROM base-kura-docker:${base_image_version} AS kura_base
FROM alpine:latest

MAINTAINER Eclipse Kura Developers <kura-dev@eclipse.org>
LABEL maintainer="Eclipse Kura Developers <kura-dev@eclipse.org>" \
      io.k8s.description="Containerized version of the Eclipse Kura™ IoT gateway" \
      io.openshift.non-scalable=true


COPY bin/ /usr/local/bin/

COPY --from=kura_base /kura-install/kura_*_docker-nn_installer.sh /kura-install/
# Copy entire /kura-install/ tree so the COPY succeeds even when no .dp files
# were staged (i.e. -Ddist.dp.skip=true / default). Files duplicated by the
# previous COPY are harmless overwrites.
COPY --from=kura_base /kura-install/ /kura-install/

ENV \
  KURA_DIR=/opt/eclipse/kura \
  LAUNCHER_VERSION="1.7.100" 



RUN set -ex; \
    apk_retry() { \
        for attempt in 1 2 3 4 5; do \
            apk "$@" && return 0; \
            sleep "$((attempt * 2))"; \
        done; \
        apk "$@"; \
    }; \
    chmod a+x -R /usr/local/bin && \
    apk_retry update && \
    apk_retry --no-cache add openjdk21-jre bash zip curl gcompat procps unzip gzip tar && \
    apk_retry --no-cache add dos2unix openssl net-tools which busybox-extras && \
    apk_retry --no-cache add bluez bluez-deprecated chrony eudev glib psmisc socat && \
    apk_retry --no-cache add shadow && \
    /kura-install/kura_*_docker-nn_installer.sh && \
    chmod -R go-rwx /opt/eclipse  && \
    chmod a+rx /opt/eclipse  && \
    find /opt/eclipse -type d | xargs chmod a+x && \
    chmod a+rwx /var/log && \
    `# Test for the existence of the entry point` \
    test -x "${KURA_DIR}/bin/start_kura.sh"&& \
    chmod a+x /usr/local/bin/* && \
    cd /root && \
    rm -Rf /context /kura /root/.m2 && \
    install -m 0777 -d "${KURA_DIR}/data" && \
    ln -s /bin/bash /usr/bin/bash && \
    mkdir -p ${KURA_DIR}/packages && \
    if [ "$PACKED" == "true" ]; then touch /kura.packed && pack-kura; fi && \
    unpack-kura && \
    sed -i "s/\-printf \'\%P.n\'//g" /usr/local/bin/dp-install && \
    for dp in \
        yofc-iot-repack-vertx-db-0.0.1-SNAPSHOT.dp \
        yofc-iot-api-comp-0.0.1-SNAPSHOT.dp \
        yofc-iot-apps-comp-0.0.1-SNAPSHOT.dp \
        yofc-iot-apps-opcuaserver-0.0.1-SNAPSHOT.dp \
        yofc-iot-apps-influxdb-0.0.1-SNAPSHOT.dp \
        yofc-iot-apps-influxdbv1-0.0.1-SNAPSHOT.dp; do \
        if [ -f "/kura-install/$dp" ]; then dp-install-local "/kura-install/$dp"; fi; \
    done && \
    # dp-install "https://repo1.maven.org/maven2/de/dentrassi/kura/addons/de.dentrassi.kura.addons.utils.fileinstall/0.6.0/de.dentrassi.kura.addons.utils.fileinstall-0.6.0.dp" && \
    add-config-ini "felix.fileinstall.disableNio2=true" && \
    add-config-ini "felix.fileinstall.dir=/load" && \
    rm -Rf /kura-install &&\
    pack-kura

EXPOSE 443

VOLUME ["/load"]

ENTRYPOINT ["/usr/local/bin/kura-entry-point"]
