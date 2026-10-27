# Remotion (4.0.x) en Mac

Qué dice la documentación, qué se midió y qué decide `perfil.py`. Niveles: Oficial (docs de Remotion) /
Medición / Criterio. Enlaces en `fuentes.md`.

## Concurrencia

- Por defecto Remotion usa la mitad de los hilos. Subirla demasiado produce «Target closed» o SIGKILL (Oficial).
  Se mide con `npx remotion benchmark --concurrencies` (Oficial).
- Fórmula de `perfil.py` (Criterio, heredada de una regla práctica; se sustituye con lo medido):
  - un render solo: `round(núcleos del nivel 0 × 0,6)`;
  - varios en paralelo: `núcleos del nivel 0 × 0,9 ÷ renders`, y se toma el menor de los dos.
  Los «núcleos del nivel 0» salen de `hw.perflevel0.physicalcpu`; no se asume cuántos niveles hay.
- Para fijar un valor medido: en `perfil-medido.json`, `remotion.concurrencia_por_render` = `{"1": 6, "3": 3}`
  (la clave es el número de renders en paralelo). Lo medido gana a la fórmula.
- Frenos: memoria (presión ≥2 o swap creciendo) → un render a la vez; térmico serious o critical → mitad de
  `--concurrency` y mitad de renders en paralelo.

## Codificador por hardware

- `--hardware-acceleration` (VideoToolbox: h264, h265, prores). Recomendado: `required` + `--video-bitrate=12M`
  (Oficial + Medición del piloto). `required` falla si no hay hardware, que es lo que se quiere.
- Con `--crf`, `if-possible` cae a libx264 en silencio (Oficial). No pasar `--crf` junto al hardware.
- Sin `--video-bitrate` el archivo sale mucho más grande (Oficial; en el piloto, casi el doble).
- `perfil.py` solo añade estas banderas si el diagnóstico confirma un codificador H.264 por hardware (o si el
  perfil medido las adoptó).

## `--gl`

- `--gl=angle` usa la GPU para dibujar, pero tiene una fuga de memoria conocida: partir los renders largos
  (Oficial). Su beneficio en macOS no está documentado (Oficial) y las mediciones del piloto tuvieron ruido: queda
  **pendiente** hasta medir en limpio con `medir.py remotion` (sin otros renders ni ffmpeg pesado en marcha).
- `perfil.py` no pasa `--gl` salvo que `perfil-medido.json` lo tenga con estado `gana` o `adoptado`.

## Caché de OffthreadVideo

- Por defecto cada render reserva el 50 % de la memoria disponible; tres renders juntos se pasan de la RAM
  (Oficial). Fijar `--offthreadvideo-cache-size-in-bytes` por render.
- Fórmula de `perfil.py` (Criterio): `memoria total × 0,25 ÷ renders pedidos`, redondeada a MiB.
- Los hilos de OffthreadVideo se dejan como están (2). En el CLI 4.0.537 la bandera se llama
  `--offthreadvideo-video-threads` (comprobado con `remotion render --help`).

## Otros detalles de la versión

- Con Apple Silicon y macOS 15 o superior (desde 4.0.534), la captura por memoria compartida hace que
  `imageFormat` y `jpegQuality` no tengan efecto (Oficial).
- `transparent` en OffthreadVideo extrae PNG y es más lento (Oficial).
- Comprobado en el CLI 4.0.537: existen `--frames`, `--concurrency`, `--gl`, `--hardware-acceleration`,
  `--video-bitrate`, `--crf`, `--log`, `--overwrite`, `--offthreadvideo-cache-size-in-bytes`.

## Medir

```
python3 scripts/medir.py remotion --proyecto <ruta> --composicion <Id> --fotogramas 0-149 --repeticiones 3 --registrar
```

Corre las variantes base, angle, hardware y ambos, intercaladas, con la misma `--concurrency`. Compara un
fotograma del medio contra la base. Solo actualiza el perfil con un ganador claro (≥15 % mejor y diferencia visual
media <2/255) y sin otros procesos pesados en marcha. `--criterio cpu` elige por menor uso de CPU en vez de
tiempo real; así se adoptó el hardware en el piloto. `--solo-comandos` muestra los comandos sin ejecutarlos.
