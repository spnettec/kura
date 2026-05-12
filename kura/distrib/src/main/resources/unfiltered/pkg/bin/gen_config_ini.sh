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

# Conflict log:
#  - kura-core's jars are inviolable (first pass, always added, never overridden).
#  - Siblings are loaded in the order recorded in framework/sibling-install-order
#    (one directory name per line, append-on-install, delete-line-on-remove).
#  - Within siblings, first-installed wins: later siblings with the same JAR
#    basename are skipped and reported.
CONFLICT_LOG_DIR="/var/log/kura"
CONFLICT_LOG="${CONFLICT_LOG_DIR}/sibling-bundle-conflict.log"

log_conflict() {
    MSG="$1"
    >&2 echo "[gen_config_ini] ${MSG}"
    [ -d "${CONFLICT_LOG_DIR}" ] || mkdir -p "${CONFLICT_LOG_DIR}" 2>/dev/null || return 0
    TS=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "?")
    printf '%s %s\n' "${TS}" "${MSG}" >> "${CONFLICT_LOG}" 2>/dev/null || true
}

# Dedup tracking (POSIX sh, no associative arrays). SEEN_JARS records which JAR
# basenames have already been added; SEEN_LOCATIONS records where each one came
# from, so a later conflict can name the first-kept source.
SEEN_JARS=""
SEEN_LOCATIONS=""

is_seen() {
    case "${SEEN_JARS}" in
        *"|${1}|"*) return 0 ;;
        *) return 1 ;;
    esac
}

mark_seen() {
    SEEN_JARS="${SEEN_JARS}|${1}|"
    SEEN_LOCATIONS="${SEEN_LOCATIONS}|${1}=${2}|"
}

first_location() {
    case "${SEEN_LOCATIONS}" in
        *"|${1}="*)
            _rest="${SEEN_LOCATIONS#*|${1}=}"
            echo "${_rest%%|*}"
            ;;
    esac
}

is_level_dir() {
    # $1 = directory basename. Valid: 1, 1s, 2, 2s, ..., 9, 9s, etc.
    [ -n "$1" ] && [ "${#1}" -le 2 ] && expr "$1" : '[0-9]\{1,\}s\{0,1\}$' > /dev/null
}

OSGI_BUNDLES=""

append_bundle() {
    # $1 = jar path, $2 = level dir basename
    _jar="$1"
    _dn="$2"
    _start_level="${_dn%s}"
    if [ "${#_dn}" = "${#_start_level}" ]; then
        _start=""
    else
        _start="\\:start"
    fi
    [ -f "${_jar}" ] || return 0
    if [ -n "${OSGI_BUNDLES}" ]; then
        OSGI_BUNDLES="${OSGI_BUNDLES},"
    fi
    OSGI_BUNDLES="${OSGI_BUNDLES}reference\\:file\\:${_jar}@${_start_level}${_start}"
}

# === First pass: kura-core plugins/ (inviolable) ===
for DIR_PATH in "${ROOT}"/*
do
    DIR_NAME=$(basename -- "${DIR_PATH}")
    [ -d "${DIR_PATH}" ] || continue
    is_level_dir "${DIR_NAME}" || continue

    for JAR in "${DIR_PATH}"/*.jar
    do
        [ -f "${JAR}" ] || continue
        JAR_BASENAME=$(basename -- "${JAR}")
        append_bundle "${JAR}" "${DIR_NAME}"
        mark_seen "${JAR_BASENAME}" "kura-core:plugins/${DIR_NAME}"
    done
done

# === Second pass: siblings, in install order ===
if [ -n "${SIBLING_ROOT}" ] && [ -d "${SIBLING_ROOT}" ]
then
    SIBLING_ROOT=$(abspath "${SIBLING_ROOT}")
    INSTALL_ORDER_FILE="${ROOT}/../framework/sibling-install-order"

    ORDERED_SIBLINGS=""

    # Read registered siblings in install order. Skip blank lines, comments,
    # and entries whose directory no longer exists (sibling dpkg-removed but
    # registry not yet purged).
    if [ -f "${INSTALL_ORDER_FILE}" ]; then
        while IFS= read -r LINE || [ -n "${LINE}" ]
        do
            [ -z "${LINE}" ] && continue
            case "${LINE}" in
                \#*) continue ;;
            esac
            [ -d "${SIBLING_ROOT}/${LINE}" ] || continue
            ORDERED_SIBLINGS="${ORDERED_SIBLINGS} ${LINE}"
        done < "${INSTALL_ORDER_FILE}"
    fi

    # Append any on-disk siblings not in the registry, with a warning.
    # Covers manual / dev installs and registry drift; preserves discovery.
    for SIBLING_DIR in "${SIBLING_ROOT}"/*/
    do
        [ -d "${SIBLING_DIR}" ] || continue
        NAME=$(basename "${SIBLING_DIR}")
        case " ${ORDERED_SIBLINGS} " in
            *" ${NAME} "*) ;;
            *)
                log_conflict "sibling '${NAME}' not in install-order registry; loading last"
                ORDERED_SIBLINGS="${ORDERED_SIBLINGS} ${NAME}"
                ;;
        esac
    done

    # Iterate siblings in registered order. Inside each sibling, iterate level
    # dirs numerically (shell glob order, e.g. 3 3s 4 4s 5 5s 6 6s).
    for NAME in ${ORDERED_SIBLINGS}
    do
        SIBLING_DIR="${SIBLING_ROOT}/${NAME}"
        for DIR_PATH in "${SIBLING_DIR}"/*
        do
            DIR_NAME=$(basename -- "${DIR_PATH}")
            [ -d "${DIR_PATH}" ] || continue
            is_level_dir "${DIR_NAME}" || continue

            for JAR in "${DIR_PATH}"/*.jar
            do
                [ -f "${JAR}" ] || continue
                JAR_BASENAME=$(basename -- "${JAR}")

                if is_seen "${JAR_BASENAME}"
                then
                    FIRST=$(first_location "${JAR_BASENAME}")
                    log_conflict "duplicate ${JAR_BASENAME} at siblings/${NAME}/${DIR_NAME}/; first kept at ${FIRST}"
                    continue
                fi

                append_bundle "${JAR}" "${DIR_NAME}"
                mark_seen "${JAR_BASENAME}" "siblings/${NAME}/${DIR_NAME}"
            done
        done
    done
fi

cat "${TEMPLATE}"
echo
echo "osgi.bundles=${OSGI_BUNDLES}"
