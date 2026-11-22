#!/bin/sh
#
#  Copyright (c) 2011, 2026 Eurotech and/or its affiliates and others
#
#  This program and the accompanying materials are made
#  available under the terms of the Eclipse Public License 2.0
#  which is available at https://www.eclipse.org/legal/epl-2.0/
#
#  SPDX-License-Identifier: EPL-2.0
#
#  Contributors:
#   Eurotech
#

set -eu

package=$1
output=$2
template=$(dirname "$0")/extract.sh
checksum=$(python3 - "$package" <<'PYTHON'
import hashlib
import sys

with open(sys.argv[1], "rb") as package:
    print(hashlib.file_digest(package, "sha256").hexdigest())
PYTHON
)
temporary=$(mktemp "${output}.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
sed "s/@CORE_DEB_SHA256@/$checksum/" "$template" > "$temporary"
cat "$package" >> "$temporary"
chmod +x "$temporary"
mv -f -- "$temporary" "$output"
