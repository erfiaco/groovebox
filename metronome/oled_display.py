#!/usr/bin/env python3
"""
OledDisplay para el metrónomo.

Layouts:
  show_config(bpm, beats, mode_name)
  show_playing(bpm, beats, mode_name)
  show_compas(numerator, denominator, beat_states, cursor_pos)
  show_edit_number(title, value, min_val, max_val)
  show_edit_beat(beat_index, state_name)
  show_message(line1, line2)

Estados de beat:
  0 = Acento   → círculo relleno  ●
  1 = Normal   → círculo vacío    ○
  2 = Silencio → punto central    ·
"""

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
import threading

# Estados de beat
BEAT_ACCENT  = 0
BEAT_NORMAL  = 1
BEAT_SILENCE = 2
BEAT_NAMES   = ["Acento", "Normal", "Silencio"]


class OledDisplay:

    def __init__(self, port=1, address=0x3C, width=128, height=64):
        self._lock = threading.Lock()
        serial = i2c(port=port, address=address)
        self._device = ssd1306(serial, width=width, height=height)
        self.W, self.H = self._device.size

        try:
            path_bold  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            path_plain = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            self._font_huge  = ImageFont.truetype(path_bold,  36)
            self._font_big   = ImageFont.truetype(path_bold,  16)
            self._font_med   = ImageFont.truetype(path_plain, 13)
            self._font_small = ImageFont.truetype(path_plain, 10)
        except Exception:
            fallback = ImageFont.load_default()
            self._font_huge  = fallback
            self._font_big   = fallback
            self._font_med   = fallback
            self._font_small = fallback

    # ── Pantalla metrónomo parado ─────────────────────────────────────────────

    def show_config(self, bpm, beats, mode_name="NORMAL", muted=False):
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)
        d.text((0, 0),  "METRO", font=self._font_big, fill=255)
        mode_x = self.W - self._tw(d, mode_name, self._font_small) - 2
        d.text((mode_x, 4), mode_name, font=self._font_small, fill=255)
        d.line([(0, 18), (self.W, 18)], fill=255)
        d.text((0, 21), "BPM:",  font=self._font_med, fill=255)
        d.text((50, 21), str(bpm), font=self._font_med, fill=255)
        d.text((0, 37), "Comp:", font=self._font_med, fill=255)
        d.text((50, 37), f"{beats}/4", font=self._font_med, fill=255)
        d.text((0, 53), "26\u2193  6=PLAY  13\u2191", font=self._font_small, fill=255)
        if muted:
            d.text((2, 54), "MUTE", font=self._font_small, fill=255)
        self._display(img)

    # ── Pantalla metrónomo sonando ────────────────────────────────────────────

    def show_playing(self, bpm, beats, mode_name="NORMAL", muted=False):
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)
        bpm_str = str(bpm)
        bpm_x   = (self.W - self._tw(d, bpm_str, self._font_huge)) // 2
        d.text((bpm_x, 4), bpm_str, font=self._font_huge, fill=255)
        sig_str = f"{beats}/4"
        sig_x   = (self.W - self._tw(d, sig_str, self._font_med)) // 2
        d.text((sig_x, 46), sig_str, font=self._font_med, fill=255)
        mode_abbr = mode_name[0] if mode_name else "N"
        d.text((self.W - self._tw(d, mode_abbr, self._font_small) - 2, 54),
               mode_abbr, font=self._font_small, fill=255)
        if muted:
            d.text((2, 54), "MUTE", font=self._font_small, fill=255)
        self._display(img)

    # ── Pantalla COMPÁS ───────────────────────────────────────────────────────

    def show_compas(self, numerator, denominator, beat_states, cursor_pos):
        """
        cursor_pos:
            0          → Numerador seleccionado
            1          → Denominador seleccionado
            2..N+1     → Beat (cursor_pos - 2) seleccionado

        beat_states: lista de int (BEAT_ACCENT / BEAT_NORMAL / BEAT_SILENCE)

        Layout:
            ┌──────────────────────────┐
            │ COMPAS                   │
            │ [4] / 4   ó  4 / [4]    │  ← brackets si cursor en num/den
            │  ● ○ ○ ○                │  ← círculos de beats
            │  ^                       │  ← cursor bajo el beat seleccionado
            │ 25=edit  6=ok  5=cancel  │
            └──────────────────────────┘
        """
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)

        # Título
        d.text((0, 0), "COMPAS", font=self._font_big, fill=255)
        d.line([(0, 18), (self.W, 18)], fill=255)

        # Numerador / Denominador
        num_str = f"[{numerator}]" if cursor_pos == 0 else str(numerator)
        den_str = f"[{denominator}]" if cursor_pos == 1 else str(denominator)
        sig_str = f"{num_str} / {den_str}"
        d.text((0, 21), sig_str, font=self._font_med, fill=255)

        # Círculos de beats
        n       = len(beat_states)
        r       = 5           # radio del círculo
        spacing = 14          # separación entre centros
        total_w = n * spacing - (spacing - 2 * r)
        x_start = (self.W - total_w) // 2
        y_circ  = 38

        for i, state in enumerate(beat_states):
            cx = x_start + i * spacing + r
            cy = y_circ
            x0, y0 = cx - r, cy - r
            x1, y1 = cx + r, cy + r

            if state == BEAT_ACCENT:
                d.ellipse([(x0, y0), (x1, y1)], fill=255)
            elif state == BEAT_NORMAL:
                d.ellipse([(x0, y0), (x1, y1)], outline=255)
            else:  # SILENCE
                d.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=255)

            # Cursor bajo el beat seleccionado
            if cursor_pos >= 2 and (cursor_pos - 2) == i:
                d.text((cx - 2, y_circ + r + 2), "^", font=self._font_small, fill=255)

        # Ayuda
        d.text((0, 54), "25=edit 6=ok 5=cancel", font=self._font_small, fill=255)

        self._display(img)

    # ── Pantalla EDIT número (numerador / denominador) ────────────────────────

    def show_edit_number(self, title, value, min_val, max_val):
        """
        ┌──────────────────────────┐
        │ Numerador                │
        │                          │
        │          4               │  ← valor grande
        │       (1 – 12)           │  ← rango
        │ 9↑  22↓   6=ok  5=cancel │
        └──────────────────────────┘
        """
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)

        d.text((0, 0), title, font=self._font_big, fill=255)
        d.line([(0, 18), (self.W, 18)], fill=255)

        val_str = str(value)
        val_x   = (self.W - self._tw(d, val_str, self._font_huge)) // 2
        d.text((val_x, 19), val_str, font=self._font_huge, fill=255)

        range_str = f"({min_val} \u2013 {max_val})"
        range_x   = (self.W - self._tw(d, range_str, self._font_small)) // 2
        d.text((range_x, 52), range_str, font=self._font_small, fill=255)

        self._display(img)

    # ── Pantalla EDIT beat ────────────────────────────────────────────────────

    def show_edit_beat(self, beat_index, state):
        """
        ┌──────────────────────────┐
        │ Beat 1                   │
        │                          │
        │        ACENTO            │  ← estado grande
        │       ● / ○ / ·         │  ← símbolo
        │ 9/22=cambiar  6=ok       │
        └──────────────────────────┘
        """
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)

        title = f"Beat {beat_index + 1}"
        d.text((0, 0), title, font=self._font_big, fill=255)
        d.line([(0, 18), (self.W, 18)], fill=255)

        state_name = BEAT_NAMES[state]
        sn_x = (self.W - self._tw(d, state_name, self._font_big)) // 2
        d.text((sn_x, 20), state_name, font=self._font_big, fill=255)

        # Símbolo del estado
        cx, cy, r = self.W // 2, 44, 6
        if state == BEAT_ACCENT:
            d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=255)
        elif state == BEAT_NORMAL:
            d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=255)
        else:
            d.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=255)

        d.text((0, 54), "9/22=cambiar  6=ok", font=self._font_small, fill=255)

        self._display(img)

    # ── Mensaje genérico ──────────────────────────────────────────────────────

    def show_message(self, line1, line2=""):
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)
        d.text((0, 16), line1, font=self._font_big,   fill=255)
        if line2:
            d.text((0, 36), line2, font=self._font_med, fill=255)
        self._display(img)

    def clear(self):
        img = Image.new("1", (self.W, self.H))
        self._device.display(img)

    # ── Internos ──────────────────────────────────────────────────────────────

    def _display(self, img):
        with self._lock:
            try:
                self._device.display(img)
            except Exception as e:
                print(f"[OLED] display error: {e}")

    @staticmethod
    def _tw(draw, text, font):
        """Ancho en píxeles del texto."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return draw.textlength(text, font=font)
