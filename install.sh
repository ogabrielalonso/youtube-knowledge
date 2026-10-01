#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'EOF'
Usage: bash install.sh [--claude|--codex|--all] [--yes]
                      [--vault PATH] [--notes-language LANG] [--whisper-model MODEL]
Overrides: YK_HOME, YK_SOURCE, YK_REF, CLAUDE_CONFIG_DIR, CODEX_HOME.
EOF
}

want_claude=0
want_codex=0
forced=0
assume_yes=0
vault=''
language=''
model=''
vault_given=0
language_given=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --claude) want_claude=1; forced=1; shift ;;
        --codex) want_codex=1; forced=1; shift ;;
        --all) want_claude=1; want_codex=1; forced=1; shift ;;
        --yes) assume_yes=1; shift ;;
        --vault|--notes-language|--whisper-model)
            [ "$#" -ge 2 ] || fail "$1 requires a value"
            case "$1" in
                --vault) vault=$2; vault_given=1 ;;
                --notes-language) language=$2; language_given=1 ;;
                --whisper-model) model=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done

export YK_HOME="${YK_HOME:-$HOME/.youtube-knowledge}"
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
case "$YK_HOME" in /*) ;; *) fail 'YK_HOME must be an absolute path' ;; esac
[ "$YK_HOME" != / ] && [ "$YK_HOME" != "$HOME" ] || fail 'Unsafe YK_HOME'
[ ! -L "$YK_HOME" ] || fail 'YK_HOME must not be a symbolic link'
bin_dir="$HOME/.local/bin"
home_created=1
if [ -e "$YK_HOME" ]; then
    home_created=0
    [ -d "$YK_HOME" ] || fail 'YK_HOME must be a directory'
    YK_HOME=$(cd "$YK_HOME" && pwd -P)
    if [ -f "$YK_HOME/.yk-installation" ]; then
        grep -qx 'youtube-knowledge:managed' "$YK_HOME/.yk-installation" || fail 'Invalid installation marker'
        [ -f "$YK_HOME/.yk-manifest" ] || fail 'Marked installation has no ownership manifest'
    else
        # Unrelated files may survive uninstall. Never adopt an existing owned path.
        for reserved in src venv bin state config.json .yk-installation .yk-manifest .skill-targets; do
            if [ -e "$YK_HOME/$reserved" ] || [ -L "$YK_HOME/$reserved" ]; then
                fail "Refusing unmarked YK_HOME with reserved path: $reserved"
            fi
        done
    fi
fi
mkdir -p "$YK_HOME"
YK_HOME=$(cd "$YK_HOME" && pwd -P)
export YK_HOME
[ "$YK_HOME" != / ] && [ "$YK_HOME" != "$(cd "$HOME" && pwd -P)" ] || fail 'Unsafe YK_HOME'
mkdir -p "$bin_dir"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/youtube-knowledge-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

source_path="${YK_SOURCE:-}"
if [ -z "$source_path" ] && [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
    if [ -f "$script_dir/pyproject.toml" ] && [ -f "$script_dir/SKILL.md" ]; then
        source_path=$script_dir
    fi
fi
mkdir -p "$scratch/src"
if [ -n "$source_path" ]; then
    [ -d "$source_path" ] || fail "YK_SOURCE is not a directory: $source_path"
    source_path=$(cd "$source_path" && pwd -P)
    [ -f "$source_path/pyproject.toml" ] && [ -f "$source_path/SKILL.md" ] || fail 'Source is missing pyproject.toml or SKILL.md'
    # Copy only distributable source, excluding local caches and repositories.
    tar -C "$source_path" --exclude=__pycache__ -cf "$scratch/source.tar" pyproject.toml constraints.txt constraints.in README.md LICENSE SKILL.md CHANGELOG.md install.sh uninstall.sh youtube_knowledge
    tar -C "$scratch/src" -xf "$scratch/source.tar"
else
    [ "${YK_OFFLINE_TEST:-0}" != 1 ] || fail 'YK_OFFLINE_TEST requires YK_SOURCE'
    curl -fsSL "https://api.github.com/repos/ogabrielalonso/youtube-knowledge/tarball/${YK_REF:-main}" -o "$scratch/source.tar.gz"
    tar -xzf "$scratch/source.tar.gz" -C "$scratch/src" --strip-components=1
fi
[ -f "$scratch/src/pyproject.toml" ] && [ -f "$scratch/src/SKILL.md" ] && [ -f "$scratch/src/constraints.txt" ] || fail 'Downloaded source is incomplete'
if [ ! -f "$YK_HOME/.yk-installation" ]; then
    printf '%s\n' 'youtube-knowledge:managed' > "$YK_HOME/.yk-installation"
    printf '%s\n' 'home:src' 'home:venv' 'home:bin' 'home:.yk-installation' \
        'home:.yk-manifest' 'home:.skill-targets' > "$YK_HOME/.yk-manifest"
    if [ "$home_created" = 1 ]; then
        printf '%s\n' 'home-dir:created' >> "$YK_HOME/.yk-manifest"
    fi
fi
# Runtime state is recursively owned; unrecorded existing paths are never adopted.
if ! grep -qx 'home:state' "$YK_HOME/.yk-manifest"; then
    [ ! -e "$YK_HOME/state" ] && [ ! -L "$YK_HOME/state" ] || fail 'Refusing unrecorded state directory'
    printf '%s\n' 'home:state' >> "$YK_HOME/.yk-manifest"
fi
[ ! -L "$YK_HOME/state" ] || fail 'state must not be a symbolic link'
mkdir -p "$YK_HOME/state"
# Record configuration before runtime commands can create it.
if [ ! -e "$YK_HOME/config.json" ]; then
    printf '{}\n' > "$YK_HOME/config.json"
    printf '%s\n' 'home:config.json' >> "$YK_HOME/.yk-manifest"
fi
if [ -e "$YK_HOME/src" ]; then
    [ ! -L "$YK_HOME/src" ] || fail 'src must not be a symbolic link'
    rm -rf "$YK_HOME/src"
fi
mv "$scratch/src" "$YK_HOME/src"

if [ "${YK_OFFLINE_TEST:-0}" = 1 ]; then
    printf '%s\n' 'OFFLINE TEST: Python environment and dependency installation are stubbed.'
    mkdir -p "$YK_HOME/venv/bin"
    test_python="${YK_TEST_PYTHON:-$(command -v python3)}"
    ln -sf "$test_python" "$YK_HOME/venv/bin/python"
    cat > "$YK_HOME/venv/bin/yk" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$YK_HOME/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$YK_HOME/venv/bin/python" -m youtube_knowledge.cli "$@"
EOF
    chmod +x "$YK_HOME/venv/bin/yk"
else
    if command -v uv >/dev/null 2>&1; then
        uv_bin=$(command -v uv)
    elif [ -x "$bin_dir/uv" ]; then
        uv_bin="$bin_dir/uv"
    else
        curl -fsSL https://astral.sh/uv/install.sh -o "$scratch/uv-install.sh"
        UV_INSTALL_DIR="$bin_dir" UV_NO_MODIFY_PATH=1 sh "$scratch/uv-install.sh"
        uv_bin="$bin_dir/uv"
    fi
    if [ ! -x "$YK_HOME/venv/bin/python" ]; then
        "$uv_bin" venv --python 3.12 "$YK_HOME/venv"
    fi
    "$uv_bin" pip install --upgrade --python "$YK_HOME/venv/bin/python" \
        -c "$YK_HOME/src/constraints.txt" --build-constraints "$YK_HOME/src/constraints.txt" \
        "$YK_HOME/src" 'yt-dlp[default,curl-cffi]' yt-dlp-ejs deno
fi

# A wrapper retains custom YK_HOME even in a later shell without the override.
mkdir -p "$YK_HOME/bin"
{
    printf '#!/usr/bin/env bash\nset -euo pipefail\n'
    printf 'export YK_HOME=%q\n' "$YK_HOME"
    printf 'exec "$YK_HOME/venv/bin/yk" "$@"\n'
} > "$YK_HOME/bin/yk"
chmod +x "$YK_HOME/bin/yk"
if [ -e "$bin_dir/yk" ] || [ -L "$bin_dir/yk" ]; then
    if [ ! -L "$bin_dir/yk" ] || [ "$(readlink "$bin_dir/yk")" != "$YK_HOME/bin/yk" ]; then
        backup="$bin_dir/yk.bak-$(date +%Y%m%d%H%M%S)-$$"
        mv "$bin_dir/yk" "$backup"
        printf 'Backed up existing yk: %s\n' "$backup"
    fi
fi
ln -sf "$YK_HOME/bin/yk" "$bin_dir/yk"
printf 'link:%s\n' "$bin_dir/yk" >> "$YK_HOME/.yk-manifest"

if [ "$forced" = 0 ]; then
    if [ -d "$CLAUDE_CONFIG_DIR" ] || command -v claude >/dev/null 2>&1; then want_claude=1; fi
    if [ -d "$CODEX_HOME" ] || command -v codex >/dev/null 2>&1; then want_codex=1; fi
    if [ "$want_claude" = 0 ] && [ "$want_codex" = 0 ]; then
        want_claude=1
        want_codex=1
        printf '%s\n' 'Neither agent detected; installing the skill for both Claude Code and Codex.'
    fi
fi
# Render once so reinstall comparisons use the installed, customized content.
"$YK_HOME/venv/bin/python" - "$YK_HOME/src/SKILL.md" "$scratch/SKILL.md" "$YK_HOME/bin/yk" "$YK_HOME" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, wrapper, installation_id = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
marker = "<!-- youtube-knowledge:wrapper -->"
if text.splitlines().count(marker) != 1:
    raise SystemExit("SKILL.md must contain exactly one wrapper placeholder line")
# Double quotes are readable for ordinary paths; shlex handles shell metacharacters.
command = '"' + wrapper + '"' if not any(c in wrapper for c in '\\"$`\n') else shlex.quote(wrapper)
text = text.replace("<!-- youtube-knowledge:managed -->",
                    f"<!-- youtube-knowledge:managed installation-id:{installation_id} -->")
Path(destination).write_text(text.replace(marker, f"Installed wrapper: `{command}`"), encoding="utf-8")
PY
install_skill() {
    target="$1/skills/youtube-knowledge"
    mkdir -p "$target"
    target=$(cd "$target" && pwd -P)
    if [ -e "$target/SKILL.md" ] || [ -L "$target/SKILL.md" ]; then
        if ! cmp -s "$scratch/SKILL.md" "$target/SKILL.md"; then
            backup="$target/SKILL.md.bak-$(date +%Y%m%d%H%M%S)-$$"
            mv "$target/SKILL.md" "$backup"
            printf 'Backed up existing skill: %s\n' "$backup"
        elif [ -L "$target/SKILL.md" ]; then
            rm "$target/SKILL.md"
        fi
    fi
    cp "$scratch/SKILL.md" "$target/SKILL.md"
    printf '%s\n' "$target" >> "$YK_HOME/.skill-targets"
    printf 'skill:%s\n' "$target" >> "$YK_HOME/.yk-manifest"
    printf 'Installed skill: %s\n' "$target/SKILL.md"
}
if [ "$want_claude" = 1 ]; then install_skill "$CLAUDE_CONFIG_DIR"; fi
if [ "$want_codex" = 1 ]; then install_skill "$CODEX_HOME"; fi
awk '!seen[$0]++' "$YK_HOME/.skill-targets" > "$scratch/skill-targets"
mv "$scratch/skill-targets" "$YK_HOME/.skill-targets"
awk '!seen[$0]++' "$YK_HOME/.yk-manifest" > "$scratch/yk-manifest"
mv "$scratch/yk-manifest" "$YK_HOME/.yk-manifest"

if [ "$assume_yes" = 0 ] && ( : </dev/tty ) 2>/dev/null; then
    if [ "$vault_given" = 0 ]; then
        printf 'Obsidian vault path (Enter to keep current setting): ' >/dev/tty
        IFS= read -r vault </dev/tty || true
    fi
    if [ "$language_given" = 0 ]; then
        printf 'Notes language (auto = video language, Enter to keep current setting): ' >/dev/tty
        IFS= read -r language </dev/tty || true
    fi
fi
if [ -n "$vault" ]; then "$YK_HOME/bin/yk" config set vault "$vault"; fi
if [ -n "$language" ]; then "$YK_HOME/bin/yk" config set notes_language "$language"; fi
if [ -z "$vault" ]; then
    printf '%s\n' 'If the vault is unset, configure it with: yk config set vault /path/to/vault'
fi
if [ -n "$model" ]; then
    "$YK_HOME/bin/yk" config set whisper_model "$model"
    if [ "${YK_OFFLINE_TEST:-0}" != 1 ]; then
        "$YK_HOME/venv/bin/python" -c 'from faster_whisper import WhisperModel; import sys; WhisperModel(sys.argv[1], device="cpu", compute_type="int8")' "$model"
    fi
else
    printf '%s\n' 'The Whisper model downloads on first use when subtitles are unavailable.'
fi
case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
        path_line='export PATH="$HOME/.local/bin:$PATH"'
        printf '%s\n' '~/.local/bin is not on PATH. Add this line to your shell configuration:' "$path_line"
        rc_file=''
        user_shell="${SHELL:-}"
        case "${user_shell##*/}" in
            zsh) rc_file="$HOME/.zshrc" ;;
            bash)
                rc_file="$HOME/.bashrc"
                if [ "$(uname -s)" = Darwin ]; then
                    if [ -f "$HOME/.bash_profile" ] || [ ! -f "$rc_file" ]; then
                        rc_file="$HOME/.bash_profile"
                    fi
                fi ;;
        esac
        if [ "$assume_yes" = 0 ] && [ -n "$rc_file" ] && ( : </dev/tty ) 2>/dev/null; then
            if [ -f "$rc_file" ] && grep -Fqx "$path_line" "$rc_file"; then
                printf 'PATH line already present in %s. Open a new shell to use it.\n' "$rc_file"
            else
                printf 'Append this PATH line to %s? [y/N] ' "$rc_file" >/dev/tty
                answer=''
                IFS= read -r answer </dev/tty || true
                case "$answer" in
                    y|Y|yes|YES)
                        printf '\n%s\n' "$path_line" >> "$rc_file"
                        printf 'Updated %s. Open a new shell to use it.\n' "$rc_file" ;;
                esac
            fi
        fi ;;
esac
if [ "${YK_OFFLINE_TEST:-0}" = 1 ]; then
    printf '%s\n' 'OFFLINE TEST: doctor skipped; dependencies were not installed.'
elif ! "$YK_HOME/bin/yk" doctor; then
    printf '%s\n' 'Installation finished, but doctor found issues. Resolve the FAIL lines, then run yk doctor again.'
fi
printf 'CLI available now: "%s"\n' "$YK_HOME/bin/yk"
printf '%s\n' 'Next: Claude Code: /youtube-knowledge <url>' '      Codex: $youtube-knowledge <url> (or ask in natural language)'
