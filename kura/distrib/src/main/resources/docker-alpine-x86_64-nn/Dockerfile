ARG base_image_version=latest
FROM base-kura-docker:${base_image_version} AS kura_base
FROM alpine:latest

MAINTAINER Eclipse Kura Developers <kura-dev@eclipse.org>
LABEL maintainer="Eclipse Kura Developers <kura-dev@eclipse.org>" \
      io.k8s.description="Containerized version of the Eclipse Kura™ IoT gateway" \
      io.openshift.non-scalable=true


COPY bin/ /usr/local/bin/

COPY --from=kura_base /kura-install/kura_*_docker-x86_64-nn_installer.sh /kura-install/
COPY --from=kura_base /kura-install/*.dp /kura-install/

ENV \
  JAVA_HOME=/usr/lib/jvm/default-jvm \
  KURA_DIR=/opt/eclipse/kura \
  LAUNCHER_VERSION="1.6.500.v20230717-2134" 



RUN chmod a+x -R /usr/local/bin && \
    apk update && \
    apk --no-cache add openjdk21 bash zip curl gcompat procps unzip gzip tar && \
    apk --no-cache add dos2unix openssl net-tools which busybox-extras && \
    apk --no-cache add bluez bluez-deprecated chrony eudev glib psmisc socat dmidecode && \
    /kura-install/kura_*_docker-x86_64-nn_installer.sh && \
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
    dp-install-local "/kura-install/yofc-iot-repack-vertx-db_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-api-comp_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-comp_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-opcuaserver_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-influxdb_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-influxdbv1_0.0.1-SNAPSHOT.dp" && \
    # dp-install "https://repo1.maven.org/maven2/de/dentrassi/kura/addons/de.dentrassi.kura.addons.utils.fileinstall/0.6.0/de.dentrassi.kura.addons.utils.fileinstall-0.6.0.dp" && \
    # add-config-ini "felix.fileinstall.disableNio2=true" && \
    # add-config-ini "felix.fileinstall.dir=/load" && \
    rm -Rf /kura-install &&\
    pack-kura

EXPOSE 443

VOLUME ["/load"]

ENTRYPOINT ["/usr/local/bin/kura-entry-point"]
