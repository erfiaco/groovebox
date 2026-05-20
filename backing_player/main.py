print('LOADING...')

import sys
sys.setswitchinterval(0.001)  # 1ms GIL switch — reduces I2C interference on audio thread

import json
import os
import subprocess
import time
from datetime import datetime

from audio_engine    import BackingEngine
from buttons_manager import ButtonsManager
from file_browser    import FileBrowser
from metro_led       import MetroLed
from oled_display    import OledDisplay
from web_server      import WebServer

TRACKS_DIR      = os.path.join(os.path.dirname(__file__), 'tracks')
RECORDINGS_DIR  = os.path.join(TRACKS_DIR, 'recordings')
BOOT_MENU       = '/home/Javo/Proyects/boot_menu/boot_menu.py'

MODE_SELECTION = 'SELECTION'
MODE_PLAY      = 'PLAY'


class BackingPlayer:

    def __init__(self):
        self.mode           = MODE_SELECTION
        self._track_name    = ''
        self._pending_start = False

        self.engine  = BackingEngine()
        self.browser = FileBrowser(TRACKS_DIR)
        self.oled    = OledDisplay()
        self.metro   = MetroLed()
        self.web     = WebServer()
        self.buttons = ButtonsManager(
            on_btn1      = self._on_btn1,
            on_btn2      = self._on_btn2,
            on_btn3      = self._on_btn3,
            on_btn4_tap  = self._on_btn4_tap,
            on_btn4_hold = self._on_btn4_hold,
        )
        self.engine.on_state_change = self._on_engine_state
        self.metro.on_beat = self._on_beat

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self):
        self.engine.start_streams()
        self._update_display()
        print('READY')

        try:
            while True:
                time.sleep(0.25)
                if self.mode == MODE_SELECTION:
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
                # Start preview metro so mobile and LED show tempo immediately
                self.metro.bpm           = meta['tempo']
                self.metro.beats_per_bar = int(str(meta['compas']).split('/')[0])
                self.metro.start()
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
            meta = self.engine.meta
            if meta is None:
                return
            if self._pending_start:
                # Second press cancels the armed flag
                self._pending_start = False
                self._push_web_state()
                return
            if self.metro.running:
                # Arm: countdown will fire on next bar 1
                self._pending_start = True
                self._push_web_state()
            else:
                self._start_countdown_now()
        else:
            self._pending_start = False
            self.engine.stop()
            self.metro.stop()
            # Restart preview metro so mobile still shows tempo
            if self.engine.meta:
                meta = self.engine.meta
                self.metro.bpm           = meta['tempo']
                self.metro.beats_per_bar = int(str(meta['compas']).split('/')[0])
                self.metro.start()
            self._update_display()

    def _start_countdown_now(self):
        meta = self.engine.meta
        if meta is None:
            return
        cc_playback = meta.get('cc_playback', 2)
        beats       = int(str(meta['compas']).split('/')[0])
        tempo       = meta['tempo']
        bar_dur_sec = (60.0 / tempo) * beats
        self.metro.stop()
        self.engine.start_play(self.metro, cc_playback, bar_dur_sec)

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
        self._print_status()
        self._push_web_state()

    def _print_status(self):
        STATE_ICON = {
            'IDLE':      '■  IDLE',
            'COUNTDOWN': '◆  COUNTDOWN',
            'PLAYING':   '▶  PLAYING',
            'RECORDING': '●  RECORDING',
            'LOOPING':   '↺  LOOPING',
            'CODA':      '▶▶ CODA',
        }
        if self.mode == MODE_SELECTION:
            label      = self.browser.get_item_label()
            pos, total = self.browser.get_position()
            lines = [
                '┌─────────────────────────────────┐',
                '│       BACKING  PLAYER           │',
                '├─────────────────────────────────┤',
                f'│  {pos:>2}/{total:<2}  {label[:25]:<25}  │',
                '├─────────────────────────────────┤',
                '│  1:SEL  2:PREV  3:NEXT  4:EXIT  │',
                '└─────────────────────────────────┘',
            ]
        else:
            state = self.engine.state
            bar   = self.engine.current_bar
            total = self.engine.total_bars
            badge = STATE_ICON.get(state, state)
            flags = []
            if self.engine.last_rep:   flags.append('LAST-REP')
            if self.engine.silenced:   flags.append('SILENCED')
            if self.engine.mute_input: flags.append('MUTE-REC')
            flag_str = '  '.join(flags) if flags else '—'
            track    = self._track_name[:29]
            lines = [
                '┌─────────────────────────────────┐',
                f'│  {track:<31}  │',
                '├─────────────────────────────────┤',
                f'│  {badge:<14}  Bar {bar:>3} / {total:<3}       │',
                f'│  {flag_str:<31}  │',
                '├─────────────────────────────────┤',
                '│  1:PLAY  2:LR  3:SIL  4:SAVE   │',
                '└─────────────────────────────────┘',
            ]
        print('\033[H\033[2J' + '\n'.join(lines), flush=True)

    def _on_beat(self, beat_in_bar, beats_per_bar):
        # 4/4: flash on 1 and 3; other signatures: only beat 1
        if beats_per_bar == 4:
            should_flash = beat_in_bar in (1, 3)
        else:
            should_flash = beat_in_bar == 1

        if should_flash:
            self.web.push({
                'type':          'beat',
                'beat_in_bar':   beat_in_bar,
                'beats_per_bar': beats_per_bar,
                'is_accent':     beat_in_bar == 1,
            })

        if self._pending_start and beat_in_bar == 1:
            self._pending_start = False
            self._start_countdown_now()

    def _push_web_state(self):
        if self.mode == MODE_SELECTION:
            items = [{'kind': k, 'name': n} for k, n in self.browser.items]
            self.web.push({
                'type':      'state',
                'state':     'IDLE',
                'track':     '',
                'tempo':     0,
                'time_sig':  '',
                'bar':       0,
                'total_bars': 0,
                'selection': {
                    'items': items,
                    'idx':   self.browser.current_idx,
                    'dir':   self.browser.get_dir_label(),
                },
            })
        else:
            meta          = self.engine.meta or {}
            display_state = 'ARMED' if self._pending_start else self.engine.state
            self.web.push({
                'type':       'state',
                'state':      display_state,
                'track':      self._track_name,
                'tempo':      meta.get('tempo', 0),
                'time_sig':   str(meta.get('compas', '')),
                'bar':        self.engine.current_bar,
                'total_bars': self.engine.total_bars,
            })

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
        
        import subprocess
        subprocess.Popen(["/usr/bin/python3", "/home/Javo/Proyects/boot_menu/boot_menu.py"])

if __name__ == '__main__':
    player = BackingPlayer()
    player.run()
