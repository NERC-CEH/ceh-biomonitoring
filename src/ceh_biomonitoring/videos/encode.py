"""Writing .mp4 videos (H.264, plays in browsers, PowerPoint and phones), with sound if given.

Uses PyAV (the "av" package, installed with the "videos" extra): ffmpeg's libraries, loaded inside Python.
Not a separate ffmpeg program, which managed computers often block (UKCEH laptops do). Frames are handed
over one at a time, so long videos don't need much memory.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _av():
    try:
        import av
        return av
    except ImportError:
        raise SystemExit("Videos need the av package. Install the videos extra: ./install.sh videos (Windows: "
                         "install-windows.bat, then type videos), or in R: cehbio_install(\"videos\").") from None


class Video:
    """with Video(path, width, height, fps, audio=samples, audio_rate=sr) as v:  v.add(frame)

    frame: height x width x 3, uint8. audio: mono samples (-1 to 1), played at audio_rate."""

    def __init__(self, path: Path, width: int, height: int, fps: float, audio: np.ndarray | None = None,
                 audio_rate: int | None = None):
        av = _av()
        self.path, self.w, self.h = Path(path), width - width % 2, height - height % 2
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.out = av.open(str(self.path), "w")
        codec = "libx264" if "libx264" in av.codecs_available else "h264"
        from fractions import Fraction
        self.v = self.out.add_stream(codec, rate=Fraction(fps).limit_denominator(1000))
        self.v.width, self.v.height, self.v.pix_fmt = self.w, self.h, "yuv420p"
        self.v.options = {"crf": "23", "preset": "medium"} if codec == "libx264" else {}
        if audio is not None and int(audio_rate) not in (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000):
            raise ValueError(f"audio_rate {audio_rate}: use a standard rate, e.g. 48000")
        self.audio, self.rate = audio, audio_rate
        self.a = None
        if audio is not None:
            self.a = self.out.add_stream("aac", rate=int(audio_rate))
            self.a.layout = "mono"
        self.frames = 0

    def add(self, frame: np.ndarray) -> None:
        f = np.ascontiguousarray(frame[: self.h, : self.w, :3], dtype=np.uint8)
        for p in self.v.encode(_av().VideoFrame.from_ndarray(f, format="rgb24")):
            self.out.mux(p)
        self.frames += 1

    def _write_audio(self) -> None:
        av = _av()
        s = np.clip(np.asarray(self.audio, dtype=np.float32), -1, 1)
        for k in range(0, len(s), 1024):
            fr = av.AudioFrame.from_ndarray(s[None, k:k + 1024], format="fltp", layout="mono")
            fr.sample_rate = int(self.rate)
            for p in self.a.encode(fr):
                self.out.mux(p)
        for p in self.a.encode():
            self.out.mux(p)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for p in self.v.encode():
            self.out.mux(p)
        if self.a is not None:
            self._write_audio()
        self.out.close()
