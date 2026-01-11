#!/usr/bin/env python3
"""
Grabador Bluetooth - arecord directo (sin chunks, sin gaps)
Selección de duración con botones GPIO26 (bajar) y GPIO6 (subir)
"""

import subprocess
import time
import datetime
import os
from threading import Thread
from gpiozero import Button, Device
from gpiozero.pins.lgpio import LGPIOFactory
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont

Device.pin_factory = LGPIOFactory()

class BluetoothRecorder:
    SAMPLE_RATE = 44100
    CHANNELS = 2
    
    def __init__(self, output_dir="recordings"):
        self.output_dir = output_dir
        self.grabando = False
        self.duracion_seg = 60  # Duración inicial: 1 minuto
        self.tiempo_inicio = None
        self.archivo_actual = None
        self.proceso_arecord = None
        self.proceso_audio_live = None  # Para bluealsa-aplay (audio en vivo)
        self.device_mac = None  # MAC del dispositivo Bluetooth conectado
        
        # Para incremento variable
        self.tiempo_pulsado_inicio = None
        
        # Crear directorio si no existe
        os.makedirs(self.output_dir, exist_ok=True)
        
        # OLED Display
        self.serial = i2c(port=1, address=0x3C)
        self.device = ssd1306(self.serial, width=128, height=64)
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            self.font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            self.font = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
        
        # Botones: GPIO26 (bajar), GPIO6 (subir), GPIO5 (START), GPIO13 (salir con pulsación larga)
        time.sleep(1.2)
        self.btn_bajar = Button(26, pull_up=True, bounce_time=0.03)
        self.btn_subir = Button(6, pull_up=True, bounce_time=0.03)
        self.btn_start = Button(5, pull_up=True, bounce_time=0.03)
        self.btn_salir = Button(13, pull_up=True, bounce_time=0.03)
        
        self.btn_bajar.when_pressed = self.on_bajar_pressed
        self.btn_bajar.when_released = self.on_button_released
        self.btn_subir.when_pressed = self.on_subir_pressed
        self.btn_subir.when_released = self.on_button_released
        self.btn_start.when_pressed = self.on_start_pressed
        self.btn_salir.when_pressed = self.on_salir_pressed
        self.btn_salir.when_released = self.on_salir_released
        
        # Thread para incremento continuo
        self.boton_presionado = None  # 'subir' o 'bajar'
        
        # Para salir con pulsación larga
        self.salir_presionado_inicio = None
        self.debe_salir = False
        
    def mostrar_pantalla(self, mensaje1, mensaje2="", mensaje3=""):
        """Muestra estado en el OLED"""
        img = Image.new("1", (128, 64))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 128, 64), fill=0)
        
        d.text((5, 5), mensaje1, font=self.font, fill=255)
        if mensaje2:
            d.text((5, 28), mensaje2, font=self.font_small, fill=255)
        if mensaje3:
            d.text((5, 45), mensaje3, font=self.font_small, fill=255)
        
        self.device.display(img)
    
    def formatear_tiempo(self, segundos):
        """Convierte segundos a formato legible"""
        if segundos < 60:
            return f"{segundos}s"
        mins = segundos // 60
        segs = segundos % 60
        if segs == 0:
            return f"{mins}min"
        return f"{mins}min {segs}s"
    
    def actualizar_display_duracion(self):
        """Actualiza display con duración actual"""
        tiempo_str = self.formatear_tiempo(self.duracion_seg)
        self.mostrar_pantalla(
            "🎙️ BT Recorder",
            f"Duración: {tiempo_str}",
            "26:↓ 6:↑ 5:OK 13:Exit"
        )
    
    def on_bajar_pressed(self):
        """Inicia proceso de bajar duración"""
        if not self.grabando:
            self.boton_presionado = 'bajar'
            self.tiempo_pulsado_inicio = time.time()
            # Primer cambio inmediato
            self.cambiar_duracion(-1)
            # Iniciar thread para incremento continuo
            Thread(target=self.incremento_continuo, daemon=True).start()
    
    def on_subir_pressed(self):
        """Inicia proceso de subir duración"""
        if not self.grabando:
            self.boton_presionado = 'subir'
            self.tiempo_pulsado_inicio = time.time()
            # Primer cambio inmediato
            self.cambiar_duracion(1)
            # Iniciar thread para incremento continuo
            Thread(target=self.incremento_continuo, daemon=True).start()
    
    def on_button_released(self):
        """Detiene incremento continuo"""
        self.boton_presionado = None
    
    def incremento_continuo(self):
        """Thread que incrementa/decrementa continuamente mientras está pulsado"""
        time.sleep(0.5)  # Pausa inicial antes de repetir
        
        while self.boton_presionado:
            tiempo_pulsado = time.time() - self.tiempo_pulsado_inicio
            
            # Determinar incremento según tiempo pulsado
            if tiempo_pulsado < 3:
                incremento = 1  # 1 seg
                delay = 0.2
            elif tiempo_pulsado < 6:
                incremento = 5  # 5 seg
                delay = 0.3
            else:
                incremento = 10  # 10 seg
                delay = 0.3
            
            # Aplicar cambio
            if self.boton_presionado == 'subir':
                self.cambiar_duracion(incremento)
            elif self.boton_presionado == 'bajar':
                self.cambiar_duracion(-incremento)
            
            time.sleep(delay)
    
    def cambiar_duracion(self, delta):
        """Cambia la duración en delta segundos"""
        self.duracion_seg = max(5, min(600, self.duracion_seg + delta))  # Entre 5s y 10min
        self.actualizar_display_duracion()
        print(f"⏱️  Duración: {self.formatear_tiempo(self.duracion_seg)}")
    
    def on_start_pressed(self):
        """Inicia grabación"""
        if not self.grabando:
            print(f"\n▶️  Iniciando grabación de {self.formatear_tiempo(self.duracion_seg)}...")
            self.iniciar_grabacion()
    
    def on_salir_pressed(self):
        """Detecta inicio de pulsación del botón salir"""
        if not self.grabando:  # Solo funciona si no está grabando
            self.salir_presionado_inicio = time.time()
            Thread(target=self.detectar_pulsacion_larga_salir, daemon=True).start()
    
    def on_salir_released(self):
        """Cancela detección de pulsación larga si se suelta antes de 3 seg"""
        self.salir_presionado_inicio = None
    
    def detectar_pulsacion_larga_salir(self):
        """Thread que detecta si el botón se mantiene presionado 3 segundos"""
        inicio = self.salir_presionado_inicio
        if inicio is None:
            return
        
        time.sleep(3)  # Esperar 3 segundos
        
        # Si todavía está presionado después de 3 seg
        if self.salir_presionado_inicio == inicio:
            print("\n🚪 Pulsación larga detectada → Saliendo...")
            self.mostrar_pantalla("SALIENDO...", "Volviendo al", "boot menu")
            self.debe_salir = True
            time.sleep(1)
    
    def actualizar_tiempo_grabacion(self):
        """Thread que actualiza el display durante la grabación"""
        # Esperar a que el proceso esté listo
        time.sleep(0.2)
        
        # Obtener nombre del archivo
        nombre_archivo = os.path.basename(self.archivo_actual)
        
        # Imprimir contador inicial inmediatamente
        print(f"  ⏱️  00:00 / Quedan: {self.duracion_seg//60:02d}:{self.duracion_seg%60:02d}")
        ultimo_print = 0
        
        while self.grabando:
            transcurrido = int(time.time() - self.tiempo_inicio)
            restante = max(0, self.duracion_seg - transcurrido)
            
            # Si ya terminó el tiempo, salir
            if restante <= 0:
                break
            
            mins_rest = restante // 60
            segs_rest = restante % 60
            
            # Actualizar OLED - mostrar nombre del archivo y tiempo restante
            self.mostrar_pantalla(
                "🎙️ GRABANDO",
                nombre_archivo,
                f"({mins_rest:02d}:{segs_rest:02d})"
            )
            
            # Imprimir cada segundo en terminal
            if transcurrido != ultimo_print:
                mins_trans = transcurrido // 60
                segs_trans = transcurrido % 60
                print(f"  ⏱️  {mins_trans:02d}:{segs_trans:02d} / Quedan: {mins_rest:02d}:{segs_rest:02d}")
                ultimo_print = transcurrido
            
            time.sleep(1)
    
    def iniciar_grabacion(self):
        """Inicia grabación con arecord directo (sin chunks)"""
        if self.grabando:
            return
        
        # IMPORTANTE: Parar audio en vivo durante la grabación
        # (bluealsa-aplay y arecord no pueden leer el mismo stream simultáneamente)
        if self.proceso_audio_live:
            print("🔇 Pausando audio en vivo para grabar...")
            try:
                self.proceso_audio_live.terminate()
                self.proceso_audio_live.wait(timeout=1)
            except:
                pass
            self.proceso_audio_live = None
            time.sleep(0.3)  # Dar tiempo a que se libere el stream
        
        # Detectar dispositivo bluealsa
        print("📡 Detectando dispositivo Bluetooth...")
        device = None
        device_mac = None
        try:
            result = subprocess.run(
                ['bluealsa-aplay', '-L'],
                capture_output=True,
                text=True
            )
            for line in result.stdout.split('\n'):
                if 'DEV=' in line and 'PROFILE=a2dp' in line:
                    device = line.strip()
                    # Extraer MAC
                    if 'DEV=' in device:
                        device_mac = device.split('DEV=')[1].split(',')[0]
                    print(f"✅ Encontrado: {device}")
                    break
            
            if not device:
                print("❌ No se encontró dispositivo bluealsa")
                return
        except Exception as e:
            print(f"❌ Error: {e}")
            return
        
        # Generar nombre de archivo MMXX (mes + número incremental)
        mes_actual = datetime.datetime.now().strftime('%m')
        
        # Buscar archivos del mes actual para obtener el siguiente número
        archivos_existentes = []
        try:
            for f in os.listdir(self.output_dir):
                if f.startswith(mes_actual) and f.endswith('.wav'):
                    try:
                        # Extraer número después del mes (MMXX.wav)
                        numero = int(f[2:4])
                        archivos_existentes.append(numero)
                    except:
                        pass
        except:
            pass
        
        # Calcular siguiente número
        if archivos_existentes:
            siguiente_numero = max(archivos_existentes) + 1
        else:
            siguiente_numero = 1
        
        filename = f"{mes_actual}{siguiente_numero:02d}.wav"
        self.archivo_actual = os.path.join(self.output_dir, filename)
        
        print(f"📁 Archivo: {self.archivo_actual}")
        print(f"⏱️  Duración: {self.formatear_tiempo(self.duracion_seg)}\n")
        
        self.grabando = True
        self.tiempo_inicio = time.time()
        
        # Thread para actualizar display
        Thread(target=self.actualizar_tiempo_grabacion, daemon=True).start()
        
        # Dar tiempo al thread para iniciarse
        time.sleep(0.1)
        
        # Comando arecord - GRABACIÓN DIRECTA SIN CHUNKS
        cmd = [
            'arecord',
            '-D', device,
            '-f', 'cd',
            '-d', str(self.duracion_seg),
            self.archivo_actual
        ]
        
        try:
            # Lanzar arecord y esperar a que termine
            self.proceso_arecord = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            print(f"🎙️  GRABANDO {self.duracion_seg}s...\n")
            
            # Esperar a que termine
            stdout, stderr = self.proceso_arecord.communicate()
            
            transcurrido = int(time.time() - self.tiempo_inicio)
            print(f"\n✅ Grabación completada")
            print(f"⏱️  Tiempo: {transcurrido}s")
            
            self.mostrar_pantalla("✅ COMPLETO", f"{transcurrido}s grabados", "Saliendo...")
            time.sleep(3)
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
        finally:
            self.grabando = False
            self.proceso_arecord = None
            
            # Reanudar audio en vivo
            if device_mac:
                print("🔊 Reanudando audio en vivo...")
                try:
                    self.proceso_audio_live = subprocess.Popen(
                        ['bluealsa-aplay', device_mac],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    time.sleep(0.5)  # Dar tiempo a que se estabilice
                except Exception as e:
                    print(f"⚠️  No se pudo reanudar audio: {e}")
    
    def cleanup(self):
        """Limpieza al salir"""
        # Parar audio en vivo
        if self.proceso_audio_live:
            try:
                print("🔇 Deteniendo audio en vivo...")
                self.proceso_audio_live.terminate()
                self.proceso_audio_live.wait(timeout=2)
            except:
                try:
                    self.proceso_audio_live.kill()
                except:
                    pass
        
        # Parar grabación si está activa
        if self.proceso_arecord:
            try:
                self.proceso_arecord.terminate()
                self.proceso_arecord.wait(timeout=2)
            except:
                try:
                    self.proceso_arecord.kill()
                except:
                    pass
        
        try:
            self.btn_bajar.close()
            self.btn_subir.close()
            self.btn_start.close()
            self.btn_salir.close()
        except:
            pass
        
        img = Image.new("1", (128, 64))
        self.device.display(img)
    
    def run(self):
        """Ejecuta el grabador"""
        print("\n" + "="*50)
        print("🎙️  GRABADOR BLUETOOTH")
        print("="*50)
        print(f"📁 {self.output_dir}")
        print("="*50 + "\n")
        
        # Detectar y activar audio en vivo por RCA
        print("🔊 Activando audio Bluetooth → RCA...")
        try:
            result = subprocess.run(
                ['bluealsa-aplay', '-L'],
                capture_output=True,
                text=True,
                timeout=3
            )
            device = None
            for line in result.stdout.split('\n'):
                if 'DEV=' in line and 'PROFILE=a2dp' in line:
                    device = line.strip()
                    break
            
            if device:
                # Extraer solo la MAC del device string
                mac = None
                if 'DEV=' in device:
                    mac = device.split('DEV=')[1].split(',')[0]
                
                if mac:
                    self.device_mac = mac  # Guardar para reanudar después
                    # Lanzar bluealsa-aplay para audio en vivo
                    self.proceso_audio_live = subprocess.Popen(
                        ['bluealsa-aplay', mac],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print(f"✅ Audio en vivo activado ({mac})")
                else:
                    print("⚠️  No se pudo extraer MAC, audio en vivo desactivado")
            else:
                print("⚠️  Dispositivo Bluetooth no conectado")
                print("   Audio en vivo no disponible")
        except Exception as e:
            print(f"⚠️  Audio en vivo no disponible: {e}")
        
        print()
        
        self.actualizar_display_duracion()
        
        print("🎵 Conecta móvil y reproduce música")
        print("⏱️  Ajusta: GPIO26(↓) GPIO6(↑)")
        print("▶️  Inicia: GPIO5")
        print("🚪 Salir: GPIO13 (mantener 3 seg)\n")
        
        try:
            # Esperar inicio de grabación o señal de salida
            while not self.grabando and not self.debe_salir:
                time.sleep(0.1)
            
            # Si debe salir, no esperar a grabar
            if not self.debe_salir:
                # Esperar fin de grabación
                while self.grabando:
                    time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n🛑 Interrumpido")
        
        self.cleanup()
        print("\n🔙 Volviendo al boot menu...\n")
        subprocess.Popen(["/usr/bin/python3", "/home/Javo/Proyects/boot_menu/boot_menu.py"])


if __name__ == "__main__":
    recorder = BluetoothRecorder(
        output_dir="/home/Javo/Proyects/practice_player/audio_files"
    )
    
    try:
        recorder.run()
    except KeyboardInterrupt:
        recorder.cleanup()
    except Exception as e:
        print(f"❌ Error: {e}")
        recorder.cleanup()
