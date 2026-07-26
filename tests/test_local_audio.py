"""PiMicrophone + PiSpeaker (ratapy.devices.local.audio).

No audio hardware: a fake `sounddevice` module is injected, so the record/play
plumbing (shapes, rates, WAV round-trip, tone generation) is exercised in Python.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from ratapy.boards import Mega
from ratapy.devices import PiMicrophone, PiSpeaker
from ratapy.raspberry import Raspberry


class FakeSD:
    """Records what it was asked to play; hands back canned audio for rec()."""

    def __init__(self) -> None:
        self.rec_args: tuple | None = None
        self.canned: np.ndarray | None = None
        self.played: np.ndarray | None = None
        self.play_rate: int | None = None
        self.stopped = False

    def rec(self, frames: int, samplerate: int, channels: int,
            dtype: str, device: object) -> np.ndarray:
        self.rec_args = (frames, samplerate, channels, device)
        if self.canned is not None:
            return self.canned
        return np.zeros((frames, channels), dtype="float32")

    def wait(self) -> None:
        pass

    def play(self, samples: np.ndarray, samplerate: int, device: object) -> None:
        self.played = np.asarray(samples)
        self.play_rate = samplerate

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def sd(monkeypatch: pytest.MonkeyPatch) -> FakeSD:
    fake = FakeSD()
    mod = types.ModuleType("sounddevice")
    for name in ("rec", "wait", "play", "stop"):
        setattr(mod, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "sounddevice", mod)
    return fake


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


# --- microphone -----------------------------------------------------------

def test_mic_attaches_to_the_raspberry(sd: FakeSD, rp: Raspberry) -> None:
    mic = PiMicrophone(board=rp)
    assert mic.board is rp


def test_mic_rejects_an_arduino_board(sd: FakeSD) -> None:
    from ratapy.protocol import RataError
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiMicrophone(board=Mega("A"))


def test_mic_record_shape_and_rate(sd: FakeSD, rp: Raspberry) -> None:
    mic = PiMicrophone(samplerate=16000, channels=1, board=rp)
    data = mic.record(seconds=2)
    frames, rate, channels, _ = sd.rec_args
    assert frames == 32000 and rate == 16000 and channels == 1
    assert data.shape == (32000, 1)


def test_mic_record_rejects_nonpositive(sd: FakeSD, rp: Raspberry) -> None:
    mic = PiMicrophone(board=rp)
    with pytest.raises(ValueError, match="seconds must be positive"):
        mic.record(0)


def test_mic_channels_validated(sd: FakeSD, rp: Raspberry) -> None:
    with pytest.raises(ValueError, match="channels must be 1 or 2"):
        PiMicrophone(channels=3, board=rp)


def test_mic_level_is_rms(sd: FakeSD, rp: Raspberry) -> None:
    mic = PiMicrophone(samplerate=1000, channels=1, board=rp)
    sd.canned = np.full((100, 1), 0.5, dtype="float32")
    assert abs(mic.level(0.1) - 0.5) < 1e-6          # RMS of a constant 0.5
    sd.canned = np.zeros((100, 1), dtype="float32")
    assert mic.level(0.1) == 0.0


def test_mic_record_wav_roundtrips(sd: FakeSD, rp: Raspberry, tmp_path) -> None:
    import wave
    mic = PiMicrophone(samplerate=8000, channels=1, board=rp)
    sd.canned = np.full((80, 1), 1.0, dtype="float32")   # full-scale
    path = str(tmp_path / "note.wav")
    mic.record_wav(path, 0.01)
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 8000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 80


# --- speaker --------------------------------------------------------------

def test_speaker_plays_an_array(sd: FakeSD, rp: Raspberry) -> None:
    spk = PiSpeaker(samplerate=44100, board=rp)
    samples = np.linspace(-1, 1, 100, dtype="float32")
    spk.play(samples)
    assert sd.play_rate == 44100
    assert np.array_equal(sd.played, samples)


def test_speaker_tone_generates_a_sine(sd: FakeSD, rp: Raspberry) -> None:
    spk = PiSpeaker(samplerate=8000, board=rp)
    spk.tone(440, seconds=0.25, amplitude=0.5)
    assert sd.played is not None
    assert len(sd.played) == int(0.25 * 8000)
    assert abs(float(np.max(np.abs(sd.played))) - 0.5) < 0.05   # ~amplitude
    assert sd.play_rate == 8000


def test_speaker_tone_amplitude_validated(sd: FakeSD, rp: Raspberry) -> None:
    spk = PiSpeaker(board=rp)
    for bad in (0, 1.5):
        with pytest.raises(ValueError, match="amplitude"):
            spk.tone(440, amplitude=bad)


def test_speaker_plays_a_wav_file(sd: FakeSD, rp: Raspberry, tmp_path) -> None:
    # Record a WAV with the mic, then hand the path to the speaker.
    mic = PiMicrophone(samplerate=8000, channels=1, board=rp)
    sd.canned = np.full((80, 1), 0.5, dtype="float32")
    path = str(tmp_path / "clip.wav")
    mic.record_wav(path, 0.01)

    spk = PiSpeaker(board=rp)
    spk.play(path)
    assert sd.play_rate == 8000                       # rate came from the WAV
    assert sd.played is not None
    assert abs(float(np.max(sd.played)) - 0.5) < 0.01  # ~0.5 back out


def test_speaker_stop(sd: FakeSD, rp: Raspberry) -> None:
    spk = PiSpeaker(board=rp)
    spk.stop()
    assert sd.stopped is True


def test_absent_sounddevice_gives_a_helpful_error(rp: Raspberry) -> None:
    # No `sd` fixture: sounddevice really isn't importable here.
    mic = PiMicrophone(board=rp)
    with pytest.raises(RuntimeError, match="sounddevice"):
        mic.record(0.1)
