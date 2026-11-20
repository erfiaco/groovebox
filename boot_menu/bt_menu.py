#!/usr/bin/env python3
"""
Menú Bluetooth para OLED:
- Escanea dispositivos cercanos y los lista (solo los que tienen nombre)
- Seleccionar un dispositivo: lo empareja (sin PIN), lo marca trusted y conecta
- Seleccionar un dispositivo ya conectado: lo desconecta
- Rescan para volver a escanear, Back para volver al boot menu

Marcadores en la lista:
  + conectado    * emparejado (trusted, reconecta solo)
"""

import time
import subprocess
import sys
import os
import re
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

# Configuración GPIO (mismos pines que boot_menu)
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

PIN_DOWN = 22   # Boton6
PIN_UP = 9      # Boton5
PIN_OK = 25     # Boton7
PIN_BACK = 5    # Boton4: volver al boot_menu

GPIO.setup(PIN_DOWN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_UP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_OK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_BACK, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# OLED
serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=128, height=64)

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
except:
    font = ImageFont.load_default()
    font_small = ImageFont.load_default()

SCAN_SECONDS = 12
BOOT_MENU = "/home/Javo/Proyects/boot_menu/boot_menu.py"

# ~/.asoundrc pisa el default de /etc/asound.conf (AudioInjector); lo usamos
# para que las apps que abren "default" salgan por el altavoz BT.
#
# OJO: no apuntamos default directo a bluealsa porque PortAudio (sounddevice,
# lo que usan las apps Python) no puede abrir ese PCM y el default desaparece
# de su lista. En su lugar: default -> tarjeta Loopback (snd-aloop, hw real
# que PortAudio sí ve) y un proceso alsaloop copia Loopback -> bluealsa.
ASOUNDRC = "/home/Javo/.asoundrc"
ASOUNDRC_MARK = "# generado por bt_menu"

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m|\x01|\x02')
MAC_RE = re.compile(r'([0-9A-F]{2}:){5}[0-9A-F]{2}')


def bt(args, timeout=10):
    """Ejecuta bluetoothctl con argumentos y devuelve stdout limpio de ANSI"""
    try:
        result = subprocess.run(
            ["bluetoothctl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return ANSI_RE.sub('', result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return ""


def _alsaloop_start():
    """(Re)arranca el puente Loopback -> bluealsa"""
    subprocess.run(["pkill", "-x", "alsaloop"], capture_output=True)
    subprocess.Popen(
        ["alsaloop", "-C", "hw:Loopback,1,0", "-P", "btspeaker", "-t", "100000"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=open('/tmp/alsaloop.log', 'w'),
        stderr=subprocess.STDOUT
    )
    print("[alsaloop] puente Loopback -> BT arrancado")


def _alsaloop_stop():
    subprocess.run(["pkill", "-x", "alsaloop"], capture_output=True)


def _alsaloop_corriendo():
    return subprocess.run(["pgrep", "-x", "alsaloop"],
                          capture_output=True).returncode == 0


def activar_salida_bt(mac):
    """Apunta el default de ALSA al Loopback y arranca el puente hacia el BT"""
    if os.path.exists(ASOUNDRC):
        with open(ASOUNDRC) as f:
            if ASOUNDRC_MARK not in f.read():
                print("[asoundrc] existe un ~/.asoundrc ajeno, no lo toco")
                return
    with open(ASOUNDRC, "w") as f:
        f.write(f"""{ASOUNDRC_MARK} — puente loopback -> Bluetooth ({mac})
pcm.!default {{
    type plug
    slave.pcm "hw:Loopback,0,0"
}}
ctl.!default {{
    type hw
    card 1
}}
pcm.btspeaker {{
    type plug
    slave.pcm {{
        type bluealsa
        device "{mac}"
        profile "a2dp"
    }}
}}
""")
    _alsaloop_start()
    print(f"[asoundrc] salida default -> BT {mac} (via Loopback)")


def desactivar_salida_bt():
    """Vuelve al default de /etc/asound.conf (AudioInjector)"""
    _alsaloop_stop()
    try:
        with open(ASOUNDRC) as f:
            es_nuestro = ASOUNDRC_MARK in f.read()
    except FileNotFoundError:
        return
    if es_nuestro:
        os.remove(ASOUNDRC)
        print("[asoundrc] salida default -> cable (AudioInjector)")


def salida_bt_activa():
    """True si el default de ALSA apunta ahora al altavoz BT"""
    try:
        with open(ASOUNDRC) as f:
            return ASOUNDRC_MARK in f.read()
    except FileNotFoundError:
        return False


def sincronizar_asoundrc():
    """Si ~/.asoundrc apunta a un BT que ya no está conectado, lo quita.
    Si sigue conectado pero el puente alsaloop no corre (p.ej. tras reiniciar),
    lo rearranca."""
    try:
        with open(ASOUNDRC) as f:
            contenido = f.read()
    except FileNotFoundError:
        _alsaloop_stop()
        return
    if ASOUNDRC_MARK not in contenido:
        return
    m = MAC_RE.search(contenido)
    if not m or "Connected: yes" not in bt(["info", m.group(0)]):
        desactivar_salida_bt()
    elif not _alsaloop_corriendo():
        _alsaloop_start()


def nombre_real(mac, name):
    """True si el dispositivo tiene nombre de verdad (no la MAC con guiones)"""
    return name and name != mac.replace(":", "-")


def mostrar(linea1, linea2="", linea3=""):
    """Pantalla simple de estado"""
    img = Image.new("1", (128, 64))
    d = ImageDraw.Draw(img)
    d.text((5, 5), linea1, font=font, fill=255)
    if linea2:
        d.text((5, 28), linea2, font=font_small, fill=255)
    if linea3:
        d.text((5, 44), linea3, font=font_small, fill=255)
    device.display(img)


def listar_dispositivos(vistos=None):
    """Lista de dicts {mac, name, paired, connected}.

    Sin `vistos` (arranque): solo emparejados — instantáneo, sin escanear.
    Con `vistos` (tras un escaneo): emparejados + los vistos en ese escaneo.
    """
    emparejados = set()
    for linea in bt(["paired-devices"]).splitlines():
        m = MAC_RE.search(linea)
        if m:
            emparejados.add(m.group(0))

    dispositivos = []
    for linea in bt(["devices"]).splitlines():
        m = MAC_RE.search(linea)
        if not m:
            continue
        mac = m.group(0)
        name = linea.split(mac, 1)[1].strip()
        if mac not in emparejados and (vistos is None or mac not in vistos):
            continue
        if not nombre_real(mac, name):
            continue
        info = bt(["info", mac])
        conectado = "Connected: yes" in info
        dispositivos.append({
            "mac": mac,
            "name": name,
            "paired": mac in emparejados,
            "connected": conectado,
        })

    # Conectados primero, luego emparejados, luego el resto
    dispositivos.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return dispositivos


def escanear():
    """Escanea SCAN_SECONDS y devuelve la lista completa de dispositivos"""
    bt(["power", "on"])

    proc = subprocess.Popen(
        ["bluetoothctl", "--timeout", str(SCAN_SECONDS), "scan", "on"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    inicio = time.time()
    while proc.poll() is None:
        restante = max(0, SCAN_SECONDS - int(time.time() - inicio))
        mostrar("Bluetooth", "Escaneando...", f"{restante}s")
        time.sleep(0.5)
        if time.time() - inicio > SCAN_SECONDS + 8:
            proc.kill()
            break

    salida = ANSI_RE.sub('', proc.stdout.read() if proc.stdout else "")

    # MACs vistas en ESTE escaneo (NEW o CHG = están cerca ahora)
    vistos = set()
    for linea in salida.splitlines():
        m = MAC_RE.search(linea)
        if m and "Device" in linea:
            vistos.add(m.group(0))

    return listar_dispositivos(vistos)


def conectar(dev):
    """Empareja (si hace falta), marca trusted y conecta. Devuelve True/False"""
    mac = dev["mac"]
    nombre = dev["name"][:14]

    bt(["power", "on"])
    bt(["pairable", "on"])

    if not dev["paired"]:
        mostrar("Emparejando", nombre, "...")
        salida = bt(["--agent", "NoInputNoOutput", "--timeout", "30", "pair", mac], timeout=40)
        if "Pairing successful" not in salida and "AlreadyExists" not in salida:
            print(f"[pair FALLO] {mac}:\n{salida}")
            return False

    bt(["trust", mac])

    mostrar("Conectando", nombre, "...")
    salida = bt(["--timeout", "20", "connect", mac], timeout=30)
    if "Connection successful" not in salida:
        print(f"[connect FALLO] {mac}:\n{salida}")
        return False
    activar_salida_bt(mac)
    return True


def desconectar(dev):
    mostrar("Desconectando", dev["name"][:14], "...")
    bt(["disconnect", dev["mac"]], timeout=15)
    desactivar_salida_bt()


def volver_a_boot_menu():
    """Limpia pantalla, relanza boot_menu y termina"""
    img = Image.new("1", (128, 64))
    device.display(img)
    try:
        GPIO.setup(PIN_DOWN, GPIO.IN)
        GPIO.setup(PIN_UP, GPIO.IN)
        GPIO.setup(PIN_OK, GPIO.IN)
        GPIO.setup(PIN_BACK, GPIO.IN)
    except:
        pass
    subprocess.Popen(
        [sys.executable, BOOT_MENU],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=open('/tmp/bootmenu.log', 'w'),
        stderr=subprocess.STDOUT
    )
    os._exit(0)


# ---------- Menú con scroll (mismo patrón que boot_menu) ----------

selected = 0
scroll_offset = 0
MAX_VISIBLE = 3

menu_items = []   # lista de tuplas (etiqueta, accion, dev)


def construir_menu(dispositivos):
    """Reconstruye items del menú a partir de los dispositivos"""
    global menu_items, selected, scroll_offset
    menu_items = []
    for dev in dispositivos:
        marca = "+" if dev["connected"] else ("*" if dev["paired"] else " ")
        etiqueta = f"{marca}{dev['name'][:15]}"
        menu_items.append((etiqueta, "device", dev))
    salida = "BT" if salida_bt_activa() else "Cable"
    menu_items.append((f"Salida: {salida}", "salida", None))
    menu_items.append(("Rescan", "rescan", None))
    menu_items.append(("Back", "back", None))
    selected = 0
    scroll_offset = 0


def draw_menu():
    global scroll_offset

    img = Image.new("1", (128, 64))
    draw = ImageDraw.Draw(img)

    draw.text((5, 2), "BLUETOOTH", font=font_small, fill=255)
    draw.line([(0, 15), (128, 15)], fill=255)

    if selected < scroll_offset:
        scroll_offset = selected
    elif selected >= scroll_offset + MAX_VISIBLE:
        scroll_offset = selected - MAX_VISIBLE + 1

    for i in range(MAX_VISIBLE):
        item_index = scroll_offset + i
        if item_index >= len(menu_items):
            break
        etiqueta = menu_items[item_index][0]
        y_pos = 20 + i * 15
        if item_index == selected:
            draw.rectangle([(2, y_pos - 2), (126, y_pos + 13)], outline=255, fill=0)
            draw.text((6, y_pos), f">{etiqueta}", font=font_small, fill=255)
        else:
            draw.text((6, y_pos), f" {etiqueta}", font=font_small, fill=255)

    if scroll_offset > 0:
        draw.polygon([(120, 18), (124, 22), (116, 22)], fill=255)
    if scroll_offset + MAX_VISIBLE < len(menu_items):
        draw.polygon([(120, 62), (124, 58), (116, 58)], fill=255)

    draw.text((2, 58), f"{selected + 1}/{len(menu_items)}", font=font_small, fill=255)
    device.display(img)


def select():
    global dispositivos
    etiqueta, accion, dev = menu_items[selected]

    if accion == "back":
        volver_a_boot_menu()

    elif accion == "salida":
        if salida_bt_activa():
            desactivar_salida_bt()
            mostrar("Salida", "Cable (jack)")
        else:
            conectados = [d for d in dispositivos if d["connected"]]
            if conectados:
                activar_salida_bt(conectados[0]["mac"])
                mostrar("Salida", conectados[0]["name"][:14], "(Bluetooth)")
            else:
                mostrar("Sin altavoz BT", "conecta uno", "primero")
        time.sleep(1.5)
        construir_menu(dispositivos)
        draw_menu()

    elif accion == "rescan":
        dispositivos = escanear()
        construir_menu(dispositivos)
        draw_menu()

    elif accion == "device":
        if dev["connected"]:
            desconectar(dev)
            dev["connected"] = False
            mostrar("Desconectado", dev["name"][:14])
            time.sleep(1.5)
        else:
            ok = conectar(dev)
            if ok:
                dev["paired"] = True
                dev["connected"] = True
                mostrar("Conectado!", dev["name"][:14])
            else:
                mostrar("FALLO", dev["name"][:14], "Prueba de nuevo")
            time.sleep(2)
        construir_menu(dispositivos)
        draw_menu()


# ---------- Main ----------

print("=== BT Menu iniciado ===")
mostrar("Bluetooth", "Cargando...")
sincronizar_asoundrc()
dispositivos = listar_dispositivos()
print(f"Dispositivos encontrados: {[(d['name'], d['mac'], 'paired' if d['paired'] else '', 'conn' if d['connected'] else '') for d in dispositivos]}")
construir_menu(dispositivos)
draw_menu()
print("Menú dibujado, esperando botones...")

try:
    last_down = True
    last_up = True
    last_ok = True
    last_back = True

    while True:
        current_down = GPIO.input(PIN_DOWN)
        current_up = GPIO.input(PIN_UP)
        current_ok = GPIO.input(PIN_OK)
        current_back = GPIO.input(PIN_BACK)

        if last_down and not current_down:
            time.sleep(0.05)
            if not GPIO.input(PIN_DOWN):
                selected = (selected + 1) % len(menu_items)
                draw_menu()

        if last_up and not current_up:
            time.sleep(0.05)
            if not GPIO.input(PIN_UP):
                selected = (selected - 1) % len(menu_items)
                draw_menu()

        if last_ok and not current_ok:
            time.sleep(0.05)
            if not GPIO.input(PIN_OK):
                select()

        if last_back and not current_back:
            time.sleep(0.05)
            if not GPIO.input(PIN_BACK):
                volver_a_boot_menu()

        last_down = current_down
        last_up = current_up
        last_ok = current_ok
        last_back = current_back
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nCtrl+C detectado")
    volver_a_boot_menu()

except Exception as e:
    print(f"\nError en bt_menu: {e}")
    volver_a_boot_menu()
