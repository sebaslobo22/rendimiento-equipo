# Cambios

## 1.0.0 · 27.10.2026

- Primera versión pública de la skill, probada con la carga real del Mac piloto (M4 Pro, 24 GB, macOS 27.2).
- Diagnóstico en tiempo de ejecución: CPU por niveles, memoria y presión, GPU y familia Metal, motores de video,
  Neural Engine, estado térmico y procesos pesados vivos.
- `perfil.py` con frenos y bloque para subagentes; `medir.py` con registro por huella del equipo; `limpiar.py` que
  solo muestra hasta que se le pide aplicar.
- Mediciones adoptadas: codificar y decodificar con VideoToolbox, Remotion con hardware y bitrate fijo, láminas
  de Chrome en CPU, un solo servidor de Whisper con Metal.
- Pendiente: medir `--gl=angle` en Remotion sin otros renders en marcha (una de dos pruebas falló).
- `install.sh` enlaza la skill en Claude Code y en Codex, con prueba y desinstalación.
- Reemplaza a `rendimiento-mac-m4`, que fijaba a mano los valores de un solo chip.
