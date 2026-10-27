#!/bin/bash
set -u
cd "$HOME/unixnu-marble8796-build/xnu"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
{
  echo "FBCON_GOP_BUILD"
  echo "XCODE $(xcode-select -p)"
  make install -j4 SDKROOT=macosx \
    TARGET_CONFIGS="DEVELOPMENT ARM64 MARBLE" \
    ARCH_CONFIGS=ARM64 \
    SRCROOT="$HOME/unixnu-marble8796-build/xnu" \
    OBJROOT="$HOME/unixnu-marble8796-build/kernel.obj" \
    SYMROOT="$HOME/unixnu-marble8796-build/kernel.sym" \
    DSTROOT="$HOME/unixnu-marble8796-build/fakeroot" \
    FAKEROOT_DIR="$HOME/unixnu-marble8796-build/fakeroot" \
    BUILD_WERROR=0 \
    RC_DARWIN_KERNEL_VERSION=22.6.0 \
    KERNEL_BUILDS_IN_PARALLEL=1 \
    BUILD_LTO=0 \
    CONCISE=0 \
    BUILD_JSON_COMPILATION_DATABASE=0 \
    BUILD_DSYM=0 \
    IIG="$HOME/unixnu-marble-kit/legacy-iig8796.py" \
    RC_NONARCH_CFLAGS="-Wno-reserved-identifier -Wno-pre-c11-compat -Wno-pre-c23-compat"
  echo BUILD_EXIT:$?
} > "$HOME/unixnu-marble8796-build/display-match-build.log" 2>&1
