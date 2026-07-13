"""Camera -- a Pi Camera Module on the master, driven with Picamera2 + OpenCV.

A camera is far too much data for an Arduino, so it plugs straight into the
Raspberry Pi. The API still reads like any other RATA device::

    rp = Raspberry()
    cam = Camera(board=rp)          # or Cam(board=rp) -- same class

    frame = cam.capture()           # one BGR image (an OpenCV/numpy array)
    cam.snapshot("photo.jpg")       # grab + save in one call
    cam.stream()                    # live preview window; press q to quit
    cam.record("clip.mp4", 5)       # record 5 seconds to a file
    for frame in cam.frames():      # iterate frames for your own processing
        ...

Frames are returned in **BGR** order, ready to hand straight to OpenCV
(`cv2.imshow`, `cv2.imwrite`, `cv2.cvtColor`, ...).

This module imports Picamera2 at load time, so it only imports on a Raspberry Pi
with the camera stack installed (`install.sh --pi`, plus the system
`python3-picamera2`/`libcamera` packages -- see the install docs). It is loaded
lazily by `ratapy.devices`, so importing RATA on a plain PC still works.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import cv2
from libcamera import Transform
from picamera2 import Picamera2

from ...protocol import RataError
from ...raspberry import Raspberry
from .base import LocalDevice

# A frame is an OpenCV image: a numpy ndarray of shape (h, w, 3), BGR, uint8.
# Typed as Any because cv2/Picamera2 return untyped arrays; keeps annotations simple.
Frame = Any


class Camera(LocalDevice):
    """A Raspberry Pi camera, captured with Picamera2 and processed with OpenCV.

    Args:
        resolution: (width, height) of captured frames. Default (640, 480).
        framerate: target frames per second for streaming/recording.
        hflip / vflip: mirror the image horizontally / vertically.
        board: the Raspberry to attach to (defaults to the current master).

    The camera is opened lazily on first use (or call :meth:`start`), and closed
    by :meth:`close` -- which also runs from `Raspberry.close()` and when the
    Camera is used as a context manager.
    """

    def __init__(
        self,
        resolution: tuple[int, int] = (640, 480),
        framerate: int = 30,
        hflip: bool = False,
        vflip: bool = False,
        board: Raspberry | None = None,
    ) -> None:
        if resolution[0] <= 0 or resolution[1] <= 0:
            raise ValueError(f"resolution must be positive, got {resolution}")
        if framerate <= 0:
            raise ValueError(f"framerate must be positive, got {framerate}")
        self.resolution: tuple[int, int] = resolution
        self.framerate: int = framerate
        self.hflip: bool = hflip
        self.vflip: bool = vflip
        self._picam: Any = None            # the Picamera2 instance, once started
        super().__init__(board)

    @property
    def is_open(self) -> bool:
        """True while the camera hardware is started."""
        return self._picam is not None

    def start(self) -> "Camera":
        """Open and start the camera. Idempotent; returns self for chaining."""
        if self._picam is not None:
            return self
        picam = Picamera2()
        # "RGB888" from libcamera arrives as BGR in the numpy array -- exactly
        # what OpenCV expects, so no per-frame conversion is needed.
        main = {"size": self.resolution, "format": "RGB888"}
        kwargs: dict[str, Any] = {"main": main}
        if self.hflip or self.vflip:
            kwargs["transform"] = self._transform()
        picam.configure(picam.create_video_configuration(**kwargs))
        picam.start()
        time.sleep(0.5) # let auto-exposure/white-balance settle
        self._picam = picam
        return self

    def _transform(self) -> Any:
        """A libcamera Transform for the requested h/v flips."""
        return Transform(hflip=int(self.hflip), vflip=int(self.vflip))

    def _release(self) -> None:
        if self._picam is not None:
            try:
                self._picam.stop()
            finally:
                self._picam.close()
            self._picam = None

    def stop(self) -> None:
        """Stop and release the camera (alias for :meth:`close`)."""
        self.close()

    def _ensure_started(self) -> Any:
        if self._picam is None:
            self.start()
        return self._picam

    def capture(self) -> Frame:
        """Grab a single frame as a BGR OpenCV image (numpy ndarray)."""
        picam = self._ensure_started()
        return picam.capture_array()

    def snapshot(self, path: str) -> Frame:
        """Grab one frame and save it to `path` (format from the extension).

        Returns the captured frame so you can use it further.
        """
        frame = self.capture()
        if not cv2.imwrite(path, frame):
            raise RataError(f"could not write image to {path!r}")
        return frame

    def frames(self, limit: int | None = None) -> Iterator[Frame]:
        """Yield BGR frames from the live camera.

        Runs forever by default; pass `limit` to stop after that many frames.
        Paces itself to the configured framerate.
        """
        self._ensure_started()
        period = 1.0 / self.framerate
        count = 0
        while limit is None or count < limit:
            start = time.monotonic()
            yield self.capture()
            count += 1
            slack = period - (time.monotonic() - start)
            if slack > 0:
                time.sleep(slack)

    def stream(self, window: str = "RATA Camera", show_fps: bool = True) -> None:
        """Show a live preview window until you press `q` (or close it).

        A quick way to see what the camera sees. For your own processing use
        :meth:`frames` instead. Blocks until stopped.
        """
        self._ensure_started()
        last = time.monotonic()
        fps = 0.0
        try:
            while True:
                frame = self.capture()
                if show_fps:
                    now = time.monotonic()
                    dt = now - last
                    last = now
                    if dt > 0:
                        fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
                    cv2.putText(
                        frame, f"{fps:4.1f} fps", (8, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                    )
                cv2.imshow(window, frame)
                # 1 ms wait doubles as the key poll; 'q' or a closed window exits.
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            cv2.destroyWindow(window)

    def record(self, path: str, duration: float, fourcc: str = "mp4v") -> None:
        """Record `duration` seconds of video to `path`.

        Encodes with OpenCV's `VideoWriter`; `fourcc` picks the codec
        (e.g. "mp4v" for .mp4, "MJPG" for .avi). Blocks while recording.
        """
        if duration <= 0:
            raise ValueError(f"duration must be positive, got {duration}")
        self._ensure_started()
        w, h = self.resolution
        writer = cv2.VideoWriter(
            path, cv2.VideoWriter.fourcc(*fourcc), float(self.framerate), (w, h)
        )
        if not writer.isOpened():
            raise RataError(f"could not open video writer for {path!r} (codec {fourcc})")
        try:
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                writer.write(self.capture())
        finally:
            writer.release()

    def __repr__(self) -> str:
        w, h = self.resolution
        state = "open" if self.is_open else "closed"
        return f"Camera({w}x{h}@{self.framerate}fps, {state})"

Cam = Camera
