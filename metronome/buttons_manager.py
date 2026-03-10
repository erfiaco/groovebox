#!/usr/bin/env python3
"""
ButtonsManager para el metrónomo.

GPIO asignados:
    GPIO 6   → start / stop (tap)
    GPIO 26  → tempo down   (tap + hold progresivo)
    GPIO 13  → tempo up     (tap + hold progresivo)
    GPIO 9   → compás 3/4   (tap)
    GPIO 22  → compás 4/4   (tap)

Comportamiento hold progresivo (igual que Practice Player):
    tap            → ±1 bpm, una vez
    hold < 1.5 s   → ±1 bpm cada 150 ms (continuo)
    hold ≥ 1.5 s   → ±10 bpm cada 150 ms (continuo)

Usa gpiozero con LGPIOFactory (compatible con el resto del sistema).
"""

import time
import threading
from gpiozero import Button, Device
from gpiozero.pins.lgpio import LGPIOFactory

Device.pin_factory = LGPIOFactory()

# ── Pines ─────────────────────────────────────────────────────────────────────
PIN_START_STOP = 6
PIN_TEMPO_DN   = 26
PIN_TEMPO_UP   = 13
PIN_TIME_3_4   = 9
PIN_TIME_4_4   = 22

# ── Parámetros del hold progresivo ────────────────────────────────────────────
HOLD_INITIAL_DELAY = 0.30   # s antes de empezar a repetir
HOLD_REPEAT_MS     = 0.15   # s entre repeticiones
HOLD_FAST_THRESH   = 1.5    # s de hold para pasar a ±10
DELTA_SLOW         = 1      # bpm por tick en modo lento
DELTA_FAST         = 10     # bpm por tick en modo rápido


class ButtonsManager:
    """
    Gestiona los 5 botones del metrónomo.

    Callbacks que hay que asignar desde main.py:
        bm.on_start_stop  = fn()
        bm.on_tempo_change = fn(delta: int)   # delta = +1 / -1 / +10 / -10
        bm.on_time_sig    = fn(beats: int)    # 3 o 4
    """

    def __init__(self):
        # ── Botones ──────────────────────────────────────────────────────────
        self._btn_start  = Button(PIN_START_STOP, pull_up=True, bounce_time=0.04)
        self._btn_dn     = Button(PIN_TEMPO_DN,   pull_up=True, bounce_time=0.03)
        self._btn_up     = Button(PIN_TEMPO_UP,   pull_up=True, bounce_time=0.03)
        self._btn_3_4    = Button(PIN_TIME_3_4,   pull_up=True, bounce_time=0.05)
        self._btn_4_4    = Button(PIN_TIME_4_4,   pull_up=True, bounce_time=0.05)

        # ── Callbacks públicos ───────────────────────────────────────────────
        self.on_start_stop   = None   # fn()
        self.on_tempo_change = None   # fn(delta: int)
        self.on_time_sig     = None   # fn(beats: int)

        # ── Estado interno de hold ────────────────────────────────────────────
        self._dn_held        = False
        self._up_held        = False
        self._dn_thread      = None
        self._up_thread      = None

        # ── Conectar handlers ────────────────────────────────────────────────
        self._btn_start.when_pressed  = self._on_start_stop
        self._btn_dn.when_pressed     = self._on_dn_press
        self._btn_dn.when_released    = self._on_dn_release
        self._btn_up.when_pressed     = self._on_up_press
        self._btn_up.when_released    = self._on_up_release
        self._btn_3_4.when_pressed    = lambda: self._call(self.on_time_sig, 3)
        self._btn_4_4.when_pressed    = lambda: self._call(self.on_time_sig, 4)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _call(self, fn, *args):
        if fn:
            try:
                fn(*args)
            except Exception as e:
                print(f"[Buttons] callback error: {e}")

    # ── Start/Stop ────────────────────────────────────────────────────────────

    def _on_start_stop(self):
        self._call(self.on_start_stop)

    # ── Tempo DOWN ────────────────────────────────────────────────────────────

    def _on_dn_press(self):
        # Tap inmediato
        self._call(self.on_tempo_change, -DELTA_SLOW)
        # Arrancar thread de hold
        self._dn_held = True
        self._dn_thread = threading.Thread(
            target=self._hold_worker,
            args=(lambda: self._dn_held, -1),
            daemon=True
        )
        self._dn_thread.start()

    def _on_dn_release(self):
        self._dn_held = False

    # ── Tempo UP ──────────────────────────────────────────────────────────────

    def _on_up_press(self):
        self._call(self.on_tempo_change, +DELTA_SLOW)
        self._up_held = True
        self._up_thread = threading.Thread(
            target=self._hold_worker,
            args=(lambda: self._up_held, +1),
            daemon=True
        )
        self._up_thread.start()

    def _on_up_release(self):
        self._up_held = False

    # ── Worker de hold progresivo ─────────────────────────────────────────────

    def _hold_worker(self, is_held_fn, direction: int):
        """
        Espera HOLD_INITIAL_DELAY, luego envía deltas de forma continua.
        direction: +1 (up) o -1 (down)
        """
        # Esperar antes de empezar a repetir
        t_start = time.monotonic()
        end_time = t_start + HOLD_INITIAL_DELAY

        while time.monotonic() < end_time:
            if not is_held_fn():
                return
            time.sleep(0.01)

        # Loop de repetición
        while is_held_fn():
            elapsed = time.monotonic() - t_start
            if elapsed >= HOLD_FAST_THRESH:
                delta = direction * DELTA_FAST
            else:
                delta = direction * DELTA_SLOW
            self._call(self.on_tempo_change, delta)
            time.sleep(HOLD_REPEAT_MS)

    # ── Cierre limpio ─────────────────────────────────────────────────────────

    def close(self):
        """Libera recursos. Llamar al salir."""
        self._dn_held = False
        self._up_held = False
        try:
            self._btn_start.close()
            self._btn_dn.close()
            self._btn_up.close()
            self._btn_3_4.close()
            self._btn_4_4.close()
        except Exception as e:
            print(f"[Buttons] close error: {e}")
