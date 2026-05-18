print('LOADING...')

import json
import os
import subprocess
import sys
import time
from datetime import datetime

from audio_engine  import BackingEngine
from buttons_manager import ButtonsManager
from file_browser  import FileBrowser
from metro_led     import MetroLed
from oled_display  import OledDisplay

TRACKS_DIR      = os.path.join(os.path.dirname(__file__), 'tracks')
RECORDINGS_DIR  = os.path.join(TRACKS_DIR, 'recordings')
BOOT_MENU       = '/home/Javo/Proyects/boot_menu/boot_menu.py'

MODE_SELECTION = 'SELECTION'
MODE_PLAY      = 'PLAY'


class BackingPlayer:

    def __init__(self):
        self.mode        = MODE_SELECTION
        self._track_name = ''

        self.engine  = BackingEngine()
        self.browser = FileBrowser(TRACKS_DIR)
        self.oled    = OledDisplay()
        self.metro   = MetroLed()
        self.buttons = ButtonsManager(
            on_btn1      = self._on_btn1,
            on_btn2      = self._on_btn2,
            on_btn3      = self._on_btn3,
            on_btn4_tap  = self._on_btn4_tap,
            on_btn4_hold = self._on_btn4_hold,
        )
        self.engine.on_state_change = self._on_engine_state

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self):
        self.engine.start_streams()
        self._update_display()
        print('READY')

        try:
            while True:
                time.sleep(0.25)
                self._update_display()
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()

    # ── Button handlers ───────────────────────────────────────────────────

    def _on_btn1(self):
        if self.mode == MODE_SELECTION:
            self._selection_select()
        else:
            self._play_toggle()

    def _on_btn2(self):
        if self.mode == MODE_SELECTION:
            self.browser.prev_item()
            self._update_display()
        else:
            lr = self.engine.toggle_last_rep()
            print(f"[Main] last_rep={'ON' if lr else 'OFF'}")
            self._update_display()

    def _on_btn3(self):
        if self.mode == MODE_SELECTION:
            self.browser.next_item()
            self._update_display()
        else:
            self.engine.toggle_silence()
            self._update_display()

    def _on_btn4_tap(self):
        if self.mode == MODE_SELECTION:
            self._exit_to_boot()
        elif self.mode == MODE_PLAY:
            self._save_recording()

    def _on_btn4_hold(self):
        if self.mode == MODE_PLAY:
            self._go_to_selection()

    # ── Selection mode actions ────────────────────────────────────────────

    def _selection_select(self):
        kind, path = self.browser.select()
        if kind == 'wav':
            json_path = os.path.splitext(path)[0] + '.json'
            try:
                with open(json_path) as f:
                    meta = json.load(f)
                self.engine.load_track(path, meta)
                self._track_name = os.path.splitext(os.path.basename(path))[0]
                self.mode = MODE_PLAY
                self.oled.show_message(f'Loaded: {self._track_name}')
                time.sleep(0.8)
            except Exception as e:
                print(f"[Main] load error: {e}")
                self.oled.show_message(f'Error: {e}')
                time.sleep(1.5)
        self._update_display()

    # ── Play mode actions ─────────────────────────────────────────────────

    def _play_toggle(self):
        state = self.engine.state
        if state == 'IDLE':
            meta         = self.engine.meta
            if meta is None:
                return
            cc_playback  = meta.get('cc_playback', 2)
            beats        = int(str(meta['compas']).split('/')[0])
            tempo        = meta['tempo']
            bar_dur_sec  = (60.0 / tempo) * beats
            self.engine.start_play(self.metro, cc_playback, bar_dur_sec)
        else:
            self.engine.stop()
            self.metro.stop()
            self._update_display()

    def _save_recording(self):
        if not self.engine.recorded:
            self.oled.show_message('Nothing recorded yet')
            time.sleep(1.0)
            self._update_display()
            return
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(RECORDINGS_DIR, f'{self._track_name}_{ts}.wav')
        ok   = self.engine.save_recording(path)
        self.oled.show_message('Saved!' if ok else 'Save error')
        time.sleep(1.0)
        self._update_display()

    def _go_to_selection(self):
        self.engine.stop()
        self.metro.stop()
        self.mode = MODE_SELECTION
        self._update_display()

    def _exit_to_boot(self):
        self.oled.show_message('Exiting...')
        time.sleep(0.5)
        self._cleanup()
        if os.path.exists(BOOT_MENU):
            subprocess.Popen([sys.executable, BOOT_MENU])
        os._exit(0)

    # ── Display ───────────────────────────────────────────────────────────

    def _update_display(self):
        if self.mode == MODE_SELECTION:
            label     = self.browser.get_item_label()
            pos, total = self.browser.get_position()
            dir_label = self.browser.get_dir_label()
            self.oled.show_browser(label, pos, total, dir_label)
        else:
            self.oled.show_play(
                track_name = self._track_name,
                state      = self.engine.state,
                bar        = self.engine.current_bar,
                total_bars = self.engine.total_bars,
                last_rep   = self.engine.last_rep,
                silenced   = self.engine.silenced,
                mute_input = self.engine.mute_input,
            )

    def _on_engine_state(self, state):
        self._update_display()

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _cleanup(self):
        try:
            self.engine.close()
        except Exception:
            pass
        try:
            self.metro.close()
        except Exception:
            pass
        try:
            self.buttons.close()
        except Exception:
            pass
        try:
            self.oled.close()
        except Exception:
            pass


if __name__ == '__main__':
    player = BackingPlayer()
    player.run()
