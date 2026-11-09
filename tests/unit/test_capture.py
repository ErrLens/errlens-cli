"""Byte budgets are independent of chunk and Unicode character boundaries."""

import tracemalloc

import pytest

from errlens.capture import Capture, TailBuffer


def test_independent_tails_and_completeness() -> None:
    capture = Capture(4)
    capture.append("stdout", b"abc")
    capture.append("stdout", b"def")
    capture.append("stderr", b"12")
    assert capture.stdout.data == b"cdef"
    assert capture.stderr.data == b"12"
    assert capture.truncated and capture.stdout.truncated
    assert not capture.stderr.truncated


def test_split_unicode_invalid_and_cut_bytes() -> None:
    data = "Привет 🌍".encode()
    tail = TailBuffer(100)
    for byte in data:
        tail.append(bytes([byte]))
    assert tail.text() == "Привет 🌍"
    tail.append(b"\xff")
    assert tail.text().endswith("�")
    cut = TailBuffer(2)
    cut.append("🌍".encode())
    assert "�" in cut.text()
    assert cut.truncated


def test_zero_exact_and_single_large_chunk() -> None:
    zero = TailBuffer(0)
    zero.append(b"x")
    assert zero.data == b"" and zero.truncated
    exact = TailBuffer(2)
    exact.append(b"ab")
    assert not exact.truncated
    exact.append(b"12345")
    assert exact.data == b"45" and exact.truncated
    with pytest.raises(ValueError):
        TailBuffer(-1)


def test_bounded_memory_without_newlines() -> None:
    tail = TailBuffer(65536)
    block = b"x" * 8192
    tracemalloc.start()
    try:
        for _ in range(4096):
            tail.append(block)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(tail.data) == 65536
    assert peak < 1024 * 1024


def test_decoding_is_explicit() -> None:
    capture = Capture()
    capture.append("stderr", "Ошибка".encode("cp1251"))
    assert capture.decoded("cp1251").stderr == "Ошибка"
