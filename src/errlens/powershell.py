"""Explicit profile edits for the opt-in PowerShell python wrapper."""

from pathlib import Path
import shutil
import subprocess
import sys
import uuid

OWNER = "# ErrLens managed integration v1"


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def default_profile() -> Path:
    executable = shutil.which("pwsh")
    if executable is None:
        raise ValueError("PowerShell 7 (pwsh) was not found; specify --profile explicitly.")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command",
                             "if ($PSVersionTable.PSVersion.Major -lt 7) { exit 1 }; $PROFILE.CurrentUserAllHosts"],
                            capture_output=True, text=True, encoding="utf-8", timeout=15, check=True)
    return Path(result.stdout.strip())


def script() -> str:
    return OWNER + "\n" + r'''
if ($PSVersionTable.PSVersion.Major -lt 7) { Write-Warning 'ErrLens requires PowerShell 7'; return }
$existing = Get-Command python -CommandType Alias,Function -ErrorAction SilentlyContinue
if ($existing) { Write-Warning 'ErrLens: existing python alias/function preserved'; return }
function global:python {
    # ErrLens wrapper: resolve applications only, on every invocation (venv-aware).
    $target = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $target) { $global:LASTEXITCODE = 127; Write-Error 'ErrLens: python executable not found'; return }
    $PSNativeCommandUseErrorActionPreference = $false
    if ($PSVersionTable.PSVersion -ge [version]'7.3') { $PSNativeCommandArgumentPassing = 'Standard' }
    if ($env:ERRLENS_DISABLE -eq '1') {
        & $target.Source @args
    } else {
        & __RUNTIME__ -m errlens run -- $target.Source @args
    }
    $global:LASTEXITCODE = $LASTEXITCODE
}
'''.replace("__RUNTIME__", quote(sys.executable))


def manage(action: str, profile: Path) -> str:
    profile = profile.expanduser().absolute()
    integration = profile.parent / "ErrLens" / (profile.name + ".python.ps1")
    line = ("if (Test-Path -LiteralPath " + quote(str(integration)) + ") { . "
            + quote(str(integration)) + " } # ErrLens v1")
    addition = ("\n" + line + "\n").encode("utf-8")
    original = profile.read_bytes() if profile.exists() else b""
    original.decode("utf-8-sig")  # Refuse unsupported encodings rather than corrupting them.
    installed = addition in original
    if b"# ErrLens v1" in original and not installed:
        raise ValueError("ErrLens profile line was edited; restore it from backup before changing integration.")
    if action == "status":
        return f"{'installed' if installed and integration.exists() else 'not installed'}: {profile}"
    if integration.exists() and not integration.read_text(encoding="utf-8").startswith(OWNER + "\n"):
        raise ValueError(f"Refusing to modify an unowned integration file: {integration}")
    if action == "install":
        integration.parent.mkdir(parents=True, exist_ok=True)
        if not integration.exists():
            integration.write_text(script(), encoding="utf-8", newline="\n")
        updated = original if installed else original + addition
    else:
        updated = original.replace(addition, b"", 1)
    if updated != original:
        profile.parent.mkdir(parents=True, exist_ok=True)
        if profile.exists():
            backup = profile.with_name(profile.name + ".errlens-backup-" + uuid.uuid4().hex)
            backup.write_bytes(original)
        profile.write_bytes(updated)
    if action == "uninstall" and integration.exists():
        integration.unlink()
    return f"{action}: {profile}. Restart PowerShell to apply."
