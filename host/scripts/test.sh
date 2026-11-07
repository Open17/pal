#!/usr/bin/env bash
# Run the host tests. With only the command line tools installed, the test
# framework lives outside the default search paths.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

frameworks=/Library/Developer/CommandLineTools/Library/Developer/Frameworks
libraries=/Library/Developer/CommandLineTools/Library/Developer/usr/lib
if [[ -d $frameworks && ! -d /Applications/Xcode.app ]]; then
    exec swift test \
        -Xswiftc -F -Xswiftc "$frameworks" \
        -Xlinker -F -Xlinker "$frameworks" \
        -Xlinker -rpath -Xlinker "$frameworks" \
        -Xlinker -rpath -Xlinker "$libraries" \
        "$@"
fi
exec swift test "$@"
