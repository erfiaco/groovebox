#!/usr/bin/env python3
"""
Metrónomo - main.py

Estados:
    METRONOMO  → pantalla principal, start/stop, tempo
    COMPAS     → menú de configuración del compás
    EDIT       → editar un item del compás (numerador, denominador, beat)

Flujo COMPAS:
    cursor 0        = Numerador
    cursor 1        = Denominador
    cursor 2..N+1   = Beat 0..N-1

    GPIO 9  / 22  → mover cursor
    GPIO 25       → entrar a EDIT del item seleccionado
    GPIO 6  tap   → salvar y volver a METRONOMO
    GPIO 5  tap   → volver a METRONOMO sin salvar

Flujo EDIT:
    GPIO 9  / 22  → cambiar valor
    GPIO 6  tap   → salvar y volver a COMPAS (cursor no cambia)
    GPIO 5  tap   → volver a COMPAS sin salvar (cursor no cambia)
"""

import os
import sys
import signal
import time
import threading
import sounddevice as sd

from metronome       import Metronome
from buttons_manager import ButtonsManager
from oled_display    import OledDisplay, BEAT_ACCENT, BEAT_NORMAL, BEAT_SILENCE, BEAT_NAMES

# ── Audio device ──────────────────────────────────────────────────────────────
sd.default.device = 0

# ── Constantes ────────────────────────────────────────────────────────────────
DEFAULT_BPM        = 60
DEFAULT_NUMERATOR  = 4
DEFAULT_DENOMINATOR = 4

NUMERATOR_MIN  = 1
NUMERATOR_MAX  = 12
DENOMINATOR_OPTIONS = [2, 4, 8, 16]

MODES = ["NORMAL", "MUTE", "INC/DEC", "PLAY", "POLY"]


class MetronomeApp:

    def __init__(self):
        # ── Estado global ─────────────────────────────────────────────────
        # "METRONOMO" | "COMPAS" | "EDIT"
        self._state      = "METRONOMO"
        self._lock       = threading.Lock()
        self._exit_event = threading.Event()

        # ── Modo de reproducción ──────────────────────────────────────────
        self._mode_idx = 0  # índice en MODES
        
        # ── Configuración Studio ──────────────────────────────────────────────
        self._studio = {
            "mute_bars":     0,
            "every_unmuted": 1,
            "increase_bpm":  0,
            "every_bars":    0,
            } 
        self._p_studio       = dict(self._studio)  # pendiente mientras editas
        self._studio_cursor  = 0
        self._edit_source    = "COMPAS"  # "COMPAS" o "STUDIO"

        # ── Compás activo (aplicado al metrónomo) ─────────────────────────
        self._numerator   = DEFAULT_NUMERATOR
        self._denominator = DEFAULT_DENOMINATOR
        self._beat_states = [BEAT_ACCENT] + \
                            [BEAT_NORMAL] * (DEFAULT_NUMERATOR - 1)

        # ── Compás pendiente (editándose en COMPAS/EDIT) ──────────────────
        self._p_numerator   = DEFAULT_NUMERATOR
        self._p_denominator = DEFAULT_DENOMINATOR
        self._p_beat_states = list(self._beat_states)

        # ── Cursor del menú COMPAS ────────────────────────────────────────
        # 0 = Numerador, 1 = Denominador, 2..N+1 = Beat índice
        self._compas_cursor = 0

        # ── Valor temporal en EDIT ────────────────────────────────────────
        self._edit_value = 0   # int (numerador/denominador) o BEAT_* (beat)

        # ── Componentes ───────────────────────────────────────────────────
        self.metro   = Metronome(bpm=DEFAULT_BPM,
                                 beats_per_bar=DEFAULT_NUMERATOR)
        self.metro.beat_sounds = self._build_beat_sounds()
        self.display = OledDisplay()
        self.buttons = ButtonsManager()

        # ── Conectar callbacks ────────────────────────────────────────────
        self.buttons.on_play_tap     = self._on_play_tap
        self.buttons.on_play_hold    = self._on_play_hold
        self.buttons.on_back         = self._on_back
        self.buttons.on_exit         = self._on_exit
        self.buttons.on_menu         = self._on_menu
        self.buttons.on_nav_down     = self._on_nav_down
        self.buttons.on_nav_up       = self._on_nav_up
        self.buttons.on_tempo_change = self._on_tempo_change

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT,  self._signal_handler)

    # =========================================================================
    # Callbacks de botones — enrutan según estado
    # =========================================================================

    def _on_play_tap(self):
        s = self._state
        if s == "METRONOMO":
            self._metro_start_stop()
        elif s == "COMPAS":
            self._compas_save_and_exit()
        elif s == "EDIT":
            self._edit_save_and_exit()
        elif s == "STUDIO":
            self._studio_save_and_exit()

    def _on_play_hold(self):
        if self._state == "METRONOMO":
            self._go_to_compas()

    
    def _on_back(self):
        s = self._state
        if s == "METRONOMO":
            self.metro.muted = not self.metro.muted
            print(f"[Metro] Mute: {self.metro.muted}")
            self._refresh_display()
        elif s == "COMPAS":
            self._go_to_metronomo()
        elif s == "EDIT":
            self._go_to_compas_from_edit()
        elif s == "STUDIO":
            self._go_to_metronomo()
    
    def _on_exit(self):
        print("[Metro] Saliendo al boot menu...")
        self._cleanup()
        os._exit(0)

    def _on_menu(self):
        s = self._state
        if s == "METRONOMO":
            self._go_to_studio()
        elif s == "COMPAS":
            self._edit_source = "COMPAS"
            self._go_to_edit()
        elif s == "STUDIO":
            self._edit_source = "STUDIO"
            self._go_to_edit_studio()

    def _on_nav_down(self):
        s = self._state
        if s == "METRONOMO":
            pass  # sin función
        elif s == "COMPAS":
            self._compas_cursor_move(+1)
        elif s == "EDIT":
            self._edit_change(-1)
        elif s == "STUDIO":
            self._studio_cursor = (self._studio_cursor + 1) % 4
            self._refresh_display()

    def _on_nav_up(self):
        s = self._state
        if s == "METRONOMO":
            pass  # sin función
        elif s == "COMPAS":
            self._compas_cursor_move(-1)
        elif s == "EDIT":
            self._edit_change(+1)
        elif s == "STUDIO":
            self._studio_cursor = (self._studio_cursor - 1) % 4
            self._refresh_display()

    def _on_tempo_change(self, delta):
        if self._state == "METRONOMO":
            from metronome import BPM_MIN, BPM_MAX
            base = (self.metro._pending_bpm
                    if self.metro._pending_bpm is not None
                    else self.metro.bpm)
            new_bpm = max(BPM_MIN, min(BPM_MAX, base + delta))
            self.metro.set_bpm(new_bpm)
            self._refresh_display()

    # =========================================================================
    # METRONOMO
    # =========================================================================

    def _build_beat_sounds(self):
        """Construye la lista de sonidos a partir de beat_states."""
        sounds = []
        for state in self._beat_states:
            if state == BEAT_ACCENT:
                sounds.append(self.metro._accent)
            elif state == BEAT_NORMAL:
                sounds.append(self.metro._beat)
            else:  # BEAT_SILENCE
                sounds.append(None)
        return sounds
    
    def _metro_start_stop(self):
        if self.metro.is_playing:
            self.metro.stop()
            print(f"[Metro] STOP — {self.metro.bpm} BPM")
        else:
            self.metro.start()
            print(f"[Metro] START — {self.metro.bpm} BPM, {self.metro.beats_per_bar}/4")
        self._refresh_display()

    # =========================================================================
    # Navegación entre estados
    # =========================================================================

    def _go_to_compas(self):
        """METRONOMO → COMPAS. Detiene el metro y copia compás activo a pending."""
        if self.metro.is_playing:
            self.metro.stop()
        self._p_numerator   = self._numerator
        self._p_denominator = self._denominator
        self._p_beat_states = list(self._beat_states)
        self._compas_cursor = 0
        self._state = "COMPAS"
        self._refresh_display()
        print("[Metro] → COMPAS")

    def _go_to_metronomo(self):
        """COMPAS → METRONOMO sin salvar."""
        self._state = "METRONOMO"
        self._refresh_display()
        print("[Metro] → METRONOMO (sin salvar)")

    def _compas_save_and_exit(self):
        """COMPAS → METRONOMO salvando los cambios."""
        self._numerator   = self._p_numerator
        self._denominator = self._p_denominator
        self._beat_states = list(self._p_beat_states)
        self.metro.set_time_sig(self._numerator)
        self.metro.beat_sounds = self._build_beat_sounds()
        self._state = "METRONOMO"
        self._refresh_display()
        print(f"[Metro] Compás guardado: {self._numerator}/{self._denominator} "
              f"beats={[BEAT_NAMES[b] for b in self._beat_states]}")
        
    def _go_to_studio(self):
        if self.metro.is_playing:
            self.metro.stop()
        self._p_studio     = dict(self._studio)
        self._studio_cursor = 0
        self._state = "STUDIO"
        self._refresh_display()
        print("[Metro] → STUDIO")

    def _studio_save_and_exit(self):
        self._studio = dict(self._p_studio)
        self._state  = "METRONOMO"
        self._refresh_display()
        print(f"[Metro] Studio guardado: {self._studio}")

    def _go_to_edit_studio(self):
        keys  = ["mute_bars", "every_unmuted", "increase_bpm", "every_bars"]
        key   = keys[self._studio_cursor]
        self._edit_value = self._p_studio[key]
        self._state = "EDIT"
        self._refresh_display()
        print(f"[Metro] → EDIT studio cursor={self._studio_cursor}")

    def _go_to_edit(self):
        """COMPAS → EDIT del item en cursor."""
        cursor = self._compas_cursor
        if cursor == 0:
            self._edit_value = self._p_numerator
        elif cursor == 1:
            self._edit_value = self._p_denominator
        else:
            beat_idx = cursor - 2
            self._edit_value = self._p_beat_states[beat_idx]
        self._state = "EDIT"
        self._refresh_display()
        print(f"[Metro] → EDIT cursor={cursor}")

    def _go_to_compas_from_edit(self):
        if self._edit_source == "STUDIO":
            self._state = "STUDIO"
        else:
            self._state = "COMPAS"
        self._refresh_display()
        print("[Metro] → back from EDIT (sin salvar)")

    def _edit_save_and_exit(self):
        if self._edit_source == "STUDIO":
            keys = ["mute_bars", "every_unmuted", "increase_bpm", "every_bars"]
            key  = keys[self._studio_cursor]
            self._p_studio[key] = self._edit_value
            self._state = "STUDIO"
        else:
            # lógica COMPAS existente
            cursor = self._compas_cursor
            if cursor == 0:
                new_n = self._edit_value
                old_n = len(self._p_beat_states)
                if new_n > old_n:
                    self._p_beat_states += [BEAT_NORMAL] * (new_n - old_n)
                elif new_n < old_n:
                    self._p_beat_states = self._p_beat_states[:new_n]
                self._p_numerator = new_n
            elif cursor == 1:
                self._p_denominator = self._edit_value
            else:
                beat_idx = cursor - 2
                self._p_beat_states[beat_idx] = self._edit_value
            self._state = "COMPAS"
        self._refresh_display()
        print(f"[Metro] Edit guardado: {self._edit_value}")

    # =========================================================================
    # Lógica interna de COMPAS y EDIT
    # =========================================================================

    def _compas_cursor_move(self, direction):
        """Mueve el cursor. direction: +1 abajo, -1 arriba."""
        # Items: 0=Num, 1=Den, 2..N+1=Beats
        max_cursor = 1 + self._p_numerator  # 0,1 + beats
        self._compas_cursor = (self._compas_cursor + direction) % (max_cursor + 1)
        self._refresh_display()

    def _edit_change(self, direction):
        """Cambia el valor en edición. direction: +1 sube, -1 baja."""
        cursor = self._compas_cursor
        if cursor == 0:
            # Numerador
            self._edit_value = max(NUMERATOR_MIN,
                                   min(NUMERATOR_MAX,
                                       self._edit_value + direction))
        elif cursor == 1:
            # Denominador — ciclar entre opciones
            idx = DENOMINATOR_OPTIONS.index(self._edit_value) \
                  if self._edit_value in DENOMINATOR_OPTIONS else 1
            idx = (idx + direction) % len(DENOMINATOR_OPTIONS)
            self._edit_value = DENOMINATOR_OPTIONS[idx]
        else:
            # Beat state — ciclar Acento / Normal / Silencio
            self._edit_value = (self._edit_value + direction) % 3
        self._refresh_display()
        

    def _edit_change(self, direction):
        cursor = self._compas_cursor
        if self._edit_source == "STUDIO":
            keys    = ["mute_bars", "every_unmuted", "increase_bpm", "every_bars"]
            key     = keys[self._studio_cursor]
            min_val = 1 if key == "every_unmuted" else 0
            self._edit_value = max(min_val, self._edit_value + direction)
        elif cursor == 0:
            self._edit_value = max(NUMERATOR_MIN, min(NUMERATOR_MAX, self._edit_value + direction))
                                                                        
        elif cursor == 1:
            idx = DENOMINATOR_OPTIONS.index(self._edit_value) \
                  if self._edit_value in DENOMINATOR_OPTIONS else 1
            idx = (idx + direction) % len(DENOMINATOR_OPTIONS)
            self._edit_value = DENOMINATOR_OPTIONS[idx]
        else:
            self._edit_value = (self._edit_value + direction) % 3
        self._refresh_display()        


    # =========================================================================
    # Display
    # =========================================================================

    def _refresh_display(self):
        s = self._state

        if s == "METRONOMO":
            bpm = (self.metro._pending_bpm
                   if self.metro._pending_bpm is not None
                   else self.metro.bpm)
            beats = self._numerator
            mode  = MODES[self._mode_idx]
            if self.metro.is_playing:
                self.display.show_playing(bpm, beats, mode, muted=self.metro.muted)
            else:
                self.display.show_config(bpm, beats, mode, muted=self.metro.muted)

        elif s == "COMPAS":
            self.display.show_compas(
                self._p_numerator,
                self._p_denominator,
                self._p_beat_states,
                self._compas_cursor
            )
            
        elif s == "STUDIO":
            self.display.show_studio(self._p_studio, self._studio_cursor)

        elif s == "EDIT":
            if self._edit_source == "STUDIO":
                keys   = ["Mute bars", "Every unmuted", "Increase BPM", "Every bars"]
                title  = keys[self._studio_cursor]
                min_v  = 1 if self._studio_cursor == 1 else 0
                self.display.show_edit_number(title, self._edit_value, min_v, 99)
            else:
                cursor = self._compas_cursor
                if cursor == 0:
                    self.display.show_edit_number(
                        "Numerador", self._edit_value,
                        NUMERATOR_MIN, NUMERATOR_MAX)
                elif cursor == 1:
                    self.display.show_edit_number(
                        "Denominador", self._edit_value,
                        DENOMINATOR_OPTIONS[0], DENOMINATOR_OPTIONS[-1])
                else:
                    self.display.show_edit_beat(cursor - 2, self._edit_value)
                

    # =========================================================================
    # Loop principal
    # =========================================================================

    def run(self):
        print("[Metro] Iniciando...")
        self._refresh_display()
        print(f"[Metro] Listo — {DEFAULT_BPM} BPM, {DEFAULT_NUMERATOR}/4")
        print("[Metro] GPIO: 6=play/compas | 26↓ 13↑ | 25=menu | 9↓ 22↑ nav | 5=back/exit")
        try:
            while not self._exit_event.wait(0.1):
                pass
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._cleanup()

    def _cleanup(self):
        print("[Metro] Cerrando...")
        if self.metro.is_playing:
            self.metro.stop()
        self.buttons.close()
        self.display.clear()
        print("[Metro] Cerrado.")
                # Volver al boot menu
        
        import subprocess
        subprocess.Popen(["/usr/bin/python3", "/home/Javo/Proyects/boot_menu/boot_menu.py"])

    def _signal_handler(self, signum, frame):
        raise SystemExit(0)


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MetronomeApp()
    app.run()
