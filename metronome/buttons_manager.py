#!/usr/bin/env python3
"""
ButtonsManager para el metrónomo.

GPIO asignados:
    GPIO 6   → play tap / menú Compás (hold 1.5s)
    GPIO 5   → back tap / salir al boot menu (hold 3s)
    GPIO 25  → abrir menú Modos / seleccionar en menús
    GPIO 22   → navegar abajo / decrementar valor
    GPIO 9  → navegar arriba / incrementar valor
    GPIO 26  → tempo down (tap + hold progresivo)
    GPIO 13  → tempo up   (tap + hold progresivo)

El significado concreto de cada callback lo decide main.py según el estado.
"""

import time
import threading
from gpiozero import Button, Device
from gpiozero.pins.lgpio import LGPIOFactory

Device.pin_factory = LGPIOFactory()

# ── Pines ─────────────────────────────────────────────────────────────────────
PIN_PLAY      = 6
PIN_BACK      = 5
PIN_MENU      = 25
PIN_NAV_DOWN  = 22
PIN_NAV_UP    = 9
PIN_TEMPO_DN  = 26
PIN_TEMPO_UP  = 13

# ── Tiempos de hold ───────────────────────────────────────────────────────────
PLAY_HOLD_TIME = 1.5   # s → menú Compás
BACK_HOLD_TIME = 2.0   # s → boot menu

# ── Hold progresivo de tempo ──────────────────────────────────────────────────
HOLD_INITIAL_DELAY = 0.30
HOLD_REPEAT_MS     = 0.15
HOLD_FAST_THRESH   = 1.5
DELTA_SLOW         = 1
DELTA_FAST         = 10


class ButtonsManager:
    """
    Callbacks públicos — asignar desde main.py:

        on_play_tap      fn()       GPIO 6 tap
        on_play_hold     fn()       GPIO 6 hold 1.5s  → ir a Compás
        on_back          fn()       GPIO 5 tap         → volver / cancelar
        on_exit          fn()       GPIO 5 hold 3s     → boot menu
        on_menu          fn()       GPIO 25 tap        → abrir Modos / seleccionar
        on_nav_down      fn()       GPIO 9             → cursor abajo / valor baja
        on_nav_up        fn()       GPIO 22            → cursor arriba / valor sube
        on_tempo_change  fn(delta)  GPIO 26/13         → ±bpm
    """

    def __init__(self):
        # ── Botones ──────────────────────────────────────────────────────────
        self._btn_play  = Button(PIN_PLAY,     pull_up=True, bounce_time=0.04,
                                 hold_time=PLAY_HOLD_TIME)
        self._btn_back  = Button(PIN_BACK,     pull_up=True, bounce_time=0.04,
                                 hold_time=BACK_HOLD_TIME)
        self._btn_menu  = Button(PIN_MENU,     pull_up=True, bounce_time=0.04)
        self._btn_ndown = Button(PIN_NAV_DOWN, pull_up=True, bounce_time=0.04)
        self._btn_nup   = Button(PIN_NAV_UP,   pull_up=True, bounce_time=0.04)
        self._btn_dn    = Button(PIN_TEMPO_DN, pull_up=True, bounce_time=0.03)
        self._btn_up    = Button(PIN_TEMPO_UP, pull_up=True, bounce_time=0.03)

        # ── Callbacks públicos ───────────────────────────────────────────────
        self.on_play_tap     = None
        self.on_play_hold    = None
        self.on_back         = None
        self.on_exit         = None
        self.on_menu         = None
        self.on_nav_down     = None
        self.on_nav_up       = None
        self.on_tempo_change = None

        # ── Estado interno ────────────────────────────────────────────────────
        self._play_held = False
        self._back_held = False
        self._dn_held   = False
        self._up_held   = False

        # ── Conectar handlers ────────────────────────────────────────────────
        self._btn_play.when_pressed  = self._on_play_press
        self._btn_play.when_held     = self._on_play_held
        self._btn_play.when_released = self._on_play_release

        self._btn_back.when_pressed  = self._on_back_press
        self._btn_back.when_held     = self._on_back_held
        self._btn_back.when_released = self._on_back_release

        self._btn_menu.when_pressed  = lambda: self._call(self.on_menu)
        self._btn_ndown.when_pressed = lambda: self._call(self.on_nav_down)
        self._btn_nup.when_pressed   = lambda: self._call(self.on_nav_up)

        self._btn_dn.when_pressed    = self._on_dn_press
        self._btn_dn.when_released   = self._on_dn_release
        self._btn_up.when_pressed    = self._on_up_press
        self._btn_up.when_released   = self._on_up_release

    # ── Helper ────────────────────────────────────────────────────────────────

    def _call(self, fn, *args):
        if fn:
            try:
                fn(*args)
            except Exception as e:
                print(f"[Buttons] callback error: {e}")

    # ── GPIO 6: play tap / hold ───────────────────────────────────────────────

    def _on_play_press(self):
        self._play_held = False

    def _on_play_held(self):
        self._play_held = True
        self._call(self.on_play_hold)

    def _on_play_release(self):
        if not self._play_held:
            self._call(self.on_play_tap)

    # ── GPIO 5: back tap / exit hold ─────────────────────────────────────────

    def _on_back_press(self):
        self._back_held = False

    def _on_back_held(self):
        self._back_held = True
        self._call(self.on_exit)

    def _on_back_release(self):
        if not self._back_held:
            self._call(self.on_back)

    # ── GPIO 26: tempo down con hold progresivo ───────────────────────────────

    def _on_dn_press(self):
        self._call(self.on_tempo_change, -DELTA_SLOW)
        self._dn_held = True
        threading.Thread(target=self._hold_worker,
                         args=(lambda: self._dn_held, -1),
                         daemon=True).start()

    def _on_dn_release(self):
        self._dn_held = False

    # ── GPIO 13: tempo up con hold progresivo ─────────────────────────────────

    def _on_up_press(self):
        self._call(self.on_tempo_change, +DELTA_SLOW)
        self._up_held = True
        threading.Thread(target=self._hold_worker,
                         args=(lambda: self._up_held, +1),
                         daemon=True).start()

    def _on_up_release(self):
        self._up_held = False

    # ── Worker hold progresivo ────────────────────────────────────────────────

    def _hold_worker(self, is_held_fn, direction):
        t_start = time.monotonic()
        end_time = t_start + HOLD_INITIAL_DELAY
        while time.monotonic() < end_time:
            if not is_held_fn():
                return
            time.sleep(0.01)
        while is_held_fn():
            elapsed = time.monotonic() - t_start
            delta = direction * (DELTA_FAST if elapsed >= HOLD_FAST_THRESH
                                 else DELTA_SLOW)
            self._call(self.on_tempo_change, delta)
            time.sleep(HOLD_REPEAT_MS)

    # ── Cierre limpio ─────────────────────────────────────────────────────────

    def close(self):
        self._dn_held = False
        self._up_held = False
        try:
            self._btn_play.close()
            self._btn_back.close()
            self._btn_menu.close()
            self._btn_ndown.close()
            self._btn_nup.close()
            self._btn_dn.close()
            self._btn_up.close()
        except Exception as e:
            print(f"[Buttons] close error: {e}")
