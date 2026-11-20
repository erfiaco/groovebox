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

```
git clone https://github.com/erfiaco/groovebox.git ~/Proyects
```

Los entornos de Python y el audio (pistas, loops, audio_files) **no están en git**. El audio se copia aparte desde la copia de seguridad.
Pendiente: `sistema/install.sh`, que instalará paquetes, configs y servicios.

## Estado

Cada carpeta se importó desde la rama que corría en la Pi 3B+ el 2026-11-20 (las `wip/raspi-2026-11-20` incluyen cambios sin terminar).
Problemas conocidos (ver el diagnóstico):
- `sistema/etc/asound.conf` usa la tarjeta nº 1, que desde que se añadió snd-aloop es el HDMI. Hay que pasar a `hw:audioinjectorpi`.
- Cada programa tiene su propio `oled_display.py` y `buttons_manager.py` con su propio mapeo de pines. La idea es unificarlos en `comun/`.
