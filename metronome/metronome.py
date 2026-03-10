#!/usr/bin/env python3
"""
Metronome engine.

- Timing por tiempo absoluto (sin drift).
- Dos sonidos: accent (tiempo 1) y beat (resto).
- Carga WAVs externos si existen en sounds/, genera sine bursts si no.
- BPM y compás se aplican al final del compás actual cuando está sonando.
- stop_event para detener el thread instantáneamente.
"""

import numpy as np
import sounddevice as sd
import soundfile as sf
import threading
import time
import os

SAMPLE_RATE  = 44100
CLICK_DURATION = 0.025   # 25ms
ACCENT_FREQ  = 880        # Hz - tiempo 1
BEAT_FREQ    = 440        # Hz - tiempos 2..N
BPM_MIN      = 20
BPM_MAX      = 300


# ─── Generación / carga de sonidos ───────────────────────────────────────────

def _generate_tone(freq: float, duration: float, sample_rate: int,
                   amplitude: float = 0.8) -> np.ndarray:
    """Sine burst con fade-out rápido en la segunda mitad."""
    n = int(sample_rate * duration)
    t = np.linspace(0, duration, n, False)
    tone = amplitude * np.sin(2 * np.pi * freq * t).astype(np.float32)
    # Envelope: mantiene amplitud en primera mitad, fade a 0 en segunda
    fade_len = n // 2
    tone[n - fade_len:] *= np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
    return tone


def _load_or_generate(path, freq):

    """
    Intenta cargar WAV en `path`.
    Si no existe o falla, genera un tono sine.
    El audio se normaliza a mono float32 @ SAMPLE_RATE.
    """
    if path and os.path.exists(path):
        try:
            data, sr = sf.read(path, dtype='float32', always_2d=False)
            if data.ndim > 1:
                data = data[:, 0]           # mono
            # No re-samplea: asume que el usuario pone WAVs a 44100
            return data
        except Exception as e:
            print(f"[Metronome] No se pudo cargar {path}: {e}. Usando sine.")
    return _generate_tone(freq, CLICK_DURATION, SAMPLE_RATE)


# ─── Clase principal ──────────────────────────────────────────────────────────

class Metronome:
    """
    Motor del metrónomo.

    Uso básico:
        metro = Metronome(bpm=60, beats_per_bar=4)
        metro.on_beat = lambda beat, total: print(beat)
        metro.start()
        ...
        metro.stop()

    Cambio en tiempo real:
        metro.set_bpm(120)        # Se aplica al acabar el compás actual
        metro.set_time_sig(3)     # Ídem

    Sonidos:
        Poner accent.wav / beat.wav en sounds/ para reemplazar los sine bursts.
        O llamar metro.load_sounds(accent_path, beat_path) manualmente.
    """

    def __init__(self,
                 bpm: int = 60,
                 beats_per_bar: int = 4,
                 sounds_dir=None):

        self.bpm           = bpm
        self.beats_per_bar = beats_per_bar
        self._pending_bpm   = None   # se aplica al fin del compás
        self._pending_beats = None

        # Cargar / generar sonidos
        if sounds_dir is None:
            sounds_dir = os.path.join(os.path.dirname(__file__), "sounds")

        accent_path = os.path.join(sounds_dir, "accent.wav")
        beat_path   = os.path.join(sounds_dir, "beat.wav")
        self._accent = _load_or_generate(accent_path, ACCENT_FREQ)
        self._beat   = _load_or_generate(beat_path,   BEAT_FREQ)

        # Thread control
        self._stop_event = threading.Event()
        self._thread     = None
        self.is_playing  = False

        # Callback externo: fn(beat_in_bar: int, beats_per_bar: int)
        # Se llama desde el thread del metrónomo (no bloquear demasiado)
        self.on_beat = None

    # ── API pública ────────────────────────────────────────────────────────

    def load_sounds(self, accent_path=None, beat_path=None):
        """Recarga sonidos en caliente (efecto al próximo beat)."""
        if accent_path:
            self._accent = _load_or_generate(accent_path, ACCENT_FREQ)
        if beat_path:
            self._beat = _load_or_generate(beat_path, BEAT_FREQ)

    def set_bpm(self, bpm: int):
        """
        Cambia el BPM.
        Si está sonando, el cambio se aplica al acabar el compás actual.
        Si está parado, el cambio es inmediato.
        """
        bpm = max(BPM_MIN, min(BPM_MAX, int(bpm)))
        if self.is_playing:
            self._pending_bpm = bpm
        else:
            self.bpm = bpm

    def set_time_sig(self, beats_per_bar: int):
        """
        Cambia el número de tiempos por compás.
        Mismo comportamiento diferido que set_bpm.
        """
        beats_per_bar = max(1, int(beats_per_bar))
        if self.is_playing:
            self._pending_beats = beats_per_bar
        else:
            self.beats_per_bar = beats_per_bar

    def start(self):
        if self.is_playing:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="metronome-beat")
        self.is_playing = True
        self._thread.start()

    def stop(self):
        if not self.is_playing:
            return
        self.is_playing = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        try:
            sd.stop()
        except Exception:
            pass

    # ── Thread de timing ──────────────────────────────────────────────────

    def _run(self):
        """
        Loop principal del metrónomo.

        Timing por tiempo absoluto:
            next_beat = anchor_time + beat_count * interval
        Así los errores de sleep no se acumulan.

        Cuando cambia el BPM al final del compás, se reinicia el anchor
        para evitar saltos de fase.
        """
        interval    = 60.0 / self.bpm
        anchor_time = time.perf_counter()
        beat_count  = 0   # beats desde el último anchor

        while not self._stop_event.is_set():

            beat_in_bar = (beat_count % self.beats_per_bar) + 1  # 1..N

            # ── Audio ────────────────────────────────────────────────
            sound = self._accent if beat_in_bar == 1 else self._beat
            try:
                sd.play(sound, SAMPLE_RATE)
            except Exception as e:
                print(f"[Metronome] sd.play error: {e}")

            # ── Callback al exterior ─────────────────────────────────
            if self.on_beat:
                try:
                    self.on_beat(beat_in_bar, self.beats_per_bar)
                except Exception as e:
                    print(f"[Metronome] on_beat callback error: {e}")

            beat_count += 1

            # ── Aplicar cambios pendientes al final del compás ───────
            if beat_in_bar == self.beats_per_bar:
                changed = False
                if self._pending_bpm is not None:
                    self.bpm        = self._pending_bpm
                    self._pending_bpm = None
                    interval        = 60.0 / self.bpm
                    changed         = True
                if self._pending_beats is not None:
                    self.beats_per_bar   = self._pending_beats
                    self._pending_beats  = None
                    changed              = True
                if changed:
                    # Reiniciar anchor para evitar drift al cambiar interval
                    anchor_time = time.perf_counter()
                    beat_count  = 0

            # ── Esperar al próximo beat ──────────────────────────────
            next_beat = anchor_time + beat_count * interval
            remaining = next_beat - time.perf_counter()

            # Sleep hasta 2ms antes (libera CPU, pero wakeup no es exacto)
            if remaining > 0.003:
                self._stop_event.wait(timeout=remaining - 0.002)

            if self._stop_event.is_set():
                break

            # Busy-wait los últimos ~2ms para precisión real
            while time.perf_counter() < next_beat:
                pass
