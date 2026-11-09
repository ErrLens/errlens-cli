"""All profile tests use temporary files; shell tests require actual executables."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import signal
import threading

import pytest

from errlens.posix_shell import manage


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_sigint_isolated(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    if os.name == "nt" or not executable:
        pytest.skip("Requires native POSIX shell")
    import shlex
    profile = tmp_path / ("." + shell + "rc")
    manage("install", shell, profile)
    env = {**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path),
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")}
    body = ". " + shlex.quote(str(profile)) + "; python -c 'import time;print(\"READY\",flush=True);time.sleep(30)'"
    process = subprocess.Popen([executable, "-c", body], cwd=tmp_path, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    lines: list[bytes] = []
    reader = threading.Thread(target=lambda: lines.append(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        reader.join(10)
        assert lines == [b"READY\n"]
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode in (130, -signal.SIGINT)
        assert b"ErrLens |" not in stderr
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        reader.join(2)


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_profile_roundtrip(tmp_path: Path, shell: str) -> None:
    profile = tmp_path / "путь с пробелами" / ("." + shell + "rc")
    profile.parent.mkdir()
    original = b"# user config\nexport VALUE=1"
    profile.write_bytes(original)
    manage("install", shell, profile)
    installed = profile.read_bytes()
    manage("install", shell, profile)
    assert profile.read_bytes() == installed
    assert "installed:" in manage("status", shell, profile)
    profile.write_bytes(installed + b"# added later\n")
    manage("uninstall", shell, profile)
    assert profile.read_bytes() == original + b"# added later\n"
    assert list(profile.parent.glob("*.errlens-backup-*"))


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_management_cli_isolated(tmp_path: Path, shell: str) -> None:
    profile = tmp_path / ("." + shell + "rc")
    env = {**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    for action in ("install", "status", "uninstall"):
        result = subprocess.run([sys.executable, "-m", "errlens", "shell", action, shell,
                                 "--profile", str(profile)], cwd=tmp_path, env=env,
                                capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        if action == "status":
            assert b"installed:" in result.stdout


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_execution(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    if not executable or os.name == "nt":
        pytest.skip("Native POSIX shell unavailable")
    profile = tmp_path / ("." + shell + "rc")
    manage("install", shell, profile)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["ZDOTDIR"] = str(tmp_path)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    import shlex
    body = '. ' + shlex.quote(str(profile)) + '''
python -c 'import sys; print(sys.argv[1])' 'Привет a b'
python -c 'import sys; print(sys.argv[1])' 'a"b'
python -c 'import sys; sys.exit(7)'
echo CODE=$?
ERRLENS_DISABLE=1 python -c 'print("disabled")'
python -c 'print(undefined_variable)'
'''
    result = subprocess.run([executable, "-c", body], cwd=tmp_path, env=env,
                            capture_output=True, timeout=30)
    assert result.returncode == 1
    assert "Привет a b".encode() in result.stdout and b"CODE=7" in result.stdout
    assert b'a"b' in result.stdout
    assert b"disabled" in result.stdout and "ErrLens".encode() in result.stderr


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_streams_and_bypasses(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    if not executable or os.name == "nt":
        pytest.skip("Native POSIX shell unavailable")
    import shlex
    profile = tmp_path / ("." + shell + "rc")
    manage("install", shell, profile)
    env = os.environ.copy()
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path),
               PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""))
    source = ". " + shlex.quote(str(profile)) + "\n"
    def invoke(code: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run([executable, "-c", source + code], cwd=tmp_path,
                              env=env, capture_output=True, timeout=20)
    result = invoke("printf 'hello' | python -c 'import sys; print(sys.stdin.read())' | tr a-z A-Z")
    assert result.returncode == 0 and result.stdout.strip() == b"HELLO"
    result = invoke("python -c 'import missing_module_errlens_6c3' >out.txt 2>err.txt; echo $?")
    assert result.stdout.strip() == b"1"
    assert (tmp_path / "out.txt").read_bytes() == b""
    assert b"ErrLens" in (tmp_path / "err.txt").read_bytes()
    result = invoke("ERRLENS_DISABLE=1 python -c 'print(undefined_name)'")
    assert result.returncode == 1 and b"ErrLens" not in result.stderr
    result = invoke("command python -c 'print(undefined_name)'")
    assert result.returncode == 1 and b"ErrLens" not in result.stderr
    result = invoke("python -c 'import sys; print(sys.prefix)'")
    assert result.returncode == 0 and sys.prefix.encode() in result.stdout


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_missing_errlens_falls_back(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    if not executable or os.name == "nt":
        pytest.skip("Native POSIX shell unavailable")
    import shlex
    profile = tmp_path / ("." + shell + "rc")
    manage("install", shell, profile)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python").symlink_to(Path(sys.executable).resolve())
    env = {**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path), "PATH": str(binaries)}
    command = ". " + shlex.quote(str(profile)) + "; python -c 'import sys;sys.exit(7)'"
    result = subprocess.run([executable, "-c", command], cwd=tmp_path, env=env,
                            capture_output=True, timeout=15)
    assert result.returncode == 7 and b"ErrLens" not in result.stderr


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash") or not shutil.which("zsh"),
                    reason="Requires native Bash and Zsh")
def test_zsh_prompt_from_bash_venv(tmp_path: Path) -> None:
    import shlex
    activate = Path(sys.prefix) / "bin" / "activate"
    bash = shutil.which("bash")
    command = ("export PS1='BASH_MARKER_" + chr(92) + "u'; . " + shlex.quote(str(activate))
               + "; exec zsh -f -c 'print -r -- $PS1'")
    result = subprocess.run([bash, "--noprofile", "--norc", "-c", command],
                            cwd=tmp_path, env={**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)},
                            capture_output=True, text=True, timeout=15)
    print("Zsh PS1 after Bash venv activation:", repr(result.stdout))
    assert result.returncode == 0 and "BASH_MARKER_\\u" in result.stdout
    clean_env = {**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    clean_env.pop("PS1", None)
    clean = subprocess.run(["zsh", "-f", "-c", 'print -r -- "$PS1"'],
                           cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=15)
    assert clean.returncode == 0 and "BASH_MARKER" not in clean.stdout
    inherited_env = {**clean_env, "PS1": "BASH_MARKER_\\u"}
    inherited = subprocess.run(["zsh", "-f", "-c", 'print -r -- "$PS1"'],
                               cwd=tmp_path, env=inherited_env, capture_output=True, text=True, timeout=15)
    print("Zsh PS1 with exported Bash prompt:", repr(inherited.stdout))
    assert inherited.returncode == 0 and "BASH_MARKER_\\u" in inherited.stdout
