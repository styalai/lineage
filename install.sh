#!/usr/bin/env bash
#
# lineage installer
# Usage:  curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/install.sh | bash
#         LINEAGE_VERSION=v0.1.0 curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/install.sh | bash
#         bash install.sh /path/to/local/tarball.tar.gz
#
# Defaults (overridable via env):
#   LINEAGE_REPO    GitHub "<owner>/<repo>" hosting the source tarballs
#   LINEAGE_VERSION "latest" (default) or "vX.Y.Z"
#   LINEAGE_HOME    install root for the source tree (default: $HOME/.lineage)
#   LINEAGE_BIN_DIR where the `lineage` launcher is written (default: $HOME/.local/bin)
#
set -euo pipefail

# -----------------------------------------------------------------------------
# Defaults & argument parsing
# -----------------------------------------------------------------------------
LINEAGE_REPO="${LINEAGE_REPO:-styalai/lineage}"
LINEAGE_VERSION="${LINEAGE_VERSION:-latest}"
LINEAGE_HOME="${LINEAGE_HOME:-$HOME/.lineage}"
LINEAGE_BIN_DIR="${LINEAGE_BIN_DIR:-$HOME/.local/bin}"

LOCAL_TARBALL=""
if [ "${1:-}" != "" ] && [ "${1:-}" != "-" ]; then
    LOCAL_TARBALL="$1"
fi

# -----------------------------------------------------------------------------
# Pretty output (no color if not a tty)
# -----------------------------------------------------------------------------
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    CYAN=$'\033[36m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; GREEN=""; YELLOW=""; CYAN=""; RED=""; RESET=""
fi
info()    { printf "%blineage:%b %s\n" "$CYAN" "$RESET" "$*"; }
success() { printf "%b✓%b %s\n" "$GREEN" "$RESET" "$*"; }
warn()    { printf "%b!%b %s\n" "$YELLOW" "$RESET" "$*" >&2; }
fail()    { printf "%b✗%b %s\n" "$RED" "$RESET" "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Platform detection
# -----------------------------------------------------------------------------
OS_RAW="$(uname -s 2>/dev/null || echo unknown)"
case "$OS_RAW" in
    Linux*)  PLATFORM=linux ;;
    Darwin*) PLATFORM=macos ;;
    MINGW*|MSYS*|CYGWIN*) fail "Windows detected — use install.ps1 instead." ;;
    *)       fail "Unsupported OS: $OS_RAW" ;;
esac

ARCH_RAW="$(uname -m 2>/dev/null || echo unknown)"
case "$ARCH_RAW" in
    x86_64|amd64)  ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *)             warn "Unknown arch '$ARCH_RAW'; proceeding anyway."; ARCH="$ARCH_RAW" ;;
esac

# -----------------------------------------------------------------------------
# Find a Python 3.11+ interpreter
# -----------------------------------------------------------------------------
find_python() {
    for cand in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            PYPATH="$(command -v "$cand")"
            VERSION="$("$PYPATH" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
            case "$VERSION" in
                3.1[1-9]|3.[2-9].*|3.[1-9][0-9].*)
                    echo "$PYPATH"
                    return 0
                    ;;
            esac
        fi
    done
    return 1
}

PYTHON="$(find_python)" || fail "Python 3.11+ not found on PATH. Install Python 3.11+ and retry."
PYTHON_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
info "found Python $PYTHON_VERSION at $PYTHON"

# -----------------------------------------------------------------------------
# Resolve version (latest or explicit)
# -----------------------------------------------------------------------------
resolve_version() {
    if [ "$LINEAGE_VERSION" != "latest" ]; then
        echo "$LINEAGE_VERSION"
        return 0
    fi
    if [ -n "$LOCAL_TARBALL" ]; then
        # Try to extract a version from the tarball filename.
        # Accepted shapes:
        #   lineage-0.1.0.tar.gz         -> 0.1.0
        #   lineage-v0.1.0.tar.gz        -> v0.1.0
        #   lineage-0.1.0-rc1.tar.gz     -> 0.1.0-rc1
        local base
        base="$(basename "$LOCAL_TARBALL")"
        local parsed
        # Extended regex (-E) — cleaner than escaping every backslash.
        # Accepts:  lineage-0.1.0.tar.gz, lineage-v0.1.0.tar.gz,
        #           lineage-0.1.0-rc1.tar.gz, lineage-0.1.0.tar.bz2
        parsed="$(printf '%s' "$base" | sed -nE 's/^lineage-(v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]*)?)\.tar(\.gz|\.bz2|\.xz|\.zst)?$/\1/p' | head -n1)"
        if [ -n "$parsed" ]; then
            echo "$parsed"
            return 0
        fi
        echo "local"
        return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl is required to resolve 'latest'. Set LINEAGE_VERSION=vX.Y.Z or pass a local tarball."
    fi
    local url="https://api.github.com/repos/$LINEAGE_REPO/releases/latest"
    local tag
    tag="$(curl -fsSL "$url" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)" || true
    if [ -z "$tag" ]; then
        # Fallback: latest tag via git ls-remote
        tag="$(curl -fsSL "https://api.github.com/repos/$LINEAGE_REPO/tags?per_page=1" 2>/dev/null \
            | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -n1)" || true
    fi
    if [ -z "$tag" ]; then
        fail "Could not resolve 'latest' version: no GitHub releases or tags found for $LINEAGE_REPO. Publish a release, set LINEAGE_VERSION=vX.Y.Z, or install from a local checkout (tar it as lineage-0.1.0.tar.gz and run ./install.sh lineage-0.1.0.tar.gz)."
    fi
    echo "$tag"
}

VERSION_TAG="$(resolve_version)"
info "installing lineage $VERSION_TAG"

# -----------------------------------------------------------------------------
# Fetch the source
# -----------------------------------------------------------------------------
WORKDIR="$LINEAGE_HOME/$VERSION_TAG"
mkdir -p "$WORKDIR" "$LINEAGE_BIN_DIR"

if [ -n "$LOCAL_TARBALL" ]; then
    info "extracting local tarball: $LOCAL_TARBALL"
    tar -xz -f "$LOCAL_TARBALL" -C "$WORKDIR" --strip-components=1
else
    TAR_URL="https://github.com/$LINEAGE_REPO/archive/refs/tags/$VERSION_TAG.tar.gz"
    info "downloading $TAR_URL"
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl is required."
    fi
    TMP_TAR="$(mktemp -t lineage.XXXXXX.tar.gz)"
    trap 'rm -f "$TMP_TAR"' EXIT
    curl -fsSL "$TAR_URL" -o "$TMP_TAR" || fail "Download failed. Check that the tag exists and is public."
    tar -xz -f "$TMP_TAR" -C "$WORKDIR" --strip-components=1
    rm -f "$TMP_TAR"
    trap - EXIT
fi

# Sanity check: the extracted tree must contain the package
if [ ! -d "$WORKDIR/lineage" ]; then
    fail "Extracted tree is missing the 'lineage/' package. Is $VERSION_TAG a valid release?"
fi

# -----------------------------------------------------------------------------
# Write the launcher
# -----------------------------------------------------------------------------
LAUNCHER="$LINEAGE_BIN_DIR/lineage"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Auto-generated by the lineage installer. Do not edit.
# To update or remove, re-run the installer or use:  $LINEAGE_BIN_DIR/lineage uninstall
set -e

WORKDIR="$WORKDIR"
PYTHON="$PYTHON"

if [ ! -d "\$WORKDIR" ] || [ ! -d "\$WORKDIR/lineage" ]; then
    echo "lineage: install at \$WORKDIR is missing or corrupted." >&2
    echo "lineage: re-run the installer to repair:  curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/install.sh | bash" >&2
    exit 1
fi

if [ ! -x "\$PYTHON" ]; then
    echo "lineage: Python interpreter \$PYTHON is missing." >&2
    exit 1
fi

export PYTHONPATH="\$WORKDIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\$PYTHON" -m lineage "\$@"
EOF
chmod +x "$LAUNCHER"

# Record the active version so future updates can find it
echo "$VERSION_TAG" > "$LINEAGE_HOME/.current"

# -----------------------------------------------------------------------------
# PATH advice
# -----------------------------------------------------------------------------
ensure_path() {
    case ":$PATH:" in
        *":$LINEAGE_BIN_DIR:"*) return 0 ;;
    esac
    warn "$LINEAGE_BIN_DIR is not on your PATH."
    SHELL_NAME="$(basename "${SHELL:-/bin/sh}")"
    case "$SHELL_NAME" in
        zsh)  RC="$HOME/.zshrc" ;;
        bash) RC="$HOME/.bashrc" ;;
        fish) RC="$HOME/.config/fish/config.fish" ;;
        *)    RC="" ;;
    esac
    # Use the resolved LINEAGE_BIN_DIR (not the raw $HOME/.local/bin) so the
    # advice matches where the launcher was actually written.
    if [ "$LINEAGE_BIN_DIR" = "$HOME/.local/bin" ]; then
        PATH_LINE="export PATH=\"\$HOME/.local/bin:\$PATH\""
    else
        PATH_LINE="export PATH=\"$LINEAGE_BIN_DIR:\$PATH\""
    fi
    if [ -n "$RC" ]; then
        if [ -w "$RC" ] || ([ ! -e "$RC" ] && [ -w "$(dirname "$RC")" ]); then
            {
                echo ""
                echo "# Added by lineage installer"
                echo "$PATH_LINE"
            } >> "$RC"
            success "added $LINEAGE_BIN_DIR to PATH in $RC (open a new shell to take effect)"
        else
            warn "could not auto-edit $RC. Add this line manually:"
            warn "  $PATH_LINE"
        fi
    else
        warn "add this to your shell init file:"
        warn "  $PATH_LINE"
    fi
}
ensure_path

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
success "lineage $VERSION_TAG installed"
printf "  %bbinary%b    %s\n" "$DIM" "$RESET" "$LAUNCHER"
printf "  %binstalled%b %s\n" "$DIM" "$RESET" "$WORKDIR"
printf "  %bpython%b   %s (%s)\n" "$DIM" "$RESET" "$PYTHON" "$PYTHON_VERSION"
printf "  %bplatform%b %s/%s\n" "$DIM" "$RESET" "$PLATFORM" "$ARCH"
echo
printf "%bNext:%b open a new shell (or \`source ~/.zshrc\`) and run \`lineage --help\`.\n" "$BOLD" "$RESET"
