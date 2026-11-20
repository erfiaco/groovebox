#!/bin/bash
# Deja una Raspberry Pi nueva igual que la Groovebox (Pi 3B+, noviembre 2026).
#
# Requisitos previos (con Raspberry Pi Imager):
#   - Raspberry Pi OS Bullseye 64 bits (el que llevaba la Pi 3B+)
#   - usuario "Javo" (todo el código usa /home/Javo/Proyects)
#   - wifi de casa y SSH configurados
# Después:
#   git clone https://github.com/erfiaco/groovebox.git ~/Proyects
#   bash ~/Proyects/sistema/install.sh
#
# Se puede volver a ejecutar: lo que ya está hecho, se salta.

set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
SIS="$REPO/sistema"
paso()  { echo; echo "=== $*"; }
aviso() { echo "  !! $*"; AVISOS+=("$*"); }
AVISOS=()

# ---------------------------------------------------------------- 0. comprobaciones
paso "0/8 Comprobaciones"
[ "$(id -un)" = "Javo" ] || { echo "Hay que ejecutarlo como el usuario Javo (el código usa /home/Javo)."; exit 1; }
[ "$REPO" = "/home/Javo/Proyects" ] || { echo "El repo tiene que estar en /home/Javo/Proyects (está en $REPO)."; exit 1; }
sudo -n true 2>/dev/null || { echo "Javo necesita sudo sin contraseña (el boot_menu lo usa para wifi/hotspot)."; exit 1; }
. /etc/os-release
[ "$VERSION_CODENAME" = "bullseye" ] || aviso "Sistema $VERSION_CODENAME: solo se ha probado en bullseye. En bookworm la red usa NetworkManager y switch_wifi/switch_hotspot no funcionarán."
BOOTCFG=/boot/config.txt
[ -f /boot/firmware/config.txt ] && BOOTCFG=/boot/firmware/config.txt
echo "  modelo: $(tr -d '\0' </proc/device-tree/model)"
echo "  sistema: $PRETTY_NAME   config: $BOOTCFG"

# ---------------------------------------------------------------- 1. paquetes
paso "1/8 Paquetes apt"
sudo apt-get update
# shellcheck disable=SC2046
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  $(grep -vE '^\s*(#|$)' "$SIS/paquetes_apt.txt") \
  build-essential autoconf automake libtool pkg-config swig unzip libasound2-dev python3-rpi.gpio
for g in audio bluetooth i2c gpio; do getent group $g >/dev/null && sudo usermod -aG $g Javo; done

# ---------------------------------------------------------------- 2. config.txt y módulos
paso "2/8 config.txt y /etc/modules"
[ -f "$BOOTCFG.orig" ] || sudo cp "$BOOTCFG" "$BOOTCFG.orig"
sudo sed -i 's/^dtparam=audio=on/#&/' "$BOOTCFG"          # audio interno apagado
if ! grep -q "# --- Groovebox ---" "$BOOTCFG"; then
  printf '\n[all]\n# --- Groovebox ---\ndtoverlay=audioinjector-wm8731-audio\ndtparam=audio=off\ndtparam=spi=off\ndtparam=i2c_arm=on\n' \
    | sudo tee -a "$BOOTCFG" >/dev/null
  echo "  añadido: AudioInjector, audio interno off, SPI off (libera GPIO 9/10/11), I2C on"
fi
for m in i2c-dev snd-aloop; do
  grep -qx "$m" /etc/modules || echo "$m" | sudo tee -a /etc/modules >/dev/null
done

# ---------------------------------------------------------------- 3. ALSA
paso "3/8 ALSA"
sudo cp "$SIS/etc/asound.conf" /etc/asound.conf
aviso "asound.conf manda el sonido a la tarjeta nº 1, como en la Pi vieja. Tras reiniciar, mira 'aplay -l': si el AudioInjector no es la nº 1, el sonido por cable puede ir al HDMI."

# ---------------------------------------------------------------- 4. lg (liblgpio)
paso "4/8 Librería lg (lgpio/rgpio) en /usr/local"
if [ -f /usr/local/lib/liblgpio.so ]; then
  echo "  ya instalada"
else
  tmp=$(mktemp -d)
  git clone -q --depth 1 https://github.com/joan2937/lg.git "$tmp/lg"
  make -C "$tmp/lg" -j4 >/dev/null
  sudo make -C "$tmp/lg" install >/dev/null
  sudo ldconfig
  rm -rf "$tmp"
fi

# ---------------------------------------------------------------- 5. bluez-alsa
paso "5/8 bluez-alsa (audio Bluetooth), la misma versión que la Pi vieja"
if command -v bluealsad >/dev/null; then
  echo "  ya instalado: $(bluealsad --version)"
else
  dpkg -s bluealsa >/dev/null 2>&1 && aviso "Está el paquete apt 'bluealsa' (versión vieja). Puede chocar con el compilado: valora 'sudo apt purge bluealsa'."
  [ -d ~/bluez-alsa ] || git clone -q https://github.com/arkq/bluez-alsa.git ~/bluez-alsa
  cd ~/bluez-alsa
  git checkout -q 4179c4e            # v4.3.1-95, la que estaba en la Pi 3B+
  autoreconf --install --force >/dev/null 2>&1
  mkdir -p build && cd build
  ../configure --prefix=/usr --enable-ofono >/dev/null
  make -j4 >/dev/null
  sudo make install >/dev/null
  cd "$REPO"
fi
sudo cp "$SIS/etc/systemd/system/bluealsa.service" /etc/systemd/system/

# ---------------------------------------------------------------- 6. red (wifi / hotspot)
paso "6/8 Red: hotspot BackingPlayer"
if command -v dhcpcd >/dev/null && [ -f /etc/dhcpcd.conf ]; then
  sudo cp "$SIS/etc/dhcpcd.conf.wifi" "$SIS/etc/dhcpcd.conf.hotspot" /etc/
  [ -f /etc/dnsmasq.conf.orig ] || sudo cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
  sudo cp "$SIS/etc/dnsmasq.conf" /etc/dnsmasq.conf
  if ! sudo test -f /etc/hostapd/hostapd.conf; then
    while :; do
      read -rsp "  Contraseña para el hotspot BackingPlayer (mínimo 8 caracteres): " PASS; echo
      [ ${#PASS} -ge 8 ] && break
    done
    PASS="$PASS" awk '/^wpa_passphrase=/{print "wpa_passphrase=" ENVIRON["PASS"]; next} 1' \
      "$SIS/etc/hostapd/hostapd.conf.example" | sudo tee /etc/hostapd/hostapd.conf >/dev/null
    sudo chmod 600 /etc/hostapd/hostapd.conf
    unset PASS
  fi
  sudo systemctl unmask hostapd
  sudo systemctl enable dnsmasq >/dev/null 2>&1
  read -rp "  ¿Arrancar en modo hotspot al encender, como la Pi vieja? [s/N] " R
  if [[ "$R" =~ ^[sS] ]]; then
    sudo cp /etc/dhcpcd.conf.hotspot /etc/dhcpcd.conf
    sudo systemctl enable hostapd >/dev/null 2>&1
    aviso "Al reiniciar arrancará como hotspot BackingPlayer (192.168.4.1): la wifi de casa dejará de verla hasta que pases a wifi desde el menú."
  else
    sudo systemctl disable hostapd >/dev/null 2>&1 || true
    echo "  arrancará en la wifi de casa; el hotspot se activa desde el boot_menu"
  fi
else
  aviso "No hay dhcpcd (¿bookworm?). Red sin configurar: los scripts switch_wifi/switch_hotspot hay que rehacerlos con nmcli."
fi

# ---------------------------------------------------------------- 7. Python
paso "7/8 Python: paquetes del boot_menu y entornos virtuales"
pip3 install --user -q -r "$SIS/requirements_boot_menu.txt"
crear_env() {  # carpeta  entorno  requirements
  local d="$REPO/$1" v="$REPO/$1/$2" r="$3"
  if [ -x "$v/bin/python" ]; then echo "  $1/$2: ya existe"; return; fi
  echo "  $1/$2: creando (puede tardar bastante en una Pi)"
  python3 -m venv "$v"
  "$v/bin/pip" install -q --upgrade pip wheel
  "$v/bin/pip" install -q -r "$r" || aviso "$1/$2: falló algún paquete de $r"
}
crear_env Looper            looper_env      "$REPO/Looper/requirements.txt"   # también lo usan sync_looper y backing_player
crear_env practice_player   practice_env    "$REPO/practice_player/requirements.txt"
crear_env metronome         metronome_env   "$REPO/metronome/requirements.txt"
crear_env bluetooth_recorder bt_recorder_env "$REPO/bluetooth_recorder/requirements.txt"
if [ ! -d "$REPO/raspi-looper" ]; then
  git clone -q https://github.com/erfiaco/raspi-looper.git "$REPO/raspi-looper"
  (cd "$REPO/raspi-looper" && git checkout -q wip/raspi-2026-11-20)
fi
crear_env raspi-looper      rlooper_env     "$SIS/requirements_raspi-looper.txt"

# ---------------------------------------------------------------- 8. arranque
paso "8/8 Arranque del boot_menu"
sudo cp "$SIS/etc/systemd/system/boot-menu.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bluealsa boot-menu >/dev/null 2>&1
# Igual que en la Pi vieja: además del servicio, el crontab lo lanza a los 10 s.
LINEA='@reboot sleep 10 && /usr/bin/python3 /home/Javo/Proyects/boot_menu/boot_menu.py'
( crontab -l 2>/dev/null | grep -vxF "$LINEA" || true; echo "$LINEA" ) | crontab -

# ---------------------------------------------------------------- resumen
paso "Hecho"
echo "Falta, a mano:"
echo "  1. Copiar el audio desde el PC (no está en git). Desde Proyectos/Groovebox, sin los WAV con nombre automático:"
echo "       X=\"--exclude=loop_*_*.wav --exclude=bt_recording_*.wav --exclude=[0-9][0-9][0-9][0-9].wav --exclude=/Django-MS_GuitSolo.wav --exclude=/fade-*.wav --exclude=/micro-fade-*.wav\""
echo "       rsync -a \$X backup_raspi/Proyects/backing_player/tracks/      Javo@<ip>:Proyects/backing_player/tracks/"
echo "       rsync -a \$X backup_raspi/Proyects/practice_player/audio_files/ Javo@<ip>:Proyects/practice_player/audio_files/"
echo "       rsync -a \$X backup_raspi/Proyects/Looper/loops/              Javo@<ip>:Proyects/Looper/loops/"
echo "  2. Reiniciar: sudo reboot"
echo "  3. Comprobar: aplay -l (AudioInjector), i2cdetect -y 1 (OLED en 0x3C)"
if [ ${#AVISOS[@]} -gt 0 ]; then
  echo; echo "Avisos:"; for a in "${AVISOS[@]}"; do echo "  - $a"; done
fi
