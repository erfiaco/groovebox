from gpiozero import Button, Device
from gpiozero.pins.lgpio import LGPIOFactory

Device.pin_factory = LGPIOFactory()

BTN1_PIN  = 6
BTN2_PIN  = 26
BTN3_PIN  = 13
BTN4_PIN  = 5
HOLD_TIME = 2.0


class ButtonsManager:
    """
    4 buttons. btn4 distinguishes tap vs hold (2s):
      - tap  fires on_btn4_tap  only if released before hold_time
      - hold fires on_btn4_hold when held >= hold_time
    """

    def __init__(self, on_btn1, on_btn2, on_btn3, on_btn4_tap, on_btn4_hold):
        self._on_btn4_tap  = on_btn4_tap
        self._on_btn4_hold = on_btn4_hold
        self._btn4_held    = False

        self.btn1 = Button(BTN1_PIN, pull_up=True, bounce_time=0.03)
        self.btn2 = Button(BTN2_PIN, pull_up=True, bounce_time=0.03)
        self.btn3 = Button(BTN3_PIN, pull_up=True, bounce_time=0.03)
        self.btn4 = Button(BTN4_PIN, pull_up=True, bounce_time=0.03,
                           hold_time=HOLD_TIME)

        self.btn1.when_pressed   = self._safe(on_btn1)
        self.btn2.when_pressed   = self._safe(on_btn2)
        self.btn3.when_pressed   = self._safe(on_btn3)
        self.btn4.when_held      = self._on_hold
        self.btn4.when_released  = self._on_release

    def _safe(self, fn):
        def wrapper():
            if fn:
                try:
                    fn()
                except Exception as e:
                    print(f"[Buttons] error: {e}")
        return wrapper

    def _on_hold(self):
        self._btn4_held = True
        if self._on_btn4_hold:
            try:
                self._on_btn4_hold()
            except Exception as e:
                print(f"[Buttons] btn4 hold error: {e}")

    def _on_release(self):
        if not self._btn4_held:
            if self._on_btn4_tap:
                try:
                    self._on_btn4_tap()
                except Exception as e:
                    print(f"[Buttons] btn4 tap error: {e}")
        self._btn4_held = False

    def close(self):
        for btn in (self.btn1, self.btn2, self.btn3, self.btn4):
            try:
                btn.close()
            except Exception:
                pass
