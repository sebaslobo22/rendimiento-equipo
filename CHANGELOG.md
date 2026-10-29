# Cambios

## 1.4.0 · 29.10.2026

- El modelo de dictado se recomienda por equipo, no por chip: cuenta la memoria (tamaño y ancho de banda), si
  Whisper corre en GPU o en procesador, el freno de memoria y lo medido. Descarta lo que en ese equipo iría a menos
  de 4 veces el tiempo real. Con dos o más modelos medidos sobre el mismo audio, elige por el error medido.
- `medir.py voz` mide también Parakeet, Orukeet y Cohere (sherpa-onnx, con los argumentos de OpenWhispr), calienta
  y repite 3 veces, compara Metal y CPU con `--backends metal,cpu` y lee si whisper-server usa los Neural
  Accelerators (`has tensor`).
- El porcentaje de error ya no castiga cifras, tildes ni «%».
- La regla del M5 ya no da por hecho que whisper.cpp usa los Neural Accelerators: el OpenWhispr 1.10.4 de un M5
  los traía apagados. Dice lo medido en el equipo.
- `perfil.py` elige el modelo de Whisper con un criterio dicho (el que usa OpenWhispr, luego el recomendado, luego
  el más grande) y activa el freno de memoria si el swap pasa del 75 % de su tamaño aunque no crezca.
- Gracias al informe de un MacBook Pro M5 de 16 GB.

## 1.3.0 · 29.10.2026

- Modelo de dictado: la skill recomienda el punto dulce entre precisión y consumo para OpenWhispr, en Mac y en
  Windows. `voz.py` lee el catálogo del OpenWhispr instalado (los modelos nuevos aparecen solos), lo cruza con
  fichas públicas (`assets/fichas_voz.json`) y con la memoria del equipo, y elige el de menos error en español
  que cabe en el 20 % de la memoria. `perfil.py` lo muestra en la sección VOZ.
- `medir.py voz` transcribe un audio tuyo con cada modelo Whisper descargado, en un servidor propio, y mide
  tiempo, memoria y porcentaje de error. En el M4 Pro piloto, Whisper Turbo: 20 veces el tiempo real y 1,8 GB.

## 1.2.0 · 28.10.2026

- La skill tiene en cuenta los saltos de arquitectura de cada generación de Apple Silicon, de M1 a M6. Decide por
  lo que el equipo declara, no por el nombre del chip: un chip nuevo con las mismas capacidades recibe las mismas
  reglas, y uno con una familia Metal más nueva que apple10 se marca para medir.
  - `arquitectura.py`: qué trae el equipo y qué hace la skill con cada cosa. Lo muestra `perfil.py` en la
    sección ARQUITECTURA.
  - `capacidades_macos.swift` informa las familias de versión de Metal (metal3, metal4) y el trazado de rayos, y
    suma ProRes RAW. `diagnosticar.py` lee todas las extensiones de la CPU (SME, SME2…) sin lista fija.
  - `perfil.py` recomienda ProRes con el motor de ProRes (`prores_videotoolbox`) y la lectura por codec, según lo
    que decodifica el chip y la versión de ffmpeg: AV1 por hardware solo con ffmpeg 8.0 o posterior.
    - Con un Remotion anterior a 4.0.236 no pide codificar por hardware.
    - Da el máximo de codificaciones por hardware a la vez.
  - `medir.py paralelo` mide cuántas codificaciones por hardware rinden a la vez: los Max y Ultra traen 2 y 4
    motores, y ninguna API lo dice. En el M4 Pro piloto, dos a la vez rinden 13 % menos que una. Con menos de
    5 s por copia muestra el resultado, pero no lo registra.
  - `assets/chips_apple.json`: la tabla de Apple, solo como referencia para lo que no se puede detectar.
  - `references/arquitectura.md`: los saltos de cada generación con sus fuentes, qué herramienta usa cada uno,
    qué se puede detectar y qué ideas comunes no son ciertas.
- La página muestra lo nuevo de cada chip en el selector.
- La página tiene un recorrido para Windows: arriba del selector se elige «Mac» o «PC con Windows» (se detecta solo).
  Con Windows cambian la portada, la sección del chip (motores de video de cada marca, qué revisa y en qué fase
  va Windows), el antes y después (marcado como medido en Mac) y la instalación; hay un mensaje para medir y un
  enlace para compartir el resultado.

## 1.1.0 · 28.10.2026

- Windows, primera fase: diagnóstico y mediciones, sin recomendaciones hasta medir equipos reales.
  - `diagnosticar.py` lee en Windows los núcleos por clase de eficiencia, la memoria, el archivo de paginación, los
    adaptadores de video con su VRAM, la NPU y el ahorro de energía (`plataforma_windows.py`, solo biblioteca
    estándar). Abre de verdad cada codificador y acelerador por hardware con un clip de 1 s.
  - `medir.py` compara libx264 con NVENC, QSV, AMF y Media Foundation, y la decodificación en CPU con cuda, qsv y
    d3d11va. En Windows mide la CPU con `GetProcessTimes`. Remotion todavía no se mide en Windows.
  - `perfil.py` resume el diagnóstico sin recomendar y entrega las reglas que no dependen del equipo.
  - `limpiar.py` en Windows solo muestra.
  - `install.ps1` enlaza con junctions, sin administrador, y funciona en Windows PowerShell 5.1 y PowerShell 7.
- Pruebas de humo en GitHub Actions para Windows y macOS (`pruebas/`).
- macOS sin cambios de comportamiento: misma huella y mismas recomendaciones en el Mac piloto.

## 1.0.1 · 27.10.2026

- `perfil.py` reparte Remotion con todos los núcleos que no son de eficiencia, no solo con el nivel 0. Desde el
  M5 Pro, Apple tiene núcleos súper y de rendimiento, y antes solo contaban los súper: en un M5 Pro con 3 renders
  daba `--concurrency=1`; ahora da 5. En chips de dos niveles (hasta el M4) el resultado no cambia. Si algún nivel
  no trae nombre, sigue usando solo el nivel 0. `medir.py` usa la misma cuenta.
- La salida de `perfil.py` cambia `nucleos_nivel0` por `nucleos_para_render` y `niveles_para_render`.

## Página · 27.10.2026

- «Ya la instalé. ¿Y ahora?»: tres pruebas para copiar después de instalar (ver tu Mac, convertir un video,
  pedir varias cosas a la vez). Las cifras de cada prueba siguen al chip elegido. También en el README.
- «Instalar y usar» con dos caminos: quien usa las apps (Claude Desktop en la pestaña Code, o Codex) copia un
  mensaje y el agente instala la skill; quien usa la terminal tiene los comandos. Cada camino trae sus tres pasos,
  y la sección dice para quién sirve la skill. El README sigue el mismo orden.
- Selector de Apple Silicon, del M1 al M6 (20 chips): la página cambia el dibujo del chip, sus motores, el ejemplo
  de la portada, las tareas y el antes y después. Solo el M4 Pro está medido. En los demás chips, las cifras son
  estimaciones marcadas con «≈»: escalan lo medido en el piloto con los promedios de Geekbench 7 de cada chip.
  La caché de Remotion y la concurrencia salen de las fórmulas de `perfil.py`. Las especificaciones vienen de Apple.
  Donde Apple no publica un dato, la página lo dice. En navegadores Chromium detecta el chip de quien visita.
- Fila nueva en el antes y después: caché máxima de 3 renders de Remotion, sin fijarla y con la fórmula de la skill.
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
