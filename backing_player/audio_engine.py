"""
BackingEngine: plays a backing WAV and records one layer on the loop section.

States:
  IDLE       - stopped, no audio
  COUNTDOWN  - metro LED counting down, audio silent
  PLAYING    - playing backing from start up to bucle_start
  RECORDING  - playing bucle section and capturing input
  LOOPING    - looping bucle section (backing + rec_buffer)
  CODA       - playing coda section to end

Recording architecture:
  rec_buffer is pre-allocated for exactly (bucle_end - bucle_start) samples.
  Designed to support future overdub layers: rec_buffer is kept separate from
  backing and mixed in _cb_looping, so additional layers can be added later.
"""

import queue
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 44100
CHANNELS    = 2
BLOCKSIZE   = 256


class BackingEngine:

    def __init__(self):
        self._lock = threading.Lock()

        self._backing     = None   # full backing WAV (N, 2) float32
        self._meta        = None   # dict parsed from JSON
        self._bar_samples = 0      # samples per bar

        # Boundary positions in samples
        self._bucle_start = 0
        self._bucle_end   = 0
        self._coda_start  = 0
        self._coda_end    = 0
        self._loop_len    = 0
        self._total_bars  = 0

        # Playback cursors
        self._play_pos = 0   # position in backing array (PLAYING / RECORDING / CODA)
        self._loop_pos = 0   # position within loop section (LOOPING)

        # Recording
        self._rec_buffer = None   # float32 (loop_len, 2)
        self._rec_pos    = 0
        self._mute_input = False
        self._recorded   = False

        # Control flags
        self._state    = 'IDLE'
        self._last_rep = False
        self._volume   = 1.0

        self._stop_event = threading.Event()
        self._cd_thread  = None

        # Streams
        self._in_stream  = None
        self._out_stream = None

        # External callback: fn(state: str)
        self.on_state_change = None

        # Persistent notification worker — audio callbacks never create threads
        self._notify_queue  = queue.Queue()
        self._notify_thread = threading.Thread(target=self._notify_worker, daemon=True)
        self._notify_thread.start()

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self):
        return self._state

    @property
    def meta(self):
        return self._meta

    @property
    def last_rep(self):
        return self._last_rep

    @property
    def mute_input(self):
        return self._mute_input

    @property
    def silenced(self):
        return self._volume == 0.0

    @property
    def recorded(self):
        return self._recorded

    @property
    def current_bar(self):
        bs = self._bar_samples
        if bs == 0:
            return 0
        state = self._state
        if state in ('PLAYING', 'RECORDING'):
            return self._play_pos // bs + 1
        if state == 'LOOPING':
            return self._meta['bucle'][0] + self._loop_pos // bs
        if state == 'CODA':
            return self._meta['coda'][0] + (self._play_pos - self._coda_start) // bs
        return 0

    @property
    def total_bars(self):
        return self._total_bars

    # ── Public API ───────────────────────────────────────────────────────

    def load_track(self, wav_path, meta):
        audio, sr = sf.read(wav_path, dtype='float32', always_2d=True)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)

        self._backing = audio
        self._meta    = meta

        tempo  = meta['tempo']
        beats  = int(str(meta['compas']).split('/')[0])
        bs     = int(round((60.0 / tempo) * beats * SAMPLE_RATE))
        self._bar_samples = bs

        bucle = meta['bucle']
        coda  = meta['coda']
        self._bucle_start = (bucle[0] - 1) * bs
        self._bucle_end   = bucle[1] * bs
        self._coda_start  = (coda[0] - 1) * bs
        self._coda_end    = min(coda[1] * bs, len(audio))
        self._loop_len    = self._bucle_end - self._bucle_start
        self._total_bars  = meta['tot_cc']

        self._rec_buffer = np.zeros((self._loop_len, CHANNELS), dtype=np.float32)
        self._recorded   = False
        self._last_rep   = False
        self._volume     = 1.0
        self._mute_input = False
        self._state      = 'IDLE'

        print(f"[BackingEngine] loaded: {wav_path}")
        print(f"  bar_samples={bs}  bucle={self._bucle_start}-{self._bucle_end}"
              f"  coda={self._coda_start}-{self._coda_end}")

    def start_streams(self):
        if self._in_stream is not None:
            return
        self._in_stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            callback=self._input_cb, blocksize=BLOCKSIZE,
            latency='low', dtype='float32'
        )
        self._out_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            callback=self._output_cb, blocksize=BLOCKSIZE,
            latency='low', dtype='float32'
        )
        self._in_stream.start()
        self._out_stream.start()
        print(f"[BackingEngine] input  latency: {self._in_stream.latency*1000:.1f} ms")
        print(f"[BackingEngine] output latency: {self._out_stream.latency*1000:.1f} ms")

    def start_play(self, metro_led, cc_playback, bar_dur_sec):
        if self._backing is None or self._state != 'IDLE':
            return
        self._stop_event.clear()
        self._cd_thread = threading.Thread(
            target=self._run_countdown,
            args=(metro_led, cc_playback, bar_dur_sec),
            daemon=True, name='backing-countdown'
        )
        self._cd_thread.start()

    def stop(self):
        self._stop_event.set()
        self._state = 'IDLE'
        self._notify('IDLE')

    def toggle_last_rep(self):
        self._last_rep = not self._last_rep
        return self._last_rep

    def toggle_silence(self):
        """
        If recording: mute/unmute the input capture (zeros to buffer).
        Otherwise:    toggle output volume between 1.0 and 0.0.
        """
        if self._state == 'RECORDING':
            self._mute_input = not self._mute_input
        elif self._state in ('PLAYING', 'LOOPING', 'CODA'):
            self._volume = 0.0 if self._volume > 0 else 1.0

    def save_recording(self, path):
        if not self._recorded or self._rec_buffer is None:
            return False
        try:
            sf.write(path, self._rec_buffer, SAMPLE_RATE)
            print(f"[BackingEngine] recording saved: {path}")
            return True
        except Exception as e:
            print(f"[BackingEngine] save error: {e}")
            return False

    def close(self):
        self._stop_event.set()
        for stream in (self._in_stream, self._out_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._in_stream  = None
        self._out_stream = None

    # ── Internal helpers ─────────────────────────────────────────────────

    def _notify_worker(self):
        while True:
            state = self._notify_queue.get()
            if state is None:
                return
            if self.on_state_change:
                self.on_state_change(state)

    def _notify(self, state):
        try:
            self._notify_queue.put_nowait(state)
        except queue.Full:
            pass

    def _wait_until(self, target):
        remaining = target - time.perf_counter()
        if remaining > 0.003:
            self._stop_event.wait(timeout=remaining - 0.002)
        while time.perf_counter() < target:
            pass

    # ── Countdown thread ─────────────────────────────────────────────────

    def _run_countdown(self, metro_led, cc_playback, bar_dur_sec):
        self._state = 'COUNTDOWN'
        self._notify('COUNTDOWN')

        anchor = time.perf_counter()
        metro_led.bpm           = self._meta['tempo']
        metro_led.beats_per_bar = int(str(self._meta['compas']).split('/')[0])
        metro_led.start(anchor=anchor)

        target = anchor + cc_playback * bar_dur_sec
        self._wait_until(target)
        metro_led.stop()

        if self._stop_event.is_set():
            self._state = 'IDLE'
            self._notify('IDLE')
            return

        self._play_pos   = 0
        self._loop_pos   = 0
        self._rec_pos    = 0
        if self._rec_buffer is not None:
            self._rec_buffer[:] = 0
        self._recorded   = False
        self._mute_input = False
        self._volume     = 1.0

        self._state = 'PLAYING'
        self._notify('PLAYING')

    # ── Audio callbacks ──────────────────────────────────────────────────

    def _input_cb(self, indata, frames, time_info, status):
        if self._state == 'RECORDING' and self._rec_buffer is not None:
            end = self._rec_pos + frames
            if end <= len(self._rec_buffer):
                if self._mute_input:
                    self._rec_buffer[self._rec_pos:end] = 0
                else:
                    self._rec_buffer[self._rec_pos:end] = indata[:frames]
                self._rec_pos = end

    def _output_cb(self, outdata, frames, time_info, status):
        outdata[:] = 0
        state = self._state

        if state in ('IDLE', 'COUNTDOWN'):
            return
        if state in ('PLAYING', 'RECORDING'):
            self._cb_linear(outdata, frames)
        elif state == 'LOOPING':
            self._cb_looping(outdata, frames)
        elif state == 'CODA':
            self._cb_coda(outdata, frames)

    def _cb_linear(self, outdata, frames):
        """Output backing sequentially; detect bucle_start and bucle_end crossings."""
        pos     = self._play_pos
        backing = self._backing
        state   = self._state
        vol     = self._volume

        avail = len(backing) - pos
        if avail <= 0:
            self._state = 'IDLE'
            self._notify('IDLE')
            return

        actual = min(frames, avail)
        outdata[:actual] = backing[pos:pos + actual] * vol
        new_pos = pos + actual
        self._play_pos = new_pos

        if state == 'PLAYING' and new_pos > self._bucle_start:
            self._rec_pos = 0
            self._state   = 'RECORDING'
            self._notify('RECORDING')
            return

        if self._state == 'RECORDING' and new_pos >= self._bucle_end:
            self._recorded = True
            self._loop_pos = 0
            self._state    = 'LOOPING'
            self._notify('LOOPING')

    def _cb_looping(self, outdata, frames):
        """Loop bucle section: backing slice + rec_buffer, mixed."""
        loop_start = self._bucle_start
        loop_len   = self._loop_len
        lp         = self._loop_pos
        vol        = self._volume
        backing    = self._backing
        rec        = self._rec_buffer

        rem    = frames
        offset = 0

        while rem > 0:
            chunk = min(rem, loop_len - lp)
            outdata[offset:offset + chunk] = (
                backing[loop_start + lp : loop_start + lp + chunk] +
                rec[lp : lp + chunk]
            ) * vol
            lp     += chunk
            offset += chunk
            rem    -= chunk

            if lp >= loop_len:
                lp = 0
                if self._last_rep:
                    self._loop_pos = 0
                    self._state    = 'CODA'
                    self._play_pos = self._coda_start
                    self._notify('CODA')
                    return   # remaining frames are zeros (outdata zeroed at top)

        self._loop_pos = lp

    def _cb_coda(self, outdata, frames):
        """Play coda section then stop."""
        pos      = self._play_pos
        coda_end = self._coda_end
        vol      = self._volume

        avail = coda_end - pos
        if avail <= 0:
            self._state = 'IDLE'
            self._notify('IDLE')
            return

        actual = min(frames, avail)
        outdata[:actual] = self._backing[pos:pos + actual] * vol
        self._play_pos   = pos + actual

        if self._play_pos >= coda_end:
            self._state = 'IDLE'
            self._notify('IDLE')
