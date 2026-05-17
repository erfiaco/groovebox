import os
import glob


class FileBrowser:
    """
    Navigates a directory tree showing only items with both .wav and .json.
    Adapted from practice_player/file_browser.py.
    """

    def __init__(self, root_dir):
        self.root_dir    = os.path.abspath(root_dir)
        self.current_dir = self.root_dir
        self.items       = []
        self.current_idx = 0

        os.makedirs(self.root_dir, exist_ok=True)
        self._scan()

    # ── Navigation ───────────────────────────────────────────────────────

    def next_item(self):
        if self.items:
            self.current_idx = (self.current_idx + 1) % len(self.items)

    def prev_item(self):
        if self.items:
            self.current_idx = (self.current_idx - 1) % len(self.items)

    def select(self):
        """
        Returns:
          ('wav', wav_path)   - load this track
          ('entered', None)   - entered a subfolder
          ('up', None)        - went up a level
          (None, None)        - empty list
        """
        if not self.items:
            return (None, None)

        kind, name = self.items[self.current_idx]

        if kind == 'wav':
            return ('wav', os.path.join(self.current_dir, name))

        if kind == 'dir':
            self.current_dir = os.path.join(self.current_dir, name)
            self._scan()
            return ('entered', None)

        if kind == 'up':
            self.current_dir = os.path.dirname(self.current_dir)
            self._scan()
            return ('up', None)

        return (None, None)

    # ── Display helpers ───────────────────────────────────────────────────

    def get_item_label(self):
        if not self.items:
            return 'Empty'
        kind, name = self.items[self.current_idx]
        if kind == 'dir':
            return name + '/'
        return name

    def get_position(self):
        return (self.current_idx + 1, len(self.items)) if self.items else (0, 0)

    def get_dir_label(self):
        rel = os.path.relpath(self.current_dir, self.root_dir)
        return '/' if rel == '.' else '/' + rel + '/'

    # ── Internal ─────────────────────────────────────────────────────────

    def _scan(self):
        self.items       = []
        self.current_idx = 0

        if self.current_dir != self.root_dir:
            self.items.append(('up', '...'))

        dirs = sorted([
            d for d in os.listdir(self.current_dir)
            if os.path.isdir(os.path.join(self.current_dir, d))
            and not d.startswith('.')
        ])
        for d in dirs:
            self.items.append(('dir', d))

        wavs = glob.glob(os.path.join(self.current_dir, '*.wav'))
        wavs = sorted(wavs, key=os.path.getmtime, reverse=True)
        for w in wavs:
            base = os.path.splitext(w)[0]
            if os.path.exists(base + '.json'):
                self.items.append(('wav', os.path.basename(w)))

        print(f"[Browser] {len(self.items)} item(s) in {self.get_dir_label()}")
