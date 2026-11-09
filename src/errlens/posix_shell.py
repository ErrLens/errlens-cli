"""Opt-in Bash and Zsh configuration; never runs a shell while installing."""

import os
from pathlib import Path
import shlex
import uuid

OWNER = "# ErrLens managed integration v1"


def default_profile(shell: str) -> Path:
    if os.name == "nt":
        raise ValueError("Default Bash/Zsh profiles are supported on Linux and macOS only; use --profile for an isolated test.")
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"
    return Path.home() / ".bashrc"


def script(shell: str) -> str:
    resolver = "type -P" if shell == "bash" else "whence -p"
    existing = "declare -F python >/dev/null" if shell == "bash" else "typeset -f python >/dev/null"
    return OWNER + "\n" + f'''if {existing} || alias python >/dev/null 2>&1; then
  printf '%s\\n' 'ErrLens: existing python function or alias preserved' >&2
else
  python() {{
    local target launcher
    target=$({resolver} python) || {{ printf '%s\\n' 'ErrLens: python not found' >&2; return 127; }}
    if [ "${{ERRLENS_DISABLE:-}}" = 1 ]; then
      command "$target" "$@"
    elif launcher=$({resolver} errlens); then
      command "$launcher" run -- "$target" "$@"
    else
      command "$target" "$@"
    fi
  }}
fi
'''


def manage(action: str, shell: str, profile: Path) -> str:
    profile = profile.expanduser().absolute()
    integration = profile.parent / ".errlens" / (profile.name + "." + shell + ".sh")
    marker = "# ErrLens " + shell + " v1"
    line = "[ ! -f " + shlex.quote(str(integration)) + " ] || . " + shlex.quote(str(integration)) + " " + marker
    addition = ("\n" + line + "\n").encode("utf-8")
    original = profile.read_bytes() if profile.exists() else b""
    original.decode("utf-8-sig")
    installed = addition in original
    if marker.encode() in original and not installed:
        raise ValueError("ErrLens connection was edited; resolve it manually before changing integration.")
    if action == "status":
        return f"{'installed' if installed and integration.exists() else 'not installed'}: {profile}"
    if integration.exists() and not integration.read_text(encoding="utf-8").startswith(OWNER + "\n"):
        raise ValueError(f"Refusing to modify unowned integration file: {integration}")
    if action == "install":
        integration.parent.mkdir(parents=True, exist_ok=True)
        if not integration.exists():
            integration.write_text(script(shell), encoding="utf-8", newline="\n")
        updated = original if installed else original + addition
    elif action == "uninstall":
        updated = original.replace(addition, b"", 1)
    else:
        raise ValueError("Unsupported action")
    if updated != original:
        profile.parent.mkdir(parents=True, exist_ok=True)
        if profile.exists():
            profile.with_name(profile.name + ".errlens-backup-" + uuid.uuid4().hex).write_bytes(original)
        profile.write_bytes(updated)
    if action == "uninstall" and integration.exists():
        integration.unlink()
    return f"{action}: {profile}; restart or source the profile."
