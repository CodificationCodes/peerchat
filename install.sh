#!/usr/bin/env bash
# Peer Chat installer — sets up an isolated environment so it never fights
# with your system Python, then installs the `peerchat` command.
set -e

REPO_URL="https://github.com/CodificationCodes/peerchat.git"
INSTALL_DIR="$HOME/.peerchat"

echo "Installing Peer Chat..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but wasn't found. Install Python 3.9+ first."
    exit 1
fi

# Prefer pipx if it's available — it handles isolation automatically and
# avoids the "externally-managed-environment" error on newer Debian/Ubuntu.
if command -v pipx >/dev/null 2>&1; then
    echo "Using pipx..."
    pipx install --force "git+${REPO_URL}"
    echo ""
    echo "Done! Run it with: peerchat"
    exit 0
fi

echo "pipx not found, falling back to a dedicated virtual environment..."

rm -rf "$INSTALL_DIR"
git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1 \
    || { echo "git clone failed. Is git installed?"; exit 1; }

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q "$INSTALL_DIR"

# Symlink a launcher onto PATH so `peerchat` works from anywhere.
LINK_DIR="$HOME/.local/bin"
mkdir -p "$LINK_DIR"
ln -sf "$INSTALL_DIR/venv/bin/peerchat" "$LINK_DIR/peerchat"

echo ""
echo "Done! Installed to $INSTALL_DIR"
if [[ ":$PATH:" != *":$LINK_DIR:"* ]]; then
    echo ""
    echo "$LINK_DIR isn't on your PATH yet. Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "Then restart your terminal, or run this once now:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
echo "Run it with: peerchat"
