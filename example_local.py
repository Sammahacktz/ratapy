"""Master-attached devices: hardware wired straight to the Raspberry Pi.

Some devices are too heavy for an Arduino (camera, addressable LED strip), so
they plug into the Pi itself. The API is the same as any RATA device -- you just
pass the Raspberry as the board. Run this ON a Raspberry Pi with a camera and a
WS2812 strip attached. Needs: python3-picamera2, opencv-python, rpi_ws281x.
"""

from ratapy import Raspberry
from ratapy.devices import PiCam, PiNeoPixel

rp = Raspberry()                          # the master; no Arduino needed here

cam = PiCam(board=rp)                       # Pi camera via Picamera2 + OpenCV
strip = PiNeoPixel(count=30, board=rp)      # WS2812 strip on GPIO18

# PiCamera helpers
cam.snapshot("photo.jpg")                 # grab one frame and save it
cam.record("clip.mp4", duration=5)        # record 5 seconds of video

# LED strip: stage the buffer, then show()
strip.fill((0, 40, 0))                    # dim green everywhere
strip[0] = (255, 0, 0)                    # first pixel red
strip.show()

# Live preview window (press q to quit) -- comment out for a headless Pi
cam.stream()

rp.close()                                # stops the camera, clears the strip
