import queue
import threading

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont

_SENTINEL = object()


class OledDisplay:

    def __init__(self, port=1, address=0x3C):
        serial     = i2c(port=port, address=address)
        self.device = ssd1306(serial, width=128, height=64)
        self.W, self.H = self.device.size

        self._error_count = 0
        self._disabled    = False

        try:
            bold  = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
            reg   = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
            self.font_big   = ImageFont.truetype(bold, 16)
            self.font_med   = ImageFont.truetype(reg,  12)
            self.font_small = ImageFont.truetype(reg,  10)
        except Exception:
            self.font_big   = ImageFont.load_default()
            self.font_med   = ImageFont.load_default()
            self.font_small = ImageFont.load_default()

        # Single persistent I2C worker — callers never block on display()
        self._queue  = queue.Queue(maxsize=2)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    # ── I2C worker loop (runs in its own thread forever) ─────────────────

    def _worker_loop(self):
        while True:
            img = self._queue.get()
            if img is _SENTINEL:
                return
            try:
                self.device.display(img)
                self._error_count = 0
            except Exception as e:
                self._error_count += 1
                print(f"[OLED] error #{self._error_count}: {e}")
                if self._error_count >= 5:
                    self._disabled = True
                    print('[OLED] disabled - too many I2C errors')

    # ── Non-blocking enqueue ──────────────────────────────────────────────

    def _draw(self, img):
        return  # OLED disabled for testing
        if self._disabled:
            return
        # Drop stale pending frame so only the latest reaches the display
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(img)
        except queue.Full:
            pass

    # ── Browser screen ───────────────────────────────────────────────────

    def show_browser(self, label, pos, total, dir_label='/'):
        img = Image.new('1', (self.W, self.H))
        d   = ImageDraw.Draw(img)

        header = 'BROWSER' + (f' {dir_label}' if dir_label != '/' else '')
        d.text((0, 0),  header[:21], font=self.font_med, fill=255)
        d.line([(0, 13), (127, 13)], fill=255)
        d.text((0, 16), f'> {label[:20]}', font=self.font_med, fill=255)
        d.text((0, 32), f'  {pos}/{total}', font=self.font_small, fill=255)
        d.text((0, 50), '1:SEL 2:PREV 3:NEXT 4:EXIT', font=self.font_small, fill=255)

        self._draw(img)

    # ── Play screen ───────────────────────────────────────────────────────

    def show_play(self, track_name, state, bar, total_bars, last_rep, silenced, mute_input):
        img = Image.new('1', (self.W, self.H))
        d   = ImageDraw.Draw(img)

        # Row 0: track name (truncated)
        d.text((0, 0), track_name[:21], font=self.font_small, fill=255)

        # Row 1: state badge
        state_labels = {
            'IDLE':      'IDLE',
            'PLAYING':   'PLAY',
            'RECORDING': 'REC *',
            'LOOPING':   'LOOP',
            'CODA':      'CODA',
        }
        badge = state_labels.get(state, state)
        d.text((0, 12), badge, font=self.font_big, fill=255)

        # Row 1: bar counter (right side)
        bar_txt = f'{bar}/{total_bars}'
        d.text((80, 14), bar_txt, font=self.font_med, fill=255)

        # Row 2: flags
        flags = []
        if last_rep:
            flags.append('LR')
        if silenced:
            flags.append('SIL')
        if mute_input:
            flags.append('MUTREC')
        d.text((0, 33), ' '.join(flags), font=self.font_small, fill=255)

        # Row 3: button hints
        hints = '1:PLAY 2:LR 3:SIL 4:SAVE'
        d.text((0, 50), hints, font=self.font_small, fill=255)

        self._draw(img)

    # ── Cleanup ───────────────────────────────────────────────────────────

    def close(self):
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass
        try:
            self.device.cleanup()
        except Exception:
            pass

    # ── Generic message ───────────────────────────────────────────────────

    def show_message(self, msg):
        img = Image.new('1', (self.W, self.H))
        d   = ImageDraw.Draw(img)
        words = msg.split()
        lines, cur = [], ''
        for w in words:
            if len(cur) + len(w) + 1 <= 21:
                cur += w + ' '
            else:
                if cur:
                    lines.append(cur.strip())
                cur = w + ' '
        if cur:
            lines.append(cur.strip())
        y = 20
        for line in lines[:3]:
            d.text((0, y), line, font=self.font_med, fill=255)
            y += 14
        self._draw(img)
