import asyncio
import os

import pytest

from core.screen_streamer import ScreenStreamer


@pytest.mark.asyncio
async def test_detect_best_mode_avoids_h264(monkeypatch):
    monkeypatch.setattr(os.path, 'isfile', lambda path: False)

    streamer = ScreenStreamer(adb_target='127.0.0.1:6520')
    mode = streamer.detect_best_mode()

    assert mode == 'fast_cap'
    assert streamer.mode == 'fast_cap'


@pytest.mark.asyncio
async def test_stream_jpeg_fallback_works(monkeypatch):
    streamer = ScreenStreamer(adb_target='127.0.0.1:6520')
    streamer._mode = 'record'

    async def fake_fast_cap_frame():
        if not hasattr(fake_fast_cap_frame, 'count'):
            fake_fast_cap_frame.count = 0
        fake_fast_cap_frame.count += 1
        return b'fakejpeg' if fake_fast_cap_frame.count <= 2 else None

    monkeypatch.setattr(streamer, '_fast_cap_frame', fake_fast_cap_frame)

    # Run a short iteration and collect frames
    frames = []

    async def collect_frames():
        async for frame in streamer.stream_jpeg():
            frames.append(frame)
            if len(frames) >= 2:
                streamer.stop()

    await collect_frames()

    assert frames == [b'fakejpeg', b'fakejpeg']
    assert streamer.mode == 'fast_cap'
