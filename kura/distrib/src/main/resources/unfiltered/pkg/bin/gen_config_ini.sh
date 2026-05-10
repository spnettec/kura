#!/bin/sh

TEMPLATE=$1
ROOT=$2
SIBLING_ROOT="${3:-}"

usage() {
    >&2 echo "Usage: gen_config_ini.sh <config.ini template> <plugin root directory> [sibling root directory]"
}

abspath() {
    cd "${1}" || exit 1
    RESULT="${PWD}"
    cd "${OLDPWD}" || exit 1
    echo "${RESULT}"
}

if ! [ -e "${TEMPLATE}" ]
then
    >&2 echo "config.ini template not found"
    usage
    exit 1
fi

if ! [ -d "${ROOT}" ]
then
    >&2 echo "plugin root directory not found"
    usage
    exit 1
fi

ROOT=$(abspath "${ROOT}")

# JAR deduplication tracking (POSIX sh, no associative arrays)
SEEN_JARS=""
is_seen() {
    case "${SEEN_JARS}" in
        *"|${1}|"*) return 0 ;;
        *) return 1 ;;
    esac
}
mark_seen() {
    SEEN_JARS="${SEEN_JARS}|${1}|"
}

# Determine precedence strategy
PRECEDENCE="kura-first"
if [ -f "${ROOT}/../framework/sibling-precedence.conf" ]; then
    _p=$(grep '^precedence=' "${ROOT}/../framework/sibling-precedence.conf" 2>/dev/null | head -1 | cut -d= -f2)
    case "${_p}" in
        sibling-override) PRECEDENCE="sibling-override" ;;
    esac
fi

OSGI_BUNDLES=""

# First pass: scan kura-core plugin directories
for DIR_PATH in "${ROOT}"/*
do
    DIR_NAME=$(basename -- "${DIR_PATH}")

    if [ "${#DIR_NAME}" = 0 ] || [ "${#DIR_NAME}" -gt 2 ] || ! [ -d "${DIR_PATH}" ]
    then
        continue
    fi

    if ! expr "${DIR_NAME}" : '[0-9]\{1,\}s\{0,1\}$' > /dev/null
    then
        continue
    fi

    START_LEVEL="${DIR_NAME%s}"

    if [ "${#DIR_NAME}" = "${#START_LEVEL}" ]
    then
        START=
    else
        START="\:start"
    fi

    for JAR in "${DIR_PATH}"/*.jar
    do
        JAR_BASENAME=$(basename -- "${JAR}")
        if [ -n "${OSGI_BUNDLES}" ]; then
            OSGI_BUNDLES="${OSGI_BUNDLES},"
        fi
        if test -f "$JAR"
        then
            OSGI_BUNDLES="${OSGI_BUNDLES}reference\:file\:${JAR}@${START_LEVEL}${START}"
        fi
        mark_seen "${JAR_BASENAME}"
    done
done

# Second pass: scan sibling addon directories
if [ -n "${SIBLING_ROOT}" ] && [ -d "${SIBLING_ROOT}" ]
then
    SIBLING_ROOT=$(abspath "${SIBLING_ROOT}")
    for SIBLING_DIR in "${SIBLING_ROOT}"/*/
    do
        [ -d "${SIBLING_DIR}" ] || continue
        for DIR_PATH in "${SIBLING_DIR}"/*
        do
            DIR_NAME=$(basename -- "${DIR_PATH}")

            if [ "${#DIR_NAME}" = 0 ] || [ "${#DIR_NAME}" -gt 2 ] || ! [ -d "${DIR_PATH}" ]
            then
                continue
            fi

            if ! expr "${DIR_NAME}" : '[0-9]\{1,\}s\{0,1\}$' > /dev/null
            then
                continue
            fi

            START_LEVEL="${DIR_NAME%s}"

            if [ "${#DIR_NAME}" = "${#START_LEVEL}" ]
            then
                START=
            else
                START="\:start"
            fi

            for JAR in "${DIR_PATH}"/*.jar
            do
                JAR_BASENAME=$(basename -- "${JAR}")

                if [ "${PRECEDENCE}" = "kura-first" ] && is_seen "${JAR_BASENAME}"
                then
                    continue
                fi

                if [ "${PRECEDENCE}" = "sibling-override" ] && is_seen "${JAR_BASENAME}"
                then
                    OSGI_BUNDLES=$(echo "${OSGI_BUNDLES}" | sed "s|reference\\\\:file\\\\:[^,]*${JAR_BASENAME}[^,]*,||g; s|,reference\\\\:file\\\\:[^,]*${JAR_BASENAME}[^,]*||g; s|^reference\\\\:file\\\\:[^,]*${JAR_BASENAME}[^,]*$||")
                fi

                if [ -n "${OSGI_BUNDLES}" ]; then
                    OSGI_BUNDLES="${OSGI_BUNDLES},"
                fi
                if test -f "$JAR"
                then
                    OSGI_BUNDLES="${OSGI_BUNDLES}reference\:file\:${JAR}@${START_LEVEL}${START}"
                fi
                mark_seen "${JAR_BASENAME}"
            done
        done
    done
fi

cat "${TEMPLATE}"
echo
echo "osgi.bundles=${OSGI_BUNDLES}"
