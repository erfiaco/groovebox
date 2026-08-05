#!/usr/bin/env python3
"""
Boot Menu:
- Modo Studio:    Metronome, Bluetooth Rec, Practice Player
- Modo Concierto: Looper, Sync_loop, 4trackloop, Backing_player
- Conecciones:    WiFi, Hotspot, Bluetooth, Shutdown

Botones directos (solo en boot_menu):
- Boton1 (GPIO6)  -> WiFi        [DESACTIVADO]
- Boton2 (GPIO26) -> Hotspot     [DESACTIVADO]
- Boton3 (GPIO13) -> Bluetooth   [DESACTIVADO]
- Boton4 (GPIO5)  -> atrás/apagar [DESACTIVADO]
"""

import time
import subprocess
import sys
import re
import threading
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO
import os

# Configuración GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Pines de navegación (botones de mano)
PIN_DOWN = 22      # Boton6
PIN_UP = 9         # Boton5
PIN_OK = 25        # Boton7

# Botones de pie
PIN_WIFI = 6       # Boton1
PIN_HOTSPOT = 26   # Boton2
PIN_BT = 13        # Boton3
PIN_BACK = 5       # Boton4: corto = atrás, mantener 2s = apagar

SHUTDOWN_HOLD_S = 2.0

# Botones 1-4 (pie) desactivados temporalmente
# ALL_PINS = [PIN_DOWN, PIN_UP, PIN_OK,
#             PIN_WIFI, PIN_HOTSPOT, PIN_BT, PIN_BACK]
ALL_PINS = [PIN_DOWN, PIN_UP, PIN_OK]

for pin in ALL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# OLED
serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=128, height=64)

# Fuente
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
except:
    font = ImageFont.load_default()
    font_small = ImageFont.load_default()

# Apps lanzables: nombre -> (comando, cwd, log)
APPS = {
    "Metronome": {
        "cmd": ["/home/Javo/Proyects/metronome/metronome_env/bin/python", "-u", "main.py"],
        "cwd": "/home/Javo/Proyects/metronome",
        "log": "metronome",
        "msg": "Metronome...",
    },
    "Bluetooth Rec": {
        "cmd": ["/home/Javo/Proyects/bluetooth_recorder/bt_recorder_env/bin/python", "-u", "main.py"],
        "cwd": "/home/Javo/Proyects/bluetooth_recorder",
        "log": "bluetooth_recorder",
        "msg": "BT Rec...",
    },
    "Practice Player": {
        "cmd": ["/home/Javo/Proyects/practice_player/practice_env/bin/python", "-u", "main.py"],
        "cwd": "/home/Javo/Proyects/practice_player",
        "log": "practice_player",
        "msg": "Practice...",
    },
    "Looper": {
        "cmd": ["/home/Javo/Proyects/Looper/looper_env/bin/python", "-u", "-m", "software.main"],
        "cwd": "/home/Javo/Proyects/Looper",
        "log": "looper",
        "msg": "Looper...",
    },
    "Sync_loop": {
        "cmd": ["/home/Javo/Proyects/Looper/looper_env/bin/python", "-u", "-m", "software.main"],
        "cwd": "/home/Javo/Proyects/sync_looper",
        "log": "sync_looper",
        "msg": "Sync_Loop...",
    },
    "4trackloop": {
        "cmd": ["/home/Javo/Proyects/raspi-looper/rlooper_env/bin/python", "-u", "main.py"],
        "cwd": "/home/Javo/Proyects/raspi-looper",
        "log": "raspi-looper",
        "msg": "4trackloop...",
    },
    "Backing_player": {
        "cmd": ["/home/Javo/Proyects/Looper/looper_env/bin/python", "-u", "main.py"],
        "cwd": "/home/Javo/Proyects/backing_player",
        "log": "backing_player",
        "msg": "Backing...",
    },
}

# Estructura de menús
MENUS = {
    "main": {
        "title": "BOOT MENU",
        "items": ["Modo Studio", "Modo Concierto", "Conecciones", "Test Audio"],
    },
    "studio": {
        "title": "MODO STUDIO",
        "items": ["Metronome", "Bluetooth Rec", "Practice Player", "< Volver"],
    },
    "concierto": {
        "title": "MODO CONCIERTO",
        "items": ["Looper", "Sync_loop", "4trackloop", "Backing_player", "< Volver"],
    },
    "conecciones": {
        "title": "CONECCIONES",
        "items": ["WiFi", "Hotspot", "Bluetooth", "Shutdown", "< Volver"],
    },
}

current_menu = "main"
selected = 0
scroll_offset = 0
MAX_VISIBLE = 3

# ---------- Estado de red y salida de audio ----------

ASOUNDRC = "/home/Javo/.asoundrc"
ASOUNDRC_MARK = "# generado por bt_menu"
MAC_RE = re.compile(r'([0-9A-F]{2}:){5}[0-9A-F]{2}')

# red: "WiFi"/"Hspt" · salida: "Jack"/"BT+" (conectado)/"BT!" (sin conexión)
status = {"red": "", "salida": ""}
draw_lock = threading.Lock()


def leer_estado():
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", "hostapd"],
                           timeout=5)
        red = "Hspt" if r.returncode == 0 else "WiFi"
    except Exception:
        red = "?"

    salida = "Jack"
    try:
        with open(ASOUNDRC) as f:
            contenido = f.read()
        if ASOUNDRC_MARK in contenido:
            salida = "BT!"
            m = MAC_RE.search(contenido)
            if m:
                info = subprocess.run(["bluetoothctl", "info", m.group(0)],
                                      capture_output=True, text=True,
                                      timeout=5).stdout
                if "Connected: yes" in info:
                    salida = "BT+"
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return red, salida


def status_worker():
    while True:
        time.sleep(5)
        try:
            nuevo = leer_estado()
            if (status["red"], status["salida"]) != nuevo:
                status["red"], status["salida"] = nuevo
                draw_menu()
        except Exception as e:
            print(f"[status] error: {e}")


def draw_menu():
    """Dibuja el menú actual con scroll si hay más de 3 opciones"""
    global scroll_offset

    menu = MENUS[current_menu]
    items = menu["items"]

    img = Image.new("1", (128, 64))
    draw = ImageDraw.Draw(img)

    draw.text((5, 2), menu["title"], font=font_small, fill=255)

    estado = f"{status['red']} {status['salida']}".strip()
    if estado:
        w = draw.textlength(estado, font=font_small)
        draw.text((126 - w, 2), estado, font=font_small, fill=255)

    draw.line([(0, 15), (128, 15)], fill=255)

    if selected < scroll_offset:
        scroll_offset = selected
    elif selected >= scroll_offset + MAX_VISIBLE:
        scroll_offset = selected - MAX_VISIBLE + 1

    for i in range(MAX_VISIBLE):
        item_index = scroll_offset + i
        if item_index >= len(items):
            break

        item = items[item_index]
        y_pos = 20 + i * 15

        if item_index == selected:
            draw.rectangle([(2, y_pos - 2), (126, y_pos + 13)], outline=255, fill=0)
            draw.text((10, y_pos), f"> {item}", font=font_small, fill=255)
        else:
            draw.text((10, y_pos), f"  {item}", font=font_small, fill=255)

    if scroll_offset > 0:
        draw.polygon([(120, 18), (124, 22), (116, 22)], fill=255)
    if scroll_offset + MAX_VISIBLE < len(items):
        draw.polygon([(120, 62), (124, 58), (116, 58)], fill=255)

    # Botones 1-4 desactivados temporalmente: no mostrar leyenda
    # if current_menu == "main":
    #     draw.text((2, 54), "1:WiFi 2:Hspot 3:BT 4:Off", font=font_small, fill=255)
    # else:
    #     draw.text((2, 58), f"{selected + 1}/{len(items)}", font=font_small, fill=255)
    if current_menu != "main":
        draw.text((2, 58), f"{selected + 1}/{len(items)}", font=font_small, fill=255)

    display(img)


def display(img):
    # Todas las escrituras al OLED pasan por aquí: el hilo de estado y el
    # principal no pueden usar el I2C a la vez (Errno 5 si colisionan)
    with draw_lock:
        device.display(img)


def show_message(line1, line2):
    img = Image.new("1", (128, 64))
    draw = ImageDraw.Draw(img)
    draw.text((15, 25), line1, font=font, fill=255)
    draw.text((15, 40), line2, font=font_small, fill=255)
    display(img)


def clear_screen():
    display(Image.new("1", (128, 64)))


def navigate(delta):
    global selected
    selected = (selected + delta) % len(MENUS[current_menu]["items"])
    draw_menu()


def enter_menu(name):
    global current_menu, selected, scroll_offset
    current_menu = name
    selected = 0
    scroll_offset = 0
    draw_menu()


def cleanup_and_exit():
    """Limpia recursos y sale limpiamente"""
    print("\nLimpiando recursos...")
    try:
        show_message("Goodbye!", "")
        time.sleep(1)
        clear_screen()
    except Exception as e:
        print(f"[oled] no responde al salir: {e}")

    # NO hacer GPIO.cleanup() - corrompe I2C y AudioInjector
    try:
        for pin in ALL_PINS:
            GPIO.setup(pin, GPIO.IN)
    except:
        pass

    print("Boot menu cerrado limpiamente")
    sys.exit(0)


def launch_app(name):
    """Lanza una app y termina el boot_menu"""
    app = APPS[name]
    print(f"Arrancando {name}...")
    show_message("Starting", app["msg"])
    time.sleep(0.5)
    clear_screen()
    GPIO.cleanup()

    subprocess.Popen(
        app["cmd"],
        cwd=app["cwd"],
        stdin=subprocess.DEVNULL,
        stdout=open(f"/tmp/{app['log']}.log", 'w', buffering=1),
        stderr=open(f"/tmp/{app['log']}_errors.log", 'w', buffering=1),
        start_new_session=True
    )
    os._exit(0)


def action_wifi():
    print("Cambiando a WiFi...")
    show_message("WiFi...", "Switching")
    subprocess.Popen(
        ["sudo", "bash", "/home/Javo/Proyects/boot_menu/switch_wifi.sh"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=open('/tmp/switch_wifi.log', 'w'),
        stderr=subprocess.STDOUT
    )
    os._exit(0)


def action_hotspot():
    print("Cambiando a Hotspot...")
    show_message("Hotspot...", "Switching")
    subprocess.Popen(
        ["sudo", "bash", "/home/Javo/Proyects/boot_menu/switch_hotspot.sh"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=open('/tmp/switch_hotspot.log', 'w'),
        stderr=subprocess.STDOUT
    )
    os._exit(0)


def action_bluetooth():
    print("Arrancando BT Menu...")
    show_message("Starting", "Bluetooth...")
    time.sleep(0.5)
    clear_screen()
    GPIO.cleanup()
    subprocess.Popen(
        [sys.executable, "/home/Javo/Proyects/boot_menu/bt_menu.py"],
        stdin=subprocess.DEVNULL,
        stdout=open('/tmp/bt_menu.log', 'w', buffering=1),
        stderr=open('/tmp/bt_menu_errors.log', 'w', buffering=1),
        start_new_session=True
    )
    os._exit(0)


def action_shutdown():
    print("Apagando sistema...")
    show_message("Shutting", "down...")
    time.sleep(1)
    clear_screen()
    GPIO.cleanup()
    subprocess.run(["sudo", "shutdown", "-h", "now"])


def test_audio():
    """Reproduce 5s de prueba por la salida default (BT o cable segun asoundrc)"""
    print(f"Test audio -> salida {status['salida']}")
    show_message("Test Audio", f"Sonando -> {status['salida']}")
    try:
        r = subprocess.run(
            ["aplay", "-q", "/home/Javo/Proyects/boot_menu/test_audio.wav"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            show_message("Test Audio", "OK")
        else:
            print(f"aplay fallo:\n{r.stderr}")
            with open('/tmp/test_audio.log', 'w') as f:
                f.write(r.stderr)
            show_message("Test FALLO", "ver /tmp/test_audio.log")
    except subprocess.TimeoutExpired:
        show_message("Test FALLO", "timeout (colgado)")
    time.sleep(1.5)
    draw_menu()


def select():
    """Ejecuta la acción del item seleccionado"""
    selection = MENUS[current_menu]["items"][selected]

    if selection == "Modo Studio":
        enter_menu("studio")
    elif selection == "Modo Concierto":
        enter_menu("concierto")
    elif selection == "Conecciones":
        enter_menu("conecciones")
    elif selection == "Test Audio":
        test_audio()
    elif selection == "WiFi":
        action_wifi()
    elif selection == "Hotspot":
        action_hotspot()
    elif selection == "Bluetooth":
        action_bluetooth()
    elif selection == "Shutdown":
        action_shutdown()
    elif selection == "< Volver":
        enter_menu("main")
    elif selection in APPS:
        launch_app(selection)


# Dibuja menú inicial
print("=== Boot Menu Iniciado ===")
status["red"], status["salida"] = leer_estado()
threading.Thread(target=status_worker, daemon=True).start()
draw_menu()
# print("Nav: DOWN(22) UP(9) OK(25) | WiFi(6) Hotspot(26) BT(13) Back/Off(5)")
print("Nav: DOWN(22) UP(9) OK(25) | Botones 1-4 desactivados")

try:
    last = {pin: True for pin in ALL_PINS}
    shutdown_press_t = None

    while True:
        current = {pin: GPIO.input(pin) for pin in ALL_PINS}

        # Botones con debounce por flanco descendente
        def pressed(pin):
            if last[pin] and not current[pin]:
                time.sleep(0.05)
                return not GPIO.input(pin)
            return False

        if pressed(PIN_DOWN):
            navigate(+1)
        if pressed(PIN_UP):
            navigate(-1)
        if pressed(PIN_OK):
            select()
        # Botones 1-4 (pie) desactivados temporalmente
        # if pressed(PIN_WIFI):
        #     action_wifi()
        # if pressed(PIN_HOTSPOT):
        #     action_hotspot()
        # if pressed(PIN_BT):
        #     action_bluetooth()

        # Boton4: corto = atrás (submenú -> principal), mantener 2s = apagar
        # if not current[PIN_BACK]:
        #     if shutdown_press_t is None:
        #         shutdown_press_t = time.monotonic()
        #     elif time.monotonic() - shutdown_press_t >= SHUTDOWN_HOLD_S:
        #         action_shutdown()
        #         shutdown_press_t = None
        # else:
        #     if shutdown_press_t is not None and current_menu != "main":
        #         enter_menu("main")
        #     shutdown_press_t = None

        for pin in ALL_PINS:
            last[pin] = current[pin]
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nCtrl+C detectado")
    cleanup_and_exit()

except Exception as e:
    print(f"\nError en boot_menu: {e}")
    cleanup_and_exit()

finally:
    # NO hacer GPIO.cleanup() - puede corromper I2C
    pass
