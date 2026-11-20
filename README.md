# Groovebox

Software de la Groovebox: Raspberry Pi + AudioInjector Zero, OLED I2C y 9 botones.
Un solo repo con todos los programas. Antes cada uno tenía su propio repo; esos repos quedan archivados con su historial completo.

## Programas

| Carpeta | Qué es | Repo anterior |
|---|---|---|
| `boot_menu/` | Menú de arranque: lanza los programas, wifi/hotspot, Bluetooth | erfiaco/boot-menu |
| `Looper/` | Looper principal (motor dúplex) | erfiaco/Looper (antes Grabadora) |
| `sync_looper/` | Looper sincronizado con metrónomo LED | erfiaco/sync_looper |
| `backing_player/` | Reproductor de bases con LED de metrónomo y servidor web | erfiaco/backing_player |
| `practice_player/` | Reproductor para practicar (tempo y tono) | erfiaco/practice_player |
| `metronome/` | Metrónomo | erfiaco/Metronome |
| `bluetooth_recorder/` | Grabadora por Bluetooth | erfiaco/bluetooth_recorder |
| `sistema/` | Configuración de la raspi: config.txt, red, ALSA, servicios, paquetes | — |

`raspi-looper` sigue aparte, en su fork: erfiaco/raspi-looper.

## Instalación en la raspi

Las carpetas tienen los mismos nombres que en la raspi, así que basta con clonar el repo en `~/Proyects`:

Con una Pi recién instalada (Raspberry Pi OS **Bullseye** 64 bits, usuario **Javo**, wifi y SSH ya configurados):

```
git clone https://github.com/erfiaco/groovebox.git ~/Proyects
bash ~/Proyects/sistema/install.sh
```

`install.sh` instala los paquetes, configura el AudioInjector, I2C, ALSA y el hotspot, compila lg y bluez-alsa, crea los entornos de Python, clona raspi-looper y deja el boot_menu arrancando solo. Se puede volver a ejecutar sin problema.

El audio (pistas, loops, audio_files) **no está en git**: se copia aparte desde la copia de seguridad (el script dice cómo al terminar).

## Estado

Cada carpeta se importó desde la rama que corría en la Pi 3B+ el 2026-11-20 (las `wip/raspi-2026-11-20` incluyen cambios sin terminar).
Problemas conocidos (ver el diagnóstico):
- `sistema/etc/asound.conf` usa la tarjeta nº 1, que desde que se añadió snd-aloop es el HDMI. De momento se deja así (ahora toca ordenar, no cambiar el funcionamiento). Mejora pendiente para cuando la Pi 4 esté montada: usar `hw:audioinjectorpi`; un intento anterior dio problemas que hay que investigar.
- El boot_menu arranca por dos vías (servicio systemd y crontab), igual que en la Pi vieja. Con la Pi 4 montada se averiguará cuál funciona y se quitará la otra.
- Cada programa tiene su propio `oled_display.py` y `buttons_manager.py` con su propio mapeo de pines. La idea es unificarlos en `comun/`.
