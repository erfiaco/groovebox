#!/usr/bin/env python3
"""
OledDisplay para el metrónomo.

Dos layouts:
  show_config(bpm, beats, mode_name)  → pantalla parado
  show_playing(bpm, beats, mode_name) → pantalla en reproducción

Pantalla CONFIG (128×64):
    ┌────────────────────────┐
    │ METRO       NORMAL     │  ← título + modo
    │ ─────────────────────  │
    │ BPM:    60             │
    │ Comp:   4/4            │
    │ 26↓   6=PLAY   13↑    │  ← ayuda
    └────────────────────────┘

Pantalla PLAYING (128×64):
    ┌────────────────────────┐
    │                        │
    │         120            │  ← BPM grande (36px)
    │         4/4        N   │  ← compás + modo (esquina)
    │                        │
    └────────────────────────┘
"""

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
import threading


class OledDisplay:

    def __init__(self, port: int = 1, address: int = 0x3C,
                 width: int = 128, height: int = 64):

        self._lock = threading.Lock()

        # Conectar OLED
        serial = i2c(port=port, address=address)
        self._device = ssd1306(serial, width=width, height=height)
        self.W, self.H = self._device.size

        # Fuentes
        try:
            path_bold  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            path_plain = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            self._font_huge  = ImageFont.truetype(path_bold,  36)  # BPM en playing
            self._font_big   = ImageFont.truetype(path_bold,  16)  # títulos config
            self._font_med   = ImageFont.truetype(path_plain, 14)  # compás playing
            self._font_small = ImageFont.truetype(path_plain, 10)  # ayuda / modo
        except Exception:
            fallback = ImageFont.load_default()
            self._font_huge  = fallback
            self._font_big   = fallback
            self._font_med   = fallback
            self._font_small = fallback

    # ── API pública ───────────────────────────────────────────────────────────

    def show_config(self, bpm: int, beats: int, mode_name: str = "NORMAL"):
        """
        Pantalla de configuración (metrónomo parado).
        """
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)

        # Fila 0: "METRO" + modo (alineado a la derecha)
        d.text((0, 0),  "METRO",    font=self._font_big,   fill=255)
        mode_x = self.W - self._text_width(d, mode_name, self._font_small) - 2
        d.text((mode_x, 4), mode_name, font=self._font_small, fill=255)

        # Separador
        d.line([(0, 18), (self.W, 18)], fill=255)

        # Fila 1: BPM
        d.text((0, 21), "BPM:",  font=self._font_med, fill=255)
        d.text((50, 21), str(bpm), font=self._font_med, fill=255)

        # Fila 2: Compás
        d.text((0, 37), "Comp:", font=self._font_med, fill=255)
        d.text((50, 37), f"{beats}/4", font=self._font_med, fill=255)

        # Fila 3: Ayuda
        d.text((0, 53), "26\u2193  6=PLAY  13\u2191", font=self._font_small, fill=255)

        self._display(img)

    def show_playing(self, bpm: int, beats: int, mode_name: str = "NORMAL"):
        """
        Pantalla de reproducción: BPM grande, compás mediano, modo en esquina.
        """
        img = Image.new("1", (self.W, self.H))
        d   = ImageDraw.Draw(img)

        # BPM centrado grande
        bpm_str = str(bpm)
        bpm_w   = self._text_width(d, bpm_str, self._font_huge)
        bpm_x   = (self.W - bpm_w) // 2
        d.text((bpm_x, 4), bpm_str, font=self._font_huge, fill=255)

        # Compás, centrado, debajo del BPM
        sig_str = f"{beats}/4"
        sig_w   = self._text_width(d, sig_str, self._font_med)
        sig_x   = (self.W - sig_w) // 2
        d.text((sig_x, 46), sig_str, font=self._font_med, fill=255)

        # Modo: primera letra, esquina inferior derecha
        mode_abbr = mode_name[0] if mode_name else "N"
        abbr_w    = self._text_width(d, mode_abbr, self._font_small)
        d.text((self.W - abbr_w - 2, 54), mode_abbr, font=self._font_small, fill=255)

        self._display(img)

    def show_message(self, line1: str, line2: str = ""):
        """Mensaje genérico de dos líneas, centrado."""
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
    def _text_width(draw: ImageDraw.Draw, text: str, font) -> int:
        """Devuelve el ancho en píxeles del texto con la fuente dada."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            # Pillow antiguo sin textbbox
            return draw.textlength(text, font=font)
