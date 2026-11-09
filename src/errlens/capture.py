"""Bounded byte tails, decoded only when diagnostic text is requested."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class CapturedData:
    """Decoded diagnostic text, separate from future raw output forwarding.

    A terminal adapter may only provide combined output; it must not invent
    stdout/stderr separation. Completeness lives in ExecutionResult.
    """

    stdout: str = ""
    stderr: str = ""
    combined: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    combined_truncated: bool = False


class TailBuffer:
    """Retain at most limit bytes, independently of line length or chunk count.

    Feed from one reader only; inspect after that reader has finished.
    """

    def __init__(self, limit: int = 1024 * 1024) -> None:
        if limit < 0:
            raise ValueError("Buffer limit must not be negative")
        self.limit = limit
        self._data = bytearray()
        self.truncated = False

    def append(self, data: bytes) -> None:
        if len(self._data) + len(data) > self.limit:
            self.truncated = True
        if self.limit == 0:
            return
        if len(data) >= self.limit:
            self._data[:] = data[-self.limit:]
        else:
            excess = max(0, len(self._data) + len(data) - self.limit)
            del self._data[:excess]
            self._data.extend(data)

    @property
    def data(self) -> bytes:
        return bytes(self._data)

    def text(self, encoding: str = "utf-8") -> str:
        """Chunk boundaries disappear before decoding; cut/invalid bytes replace.

        The caller may supply another encoding. No universal detection is assumed.
        """
        return self._data.decode(encoding, errors="replace")


class Capture:
    """Independent 1 MiB tails by default; never stores full logs on disk."""

    def __init__(self, max_bytes: int = 1024 * 1024) -> None:
        self.stdout = TailBuffer(max_bytes)
        self.stderr = TailBuffer(max_bytes)

    def append(self, stream: Literal["stdout", "stderr"], data: bytes) -> None:
        getattr(self, stream).append(data)

    @property
    def truncated(self) -> bool:
        return self.stdout.truncated or self.stderr.truncated

    def decoded(self, encoding: str = "utf-8") -> CapturedData:
        return CapturedData(
            self.stdout.text(encoding), self.stderr.text(encoding),
            stdout_truncated=self.stdout.truncated, stderr_truncated=self.stderr.truncated,
        )
