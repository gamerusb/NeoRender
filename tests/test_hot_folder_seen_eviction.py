from __future__ import annotations

from pathlib import Path

import pytest

from core.hot_folder import HotFolder


class _Pipe:
    def __init__(self, inbox: Path):
        self.hot_folder_inbox = inbox
        self.hot_folder_profile = ""
        self.hot_folder_render_only = False
        self._started = False
        self.tenant_id = "default"
        self.db_path = None


@pytest.mark.asyncio
async def test_move_file_discards_seen_for_reused_names(tmp_path: Path):
    inbox = tmp_path / "inbox"
    proc = tmp_path / "processing"
    done = tmp_path / "done"
    inbox.mkdir()
    proc.mkdir()
    done.mkdir()
    src = proc / "video.mp4"
    src.write_bytes(b"x" * 5000)

    hf = HotFolder(_Pipe(inbox))
    key = str(src.resolve())
    hf._seen.add(key)

    await hf._move_file(str(src), "done")
    assert key not in hf._seen
