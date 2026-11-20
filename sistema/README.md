# sistema/

Configuración de la Pi 3B+ (Raspberry Pi OS Bullseye) a 2026-11-20. Los ficheros están en las rutas donde van en la raspi.

| Fichero | Para qué |
|---|---|
| `boot/config.txt` | Overlay del AudioInjector, audio interno apagado, SPI apagado (libera GPIO 9/10/11 para botones) |
| `etc/modules` | `i2c-dev` (OLED) y `snd-aloop` (puente para el Bluetooth) |
| `etc/asound.conf` | Salida ALSA por defecto. **Tiene un fallo conocido**: usa `hw:1,0` (ahora el HDMI) |
| `etc/dhcpcd.conf.wifi` / `.hotspot` | Los scripts `boot_menu/switch_*.sh` copian uno de los dos sobre `/etc/dhcpcd.conf` |
| `etc/hostapd/hostapd.conf.example` | Hotspot `BackingPlayer`. Hay que copiarlo como `hostapd.conf` y poner la contraseña |
| `etc/dnsmasq.conf` | DHCP del hotspot (192.168.4.2–20) |
| `etc/systemd/system/*.service` | `boot-menu` (lanza el menú) y `bluealsa` (audio Bluetooth A2DP) |
| `paquetes_apt.txt` | Paquetes apt necesarios |
| `requirements_boot_menu.txt` | Paquetes que el boot_menu usa del `pip --user` |

**No están aquí, a propósito:** `wpa_supplicant.conf` (contraseñas wifi), el crontab (lanzaba el boot_menu por duplicado) y los servicios viejos (looper, test, grabador_zoom…).
