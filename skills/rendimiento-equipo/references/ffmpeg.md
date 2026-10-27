# ffmpeg con VideoToolbox

Qué hacer con ffmpeg en un Mac con motores de video. `perfil.py` ya entrega los argumentos para tu equipo; esto
explica el porqué. Niveles de evidencia: Oficial / Mantenedor / Medición / Criterio.

## Reglas

- `-nostdin` siempre en scripts y agentes: sin él ffmpeg lee la entrada estándar y puede quedarse esperando.
- Decodificar por hardware: `-hwaccel videotoolbox` va ANTES de `-i`. (Medición en el piloto: gana al CPU. La
  guía genérica de ffmpeg dice lo contrario, por eso `medir.py decodificar` existe: se comprueba en cada equipo.)
- Codificar por hardware: `-c:v h264_videotoolbox -b:v 12M -allow_sw 0` para finales de 1080×1920 y
  `-b:v 3500k` para vistas previas (Criterio, con la medición del piloto de que 12M mantiene la calidad).
  `hevc_videotoolbox` si el destino acepta HEVC; `prores_videotoolbox` para intermedios.
- Nunca dejar los valores por defecto del codificador (regla de las fuentes de la skill). En ffmpeg 6.0 `-allow_sw`
  ya vale false por defecto (comprobado con `ffmpeg -h encoder=h264_videotoolbox`, que también lista `-require_sw`,
  `-constant_bit_rate`, `-profile`, `-level` y `-coder`), pero se escribe explícito para que otra versión no cambie
  el comportamiento sin avisar.
- `-allow_sw 0`: que falle antes de caer a CPU sin avisar.
- Calidad constante: `-q:v` solo funciona en Apple Silicon. Referencia: `h264_videotoolbox -q:v 70` ≈
  x264 crf 22 (Mantenedor, fuente única; no verificada aquí). El camino por defecto de la skill es bitrate fijo.
- Sin hardware disponible: `-c:v libx264 -preset medium -crf 20`.
- Tras medir una calidad dudosa, comparar un fotograma de cada versión y el tamaño del archivo (`medir.py` lo hace
  con la diferencia media sobre 255; el criterio de la skill es menor de 2/255).

## HDR a SDR

- Ruta por defecto: `zscale` + `tonemap` en CPU, UNA vez por tramo, guardando el SDR y reutilizándolo. Nunca
  convertir el video completo si solo se usa un tramo.
- `scale_vt` (conversión por hardware) existe en ffmpeg reciente, pero hay un reporte de colores erróneos
  (Mantenedor) y el ffmpeg del piloto no lo trae. Solo se usa si `perfil-medido.json` lo marca como
  `"scale_vt": "validado"` en `ffmpeg.hdr_sdr` y el ffmpeg elegido lo tiene.
- Receta estándar de la comunidad (FFmpeg wiki, nivel Mantenedor), para HLG o PQ etiquetados:

  ```
  -vf "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
  ```

  Comprobación hecha al construir la skill: esta cadena corre sin error en ffmpeg 6.0 sobre un HEVC 10 bits HLG
  de iPhone y produce H.264 yuv420p bt709 con `h264_videotoolbox`. El aspecto visual de la conversión NO se
  revisó: mira un fotograma antes de dar por bueno el tonemap para una pieza final.
- Cada tonemap en CPU es pesado: no lanzar varios a la vez ni junto a 3 renders.

## Qué ffmpeg usar

`diagnosticar.py` busca ffmpeg en `PATH`, en rutas conocidas (Homebrew, MacPorts, el ffmpeg incluido en
OpenWhispr) y en `RENDIMIENTO_FFMPEG`; escanea `-encoders`, `-filters` y `-hwaccels` buscando videotoolbox,
scale_vt, zscale y tonemap, y elige el que más capacidades útiles tiene. El ffmpeg de `PATH` no siempre es el
mejor: por eso se pasa la ruta elegida en el bloque para subagentes. Si falta ffprobe, la duración se lee de
`ffmpeg -i`.

## Qué no está resuelto

- No se midió `hevc_videotoolbox` ni `prores_videotoolbox` frente a sus equivalentes en CPU.
- No se validó `scale_vt` en ningún equipo.
- Se midió con un solo tipo de fuente (HEVC de iPhone). Otras fuentes pueden comportarse distinto.
