#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
work=$1
source=src/SoftHSMv2-2.6.1.tar.gz
source_commit=670e97dfc0d7233e841544b8462a32aabcbfbec3
export SOURCE_DATE_EPOCH=1795566474

cd "$here"
sha256sum -c source.sha256
test "$(gzip -dc "$source" | git get-tar-commit-id)" = "$source_commit"
tar -xzf "$source" -C "$work"
cmake -S "$work/SoftHSMv2-2.6.1" -B "$work/build" -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_GOST=OFF -DENABLE_P11_KIT=OFF -DENABLE_EDDSA=ON -DBUILD_TESTS=ON -DENABLE_STRICT=OFF \
    -DDEFAULT_SOFTHSM2_CONF=/etc/kura-pkcs11/softhsm2-file.conf \
    "-DCMAKE_CXX_FLAGS=-ffile-prefix-map=$work=/usr/src/kura-softhsm2-file" \
    "-DCMAKE_C_FLAGS=-ffile-prefix-map=$work=/usr/src/kura-softhsm2-file"
cmake --build "$work/build" --parallel 2
OPENSSL_CONF="$here/ctest-openssl.conf" ctest --test-dir "$work/build" --output-on-failure --timeout 100

{
    printf 'SoftHSM-Source-Commit: %s\n' "$source_commit"
    printf 'SoftHSM-Native-Revision: b6388cf372faa376c9c9056b80c70455fb06e54f\n'
    printf 'Source-Archive-SHA256: %s\n' "$(cut -d ' ' -f 1 "$here/source.sha256")"
    printf 'Module-SHA256: %s\n' "$(sha256sum "$work/build/src/lib/libsofthsm2.so" | cut -d ' ' -f 1)"
} > "$work/build-origin"
