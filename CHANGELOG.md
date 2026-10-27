# Cambios

## Página · 27.10.2026

- Sección «Antes y después» al inicio: siete mediciones del Mac piloto que pasan de un estado al otro con el scroll.
- Chip dibujado en el estilo del anuncio del M4 Pro (paquete de vidrio y plano de líneas azules), animado: el paquete
  se levanta, el plano se dibuja y se encienden los núcleos de cada motor. Es un dibujo propio, sin imágenes ni logo
  de Apple.
- `docs/index.html` rediseñada: lenguaje de la app Codex y de apple.com, escenas ligadas al scroll en ambos sentidos
  (el chip se divide en seis motores), parallax, iconos de línea y datos como gráficos animados con detalle al pasar
  el cursor.

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
