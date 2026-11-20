import threading
import time
from gpiozero import LED, Device
from gpiozero.pins.lgpio import LGPIOFactory

Device.pin_factory = LGPIOFactory()

PIN_ACCENT     = 23
PIN_BEAT       = 24
FLASH_DURATION = 0.04


class MetroLed:

    def __init__(self, bpm=120, beats_per_bar=4):
        self.bpm            = bpm
        self.beats_per_bar  = beats_per_bar

        # Optional callback: fn(beat_in_bar: int, beats_per_bar: int)
        self.on_beat = None

        self._led_accent = LED(PIN_ACCENT)
        self._led_beat   = LED(PIN_BEAT)

        self._running    = False
        self._stop_event = threading.Event()
        self._thread     = None
        self._anchor     = None

    @property
    def running(self):
        return self._running

    def start(self, anchor=None):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._anchor  = anchor if anchor is not None else time.perf_counter()
        self._thread  = threading.Thread(target=self._run, daemon=True, name='metro-led')
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_event.set()
        self._led_accent.off()
        self._led_beat.off()

    def close(self):
        self.stop()
        try:
            self._led_accent.close()
            self._led_beat.close()
        except Exception:
            pass

    def _wait_until(self, target):
        remaining = target - time.perf_counter()
        if remaining > 0.003:
            self._stop_event.wait(timeout=remaining - 0.002)
        while time.perf_counter() < target:
            pass

    def _run(self):
        interval = 60.0 / self.bpm
        bpb      = self.beats_per_bar
        i        = 0

        while self._running:
            beat_time   = self._anchor + i * interval
            beat_in_bar = (i % bpb) + 1

            if beat_in_bar == 1:
                self._led_accent.on()
                self._led_beat.off()
            else:
                self._led_accent.off()
                self._led_beat.on()

            if self.on_beat:
                try:
                    self.on_beat(beat_in_bar, bpb)
                except Exception:
                    pass

            self._wait_until(beat_time + FLASH_DURATION)
            self._led_accent.off()
            self._led_beat.off()

            self._wait_until(beat_time + interval)
            i += 1
