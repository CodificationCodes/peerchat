#!/usr/bin/env bash
# Peer Chat installer — sets up an isolated environment so it never fights
# with your system Python, then installs the `peerchat` command and makes
# sure it's actually usable in every future terminal session (not just the
# one you installed it from).
set -e

REPO_URL="https://github.com/CodificationCodes/peerchat.git"
INSTALL_DIR="$HOME/.peerchat"
LINK_DIR="$HOME/.local/bin"
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

echo "Installing Peer Chat..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but wasn't found. Install Python 3.9+ first."
    exit 1
fi

# Adds PATH_LINE to a shell rc file exactly once, creating the file if it
# doesn't exist yet. Safe to call repeatedly (e.g. on reinstall/update) —
# it never adds a duplicate line.
add_path_line() {
    local rc_file="$1"
    if [ -f "$rc_file" ] && grep -qF "$PATH_LINE" "$rc_file" 2>/dev/null; then
        return
    fi
    mkdir -p "$(dirname "$rc_file")"
    {
        echo ""
        echo "# Added by the Peer Chat installer"
        echo "$PATH_LINE"
    } >> "$rc_file"
}

# Writes PATH_LINE into whichever shell config files are actually relevant
# for this user, based on their login shell — rather than just telling them
# to do it themselves. Covers both interactive-shell rc files (.bashrc,
# .zshrc) and login-shell profile files (.bash_profile/.profile, .zprofile),
# since macOS Terminal.app and many Linux terminals only read one or the
# other depending on how the shell was launched.
ensure_path_persisted() {
    case "$(basename "${SHELL:-}")" in
        zsh)
            add_path_line "$HOME/.zshrc"
            add_path_line "$HOME/.zprofile"
            ;;
        bash)
            add_path_line "$HOME/.bashrc"
            add_path_line "$HOME/.bash_profile"
            ;;
        fish)
            local fish_conf="$HOME/.config/fish/config.fish"
            if [ ! -f "$fish_conf" ] || ! grep -qF "$LINK_DIR" "$fish_conf" 2>/dev/null; then
                mkdir -p "$(dirname "$fish_conf")"
                {
                    echo ""
                    echo "# Added by the Peer Chat installer"
                    echo "set -gx PATH \$HOME/.local/bin \$PATH"
                } >> "$fish_conf"
            fi
            ;;
        *)
            # Unknown shell: cover the most common POSIX fallback too.
            add_path_line "$HOME/.profile"
            ;;
    esac
}

# Prefer pipx if it's available — it handles isolation automatically and
# avoids the "externally-managed-environment" error on newer Debian/Ubuntu.
if command -v pipx >/dev/null 2>&1; then
    echo "Using pipx..."
    pipx install --force "git+${REPO_URL}"
    # This is the actual fix for pipx installs: pipx only adds its bin dir
    # to PATH permanently if you tell it to. Previously we never called
    # this, so `peerchat` worked once (if PATH already happened to include
    # it) and then vanished in every new terminal.
    pipx ensurepath >/dev/null 2>&1 || true
    echo ""
    echo "Done! Open a new terminal window, then run: peerchat"
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
mkdir -p "$LINK_DIR"
ln -sf "$INSTALL_DIR/venv/bin/peerchat" "$LINK_DIR/peerchat"
ln -sf "$INSTALL_DIR/venv/bin/peerchat-server" "$LINK_DIR/peerchat-server" 2>/dev/null || true

ensure_path_persisted

echo ""
echo "Done! Installed to $INSTALL_DIR"
echo "Open a new terminal window, then run: peerchat"