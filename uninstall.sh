#!/usr/bin/env bash
set -euo pipefail

YK_HOME="${YK_HOME:-$HOME/.youtube-knowledge}"
case "$YK_HOME" in /*) ;; *) printf '%s\n' 'Error: YK_HOME must be absolute' >&2; exit 1 ;; esac
if [ ! -d "$YK_HOME" ]; then
    printf '%s\n' 'youtube-knowledge is already absent.'
    exit 0
fi
if [ -L "$YK_HOME" ]; then
    printf '%s\n' 'Error: refusing a symlinked YK_HOME' >&2
    exit 1
fi
YK_HOME=$(cd "$YK_HOME" && pwd -P)
if [ "$YK_HOME" = / ] || [ "$YK_HOME" = "$(cd "$HOME" && pwd -P)" ] || ! grep -qx 'youtube-knowledge:managed' "$YK_HOME/.yk-installation" || [ ! -f "$YK_HOME/.yk-manifest" ]; then
    printf '%s\n' 'Error: refusing to remove an unmarked or unsafe installation directory' >&2
    exit 1
fi
remove_skill() {
    target="$1/SKILL.md"
    if [ -f "$target" ] && grep -qFx "<!-- youtube-knowledge:managed installation-id:$YK_HOME -->" "$target"; then
        rm "$target"
        rmdir "$1" 2>/dev/null || true
        printf 'Removed managed skill: %s\n' "$target"
    fi
}
home_created=0
while IFS= read -r owned; do
    case "$owned" in
        home-dir:created) home_created=1 ;;
        skill:*/skills/youtube-knowledge) remove_skill "${owned#skill:}" ;;
        link:*/yk)
            link=${owned#link:}
            if [ -L "$link" ] && [ "$(readlink "$link")" = "$YK_HOME/bin/yk" ]; then rm "$link"; fi ;;
        home:src|home:venv|home:bin|home:state)
            path="$YK_HOME/${owned#home:}"
            [ ! -L "$path" ] || { printf 'Error: refusing symlinked owned path: %s\n' "$path" >&2; exit 1; }
            rm -rf "$path" ;;
        home:config.json|home:.skill-targets|home:.yk-installation)
            rm -f "$YK_HOME/${owned#home:}" ;;
        home:.yk-manifest) ;;
        *) printf 'Error: invalid manifest entry: %s\n' "$owned" >&2; exit 1 ;;
    esac
done < "$YK_HOME/.yk-manifest"
rm "$YK_HOME/.yk-manifest"
if [ "$home_created" = 1 ]; then rmdir "$YK_HOME" 2>/dev/null || true; fi
printf '%s\n' 'Removed youtube-knowledge. Vault notes, temporary video workdirs, skill backups, uv and shared model caches were preserved.'
