ARG base_image_version=latest
FROM base-kura-docker:${base_image_version} AS kura_base
FROM registry.access.redhat.com/ubi8/ubi-minimal:latest

MAINTAINER Eclipse Kura Developers <kura-dev@eclipse.org>
LABEL maintainer="Eclipse Kura Developers <kura-dev@eclipse.org>" \
      io.k8s.description="Containerized version of the Eclipse Kura™ IoT gateway" \
      io.openshift.non-scalable=true


COPY bin/ /usr/local/bin/

COPY --from=kura_base /kura-install/kura_*_docker-x86_64-nn_installer.sh /kura-install/
COPY --from=kura_base /kura-install/*.dp /kura-install/

ENV \
  KURA_DIR=/opt/eclipse/kura \
  JAVA_HOME=/usr/lib/jvm/jre-17-openjdk \
  SKIP_JAVA_VERSION_CHECK=true \
  LAUNCHER_VERSION="1.6.400.v20210924-0641" \
  TZ=Asia/Shanghai \
  LANG=en_US.UTF-8

RUN true && \
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm && \
    microdnf -y update && \
    microdnf -y install \
        java-17-openjdk-headless \
        java-11-openjdk-headless \
        procps \
        zip \
        unzip \
        gzip \
        tar \
        psmisc \
        socat \
        dos2unix \
        openssl \
        net-tools \
        dmidecode \
        hostname \
        which \
        findutils \
    && \
    microdnf -y clean all && rm -rf /var/cache/yum && \
    /kura-install/kura_*_docker-x86_64-nn_installer.sh && rm -rf /kura-install/ && \
    chmod -R go-rwx /opt/eclipse  && \
    chmod a+rx /opt/eclipse  && \
    find /opt/eclipse -type d | xargs chmod a+x && \
    chmod a+rwx /var/log && \
    `# Test for the existence of the entry point` \
    test -x "${KURA_DIR}/bin/start_kura.sh" && \
    chmod a+x -R /usr/local/bin/ && \
    install -m 0777 -d "${KURA_DIR}/data" && \
    mkdir -p ${KURA_DIR}/packages && \
    if [ "$PACKED" == "true" ]; then touch /kura.packed && sh pack-kura; fi  && \
    chmod +x /usr/local/bin/*  && \
    unpack-kura  && \
    export JAVA_HOME="/usr/lib/jvm/jre-11-openjdk" && \
    export PATH=$JAVA_HOME/bin:$PATH && \
    export CLASSPATH=.:$JAVA_HOME/lib/dt.jar:$JAVA_HOME/lib/tools.jar && \
    dp-install-local "/kura-install/yofc-iot-repack-vertx-db_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-api-comp_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-comp_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-opcuaserver_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-influxdb_0.0.1-SNAPSHOT.dp" && \
    dp-install-local "/kura-install/yofc-iot-apps-influxdbv1_0.0.1-SNAPSHOT.dp" && \
    # add-config-ini "felix.fileinstall.disableNio2=true" && \
    # add-config-ini "felix.fileinstall.dir=/load" && \
    rm -rf /kura-install/ && \
    microdnf -y remove java-11-openjdk-headless && \
    microdnf -y clean all && rm -rf /var/cache/yum && \
    pack-kura

EXPOSE 443
EXPOSE 1883
EXPOSE 8088

VOLUME ["/load","/opt/eclipse"]

ENTRYPOINT ["/usr/local/bin/kura-entry-point"]
