from __future__ import annotations

from io import StringIO


def test_json_mode_clears_pinned_stream_and_uses_live_streams(capsys) -> None:
    from distill._console import console, set_json_mode

    pinned = StringIO()
    try:
        console.file = pinned
        set_json_mode(True)

        assert console._file is None

        console.print("diagnostic")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "diagnostic" in captured.err
        assert pinned.getvalue() == ""

        set_json_mode(False)
        console.print("human")
        captured = capsys.readouterr()
        assert "human" in captured.out
        assert captured.err == ""
    finally:
        set_json_mode(False)
