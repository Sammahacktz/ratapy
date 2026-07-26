"""I2S audio on the Raspberry Pi -- a microphone in, a speaker out.

Two master-attached devices, both driven in Python with `sounddevice` (PortAudio)
over ALSA:

    rp = Raspberry()
    mic = PiMicrophone(board=rp)          # e.g. an INMP441 I2S MEMS mic
    spk = PiSpeaker(board=rp)             # e.g. a MAX98357 I2S amp + speaker

    clip = mic.record(seconds=3)          # -> numpy float32 array, [-1, 1]
    spk.play(clip)                        # play it back
    spk.tone(440, 0.5)                    # or a 440 Hz beep

    mic.record_wav("note.wav", 3)         # save straight to a .wav
    spk.play("note.wav")                  # play a .wav file

These need the Pi's I2S bus set up (a device-tree overlay in the boot config)
and the audio stack installed -- see docs/INSTALL.md. Running BOTH an I2S mic and
an I2S amp at once needs a combined overlay (e.g. the Google voiceHAT); a single
one alone is simpler. `sounddevice` + PortAudio only import on a machine with the
audio stack, so -- like the camera and NeoPixel -- these are loaded lazily and
`import ratapy` still works on a plain PC.

`device=` picks the ALSA device when you have more than one (a name substring or
index, per `sounddevice.query_devices()`); leave it None for the default.
"""

from __future__ import annotations

import wave
from typing import Any

from .base import LocalDevice


def _sd() -> Any:
    """Import sounddevice on demand, with a clear message if it's absent."""
    try:
        import sounddevice
    except (ImportError, OSError) as e:  # OSError: PortAudio lib not installed
        raise RuntimeError(
            "audio needs sounddevice + PortAudio -- `bash install.sh --pi`, or "
            "`sudo apt install libportaudio2 && uv pip install sounddevice`"
        ) from e
    return sounddevice


class PiMicrophone(LocalDevice):
    """A microphone on the Pi (I2S like the INMP441, or any ALSA capture device).

    Args:
        samplerate: samples per second (16000 is plenty for voice; the INMP441
            does up to 48000).
        channels: 1 (mono) or 2.
        device: ALSA device to capture from -- a name substring or index; None
            uses the default.
        board: the Raspberry to attach to (defaults to the current master).
    """

    def __init__(self, samplerate: int = 16000, channels: int = 1,
                 device: "int | str | None" = None,
                 board: "object | None" = None) -> None:
        if channels not in (1, 2):
            raise ValueError(f"channels must be 1 or 2, got {channels}")
        super().__init__(board)   # type: ignore[arg-type]  # LocalDevice checks Raspberry
        self.samplerate = samplerate
        self.channels = channels
        self.device = device

    def record(self, seconds: float) -> Any:
        """Record `seconds` of audio, blocking, into a float32 numpy array [-1, 1]."""
        if seconds <= 0:
            raise ValueError(f"seconds must be positive, got {seconds}")
        sd = _sd()
        frames = int(seconds * self.samplerate)
        data = sd.rec(frames, samplerate=self.samplerate, channels=self.channels,
                      dtype="float32", device=self.device)
        sd.wait()
        return data

    def level(self, seconds: float = 0.1) -> float:
        """Quick loudness sample: RMS of a short recording, ~0.0 (quiet)..1.0."""
        import numpy as np
        data = self.record(seconds)
        return float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0

    def record_wav(self, path: str, seconds: float) -> None:
        """Record straight to a 16-bit WAV file."""
        import numpy as np
        data = self.record(seconds)
        pcm = np.clip(data, -1.0, 1.0)
        ints = (pcm * 32767).astype("<i2")
        with wave.open(path, "wb") as w:
            w.setnchannels(self.channels)
            w.setsampwidth(2)
            w.setframerate(self.samplerate)
            w.writeframes(ints.tobytes())

    def __repr__(self) -> str:
        return f"PiMicrophone(samplerate={self.samplerate}, channels={self.channels})"


class PiSpeaker(LocalDevice):
    """A speaker on the Pi (an I2S amp like the MAX98357, or any ALSA output).

    Args:
        samplerate: playback rate; must match the audio you feed it.
        device: ALSA output device (name substring or index); None = default.
        board: the Raspberry to attach to (defaults to the current master).
    """

    def __init__(self, samplerate: int = 44100,
                 device: "int | str | None" = None,
                 board: "object | None" = None) -> None:
        super().__init__(board)   # type: ignore[arg-type]
        self.samplerate = samplerate
        self.device = device

    def play(self, source: Any, blocking: bool = True) -> None:
        """Play a numpy array (float32 [-1, 1]) or a path to a .wav file."""
        sd = _sd()
        samples, rate = (self._read_wav(source) if isinstance(source, str)
                         else (source, self.samplerate))
        sd.play(samples, samplerate=rate, device=self.device)
        if blocking:
            sd.wait()

    def tone(self, frequency: float, seconds: float = 0.5,
             amplitude: float = 0.3) -> None:
        """Play a sine tone -- a beep at `frequency` Hz for `seconds`."""
        import numpy as np
        if not 0 < amplitude <= 1:
            raise ValueError(f"amplitude must be in (0, 1], got {amplitude}")
        t = np.linspace(0, seconds, int(seconds * self.samplerate), endpoint=False)
        wave_ = (amplitude * np.sin(2 * np.pi * frequency * t)).astype("float32")
        self.play(wave_)

    def stop(self) -> None:
        """Stop playback immediately (for a non-blocking play)."""
        _sd().stop()

    @staticmethod
    def _read_wav(path: str) -> "tuple[Any, int]":
        import numpy as np
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            raw = w.readframes(w.getnframes())
            ints = np.frombuffer(raw, dtype="<i2")
            if w.getnchannels() == 2:
                ints = ints.reshape(-1, 2)
        return ints.astype("float32") / 32768.0, rate

    def _release(self) -> None:
        try:
            _sd().stop()
        except Exception:  # nothing playing / no audio stack -- fine
            pass

    def __repr__(self) -> str:
        return f"PiSpeaker(samplerate={self.samplerate})"
