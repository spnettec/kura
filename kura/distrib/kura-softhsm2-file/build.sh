#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
target=$1
revision=$2
case "$revision" in
    ''|*[!0-9]*) printf '%s\n' 'Expected a numeric Debian package revision.' >&2; exit 2 ;;
esac
arch=$(dpkg --print-architecture)
case "$arch" in
    arm64|amd64) ;;
    *) printf 'Unsupported SoftHSM package architecture: %s\n' "$arch" >&2; exit 2 ;;
esac

package=kura-softhsm2-file
version="2.6.1+gitb6388cf372-$revision"
source=src/SoftHSMv2-2.6.1.tar.gz
source_commit=670e97dfc0d7233e841544b8462a32aabcbfbec3
export SOURCE_DATE_EPOCH=1795566474
cd "$here"
sha256sum -c source.sha256
test "$(gzip -dc "$source" | git get-tar-commit-id)" = "$source_commit"
mkdir -p "$target"
work=$(mktemp -d "$target/.softhsm2-build.XXXXXX")
trap 'rm -rf -- "$work"' EXIT

tar -xzf "$source" -C "$work"
cmake -S "$work/SoftHSMv2-2.6.1" -B "$work/build" -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_GOST=OFF -DENABLE_P11_KIT=OFF -DENABLE_EDDSA=ON -DBUILD_TESTS=ON -DENABLE_STRICT=OFF \
    -DDEFAULT_SOFTHSM2_CONF=/etc/kura/softhsm2-file.conf \
    "-DCMAKE_CXX_FLAGS=-ffile-prefix-map=$work=/usr/src/$package" \
    "-DCMAKE_C_FLAGS=-ffile-prefix-map=$work=/usr/src/$package"
cmake --build "$work/build" --parallel 2
OPENSSL_CONF="$here/ctest-openssl.conf" ctest --test-dir "$work/build" --output-on-failure --timeout 100

binary="$work/build/src/lib/libsofthsm2.so"
root="$work/debian/$package"
libdir=/usr/lib/kura-pkcs11/softhsm2
docdir="/usr/share/doc/$package"
install -d -m 0755 "$work/debian" "$root/DEBIAN" "$root$libdir" "$root$docdir"
cat > "$work/debian/control" <<EOF
Source: $package
Section: admin
Priority: optional
Maintainer: Eclipse Kura Developers <kura-dev@eclipse.org>

Package: $package
Architecture: any
Description: Optional Kura SoftHSM file-token module
EOF
install -m 0644 "$binary" "$root$libdir/libsofthsm2.so"
depends=$(cd "$work" && dpkg-shlibdeps -O -e "debian/$package$libdir/libsofthsm2.so")
depends=${depends#shlibs:Depends=}
test -n "$depends"
cat > "$root/DEBIAN/control" <<EOF
Package: $package
Version: $version
Architecture: $arch
Section: admin
Priority: optional
Maintainer: Eclipse Kura Developers <kura-dev@eclipse.org>
Depends: $depends
Description: Optional Kura SoftHSM file-token module
 Linux file-token module with original file identity and recovery.
 Select this module explicitly in a Kura PKCS#11 keystore configuration.
EOF
install -m 0644 "$work/SoftHSMv2-2.6.1/LICENSE" "$root$docdir/copyright"
install -m 0644 "$here/README.md" "$root$docdir/README.md"
{
    printf 'SoftHSM-Source-Commit: %s\n' "$source_commit"
    printf 'SoftHSM-Native-Revision: b6388cf372faa376c9c9056b80c70455fb06e54f\n'
    printf 'Source-Archive-SHA256: %s\n' "$(cut -d ' ' -f 1 "$here/source.sha256")"
    printf 'Module-SHA256: %s\n' "$(sha256sum "$binary" | cut -d ' ' -f 1)"
} > "$root$docdir/build-origin"
(cd "$root" && find usr -type f -print0 | LC_ALL=C sort -z | xargs -0 md5sum > DEBIAN/md5sums)

output="$target/${package}_${version}_${arch}.deb"
dpkg-deb --build --root-owner-group "$root" "$work/assembled.deb"
mv -f "$work/assembled.deb" "$output"
sha256sum "$output"
