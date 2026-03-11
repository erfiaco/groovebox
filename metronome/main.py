#!/usr/bin/env python3
"""
Metrónomo - main.py

State machine:
    STOPPED  →  (GPIO 6)  →  PLAYING
    PLAYING  →  (GPIO 6)  →  STOPPED

En STOPPED:
    - OLED muestra pantalla de configuración
    - GPIO 26 / 13 cambian BPM (efecto inmediato)
    - GPIO 9 / 22 cambian compás (efecto inmediato)

En PLAYING:
    - OLED muestra BPM grande
    - GPIO 26 / 13 cambian BPM (se aplica al final del compás actual)
    - GPIO 9 / 22 cambian compás (se aplica al final del compás actual)

Salida limpia: Ctrl+C (headless) o SIGTERM desde el boot menu.
"""

import sys
import signal
import time
import threading

from metronome      import Metronome
from buttons_manager import ButtonsManager
from oled_display   import OledDisplay
import sounddevice as sd
sd.default.device = 0

# ── Configuración inicial ────────────────────────────────────────────────────

DEFAULT_BPM       = 60
DEFAULT_BEATS     = 4
BPM_MIN           = 20
BPM_MAX           = 300

# Nombres de los modos (por ahora solo NORMAL está activo)
MODES = ["NORMAL", "MUTE", "INC/DEC", "PLAY", "POLY"]
current_mode_idx  = 0   # NORMAL


# ── State machine ────────────────────────────────────────────────────────────

class MetronomeApp:

    def __init__(self):
        self._state = "STOPPED"   # "STOPPED" | "PLAYING"
        self._lock  = threading.Lock()

        # Componentes
        self.metro   = Metronome(bpm=DEFAULT_BPM, beats_per_bar=DEFAULT_BEATS)
        self.display = OledDisplay()
        self.buttons = ButtonsManager()

        # Conectar callbacks de botones
        self.buttons.on_start_stop   = self._on_start_stop
        self.buttons.on_tempo_change = self._on_tempo_change
        self.buttons.on_time_sig     = self._on_time_sig
        self.buttons.on_exit         = self._on_exit

        # Conectar callback de beat (para posibles usos futuros)
        self.metro.on_beat = self._on_beat

        # Señales de sistema para salida limpia
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT,  self._signal_handler)

    # ── Propiedades de estado ─────────────────────────────────────────────

    @property
    def bpm(self):
        return self.metro.bpm

    @property
    def beats(self):
        return self.metro.beats_per_bar

    @property
    def mode_name(self):
        return MODES[current_mode_idx]

    # ── Callbacks de botones ──────────────────────────────────────────────

    def _on_start_stop(self):
        with self._lock:
            if self._state == "STOPPED":
                self._do_start()
            else:
                self._do_stop()

    def _on_tempo_change(self, delta: int):
        new_bpm = max(BPM_MIN, min(BPM_MAX, self.metro.bpm + delta))
        # Si hay pending_bpm, lo sumamos desde ahí para no perder teclas rápidas
        if self.metro._pending_bpm is not None:
            new_bpm = max(BPM_MIN, min(BPM_MAX, self.metro._pending_bpm + delta))
        self.metro.set_bpm(new_bpm)
        self._refresh_display()

    def _on_time_sig(self, beats: int):
        self.metro.set_time_sig(beats)
        self._refresh_display()

    def _on_beat(self, beat_in_bar: int, beats_per_bar: int):
        """
        Llamado desde el thread del metrónomo en cada beat.
        Por ahora no hace nada visible (BPM en pantalla es estático).
        En el futuro: pulso visual, resaltar beat, etc.
        """
        pass
    
    def _on_exit(self):
        print("[Metro] Saliendo al boot menu...")
        raise SystemExit(0)

    # ── Transiciones de estado ────────────────────────────────────────────

    def _do_start(self):
        self._state = "PLAYING"
        self.metro.start()
        self._refresh_display()
        print(f"[Metro] START — {self.bpm} BPM, {self.beats}/4")

    def _do_stop(self):
        self._state = "STOPPED"
        self.metro.stop()
        self._refresh_display()
        print(f"[Metro] STOP — {self.bpm} BPM")

    # ── Display ───────────────────────────────────────────────────────────

    def _refresh_display(self):
        """Actualiza el OLED según el estado actual."""
        # Tomar el BPM efectivo: pending si existe (lo que el usuario verá pronto)
        visible_bpm = self.metro._pending_bpm if self.metro._pending_bpm else self.bpm
        visible_beats = self.metro._pending_beats if self.metro._pending_beats else self.beats

        if self._state == "PLAYING":
            self.display.show_playing(visible_bpm, visible_beats, self.mode_name)
        else:
            self.display.show_config(visible_bpm, visible_beats, self.mode_name)

    # ── Loop principal ────────────────────────────────────────────────────

    def run(self):
        print("[Metro] Iniciando metrónomo...")
        self._refresh_display()
        print(f"[Metro] Listo — {DEFAULT_BPM} BPM, {DEFAULT_BEATS}/4")
        print("[Metro] GPIO 6 = start/stop | 26 = BPM- | 13 = BPM+ | 9 = 3/4 | 22 = 4/4")

        try:
            while True:
                time.sleep(0.1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._cleanup()

    def _cleanup(self):
        print("[Metro] Cerrando...")
        if self._state == "PLAYING":
            self.metro.stop()
        self.buttons.close()
        self.display.clear()
        print("[Metro] Cerrado limpiamente.")

    def _signal_handler(self, signum, frame):
        print(f"[Metro] Señal {signum} recibida — saliendo.")
        raise SystemExit(0)


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MetronomeApp()
    app.run()
