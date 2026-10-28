# Arquitectura de Apple Silicon: qué trae cada generación y qué hace la skill con ello

Niveles de evidencia: **Oficial** (Apple, código de ffmpeg o whisper.cpp), **Medición** (en el Mac piloto),
**Criterio**. Revisado el 28.10.2026.

## Cómo decide, y por qué aguanta chips nuevos

1. **Lo medido manda** (`perfil-medido.json`).
2. **Después, lo que el equipo declara en tiempo de ejecución:** familia Metal, codecs por hardware,
   extensiones de la CPU y núcleos del Neural Engine. Un chip nuevo con las mismas capacidades recibe las mismas
   reglas sin tocar nada.
3. **Al final, la tabla de Apple** (`assets/chips_apple.json`), solo para lo que ninguna API dice, como cuántos
   motores de codificación de video hay.

Si aparece una familia Metal más nueva que `apple10`, la skill aplica las reglas comunes, lo dice y pide medir.
Las reglas viven en `scripts/arquitectura.py`; `perfil.py --formato texto` las muestra en la sección ARQUITECTURA.

## Saltos por generación

| Generación | Lo nuevo | Lo que hace la skill | Fuente |
|---|---|---|---|
| M1 (2020) | Primer motor de medios del Mac: H.264 y HEVC por hardware. Neural Engine de 16 núcleos. Familia Metal apple7. | Codifica con `h264_videotoolbox` y lee con `-hwaccel videotoolbox`. | [Apple](https://www.apple.com/newsroom/2020/11/apple-unleashes-m1/) |
| M1 Pro y M1 Max (2021) | Primeros motores de ProRes (Pro: 1; Max: 2). M1 Max: 2 motores de codificación de video. | ProRes con `prores_videotoolbox`. | [Apple](https://www.apple.com/newsroom/2021/10/introducing-m1-pro-and-m1-max-the-most-powerful-chips-apple-has-ever-built/) |
| M1 Ultra (2022) | UltraFusion: dos M1 Max en un chip. Neural Engine de 32 núcleos. | Cuenta los núcleos de los dos chips. | [Apple](https://www.apple.com/newsroom/2022/03/apple-unveils-m1-ultra-the-worlds-most-powerful-chip-for-a-personal-computer/) |
| M2 (2022) | ProRes llega al chip base; decodifica H.264 y HEVC en 8K. Familia apple8. | ProRes por hardware también en el chip base. | [Apple](https://www.apple.com/newsroom/2022/06/apple-unveils-m2-with-breakthrough-performance-and-capabilities/) |
| M3 (2023) | Dynamic Caching, sombreado de mallas y trazado de rayos por hardware. Primera decodificación AV1 por hardware. Familia apple9. | AV1 por hardware si ffmpeg es 8.0 o posterior. Avisa que Blender usa el trazado de rayos solo. | [Apple](https://www.apple.com/newsroom/2023/10/apple-unveils-m3-m3-pro-and-m3-max-the-most-advanced-chips-for-a-personal-computer/) |
| M4 (2024) | Trazado de rayos el doble de rápido; Neural Engine de 38 TOPS. Misma familia que M3 (apple9). El sistema declara SME en la CPU. | Lo mismo que M3. SME lo usa Accelerate solo. | [Apple](https://www.apple.com/newsroom/2024/10/apple-introduces-m4-pro-and-m4-max/) |
| M5 (2025) | Un Neural Accelerator en cada núcleo de la GPU; trazado de rayos de 3.ª generación; Dynamic Caching nuevo. Familia apple10. | Explica qué herramientas los usan (whisper.cpp desde v1.8.3) y pide medir antes de cambiar el backend de Whisper. | [Apple](https://www.apple.com/newsroom/2025/10/apple-unleashes-m5-the-next-big-leap-in-ai-performance-for-apple-silicon/) |
| M5 Pro y M5 Max (2026) | Dos dies (Fusion). Núcleos «super» y «performance» nuevos, sin núcleos de eficiencia. | Reparte Remotion entre super y performance (`perfil.py` 1.0.1). | [Apple](https://www.apple.com/newsroom/2026/03/apple-debuts-m5-pro-and-m5-max-to-supercharge-the-most-demanding-pro-workflows/) |
| M5 Ultra (2026) | Cuatro dies; 12 super y 24 performance; 4 motores de codificación. | Mide cuántas codificaciones rinden a la vez. | [Apple](https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/) |
| M6 (2026) | Primer chip de 2 nm. Tres niveles de CPU (2 super, 4 performance, 6 eficiencia). Neural Engine doble de 16 núcleos. GPU con Neural Accelerators. | Igual que M5. Su familia Metal no está en la tabla de Apple: si es nueva, la skill pide medir. | [Apple](https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/) |

**Motores de medios por nivel.** No cambian en cada generación:

- base y Pro: 1 de codificación, 1 de decodificación y 1 de ProRes;
- Max: 2 de codificación y 2 de ProRes;
- Ultra: 4 de codificación, 2 de decodificación y 4 de ProRes.

Ningún chip codifica AV1 por hardware. Fuente: fichas técnicas de Apple ([MacBook Pro](https://www.apple.com/macbook-pro/specs/),
[Mac Studio](https://www.apple.com/mac-studio/specs/)).

## Qué usa cada herramienta

| Capacidad | ffmpeg | whisper.cpp | Core ML y Vision | Chrome y Remotion | Blender |
|---|---|---|---|---|---|
| H.264 y HEVC por hardware | Sí (`h264_videotoolbox`, `-hwaccel videotoolbox`) | — | — | Sí; Remotion con `--hardware-acceleration` desde 4.0.236 | — |
| ProRes por hardware | Sí, desde ffmpeg 5.0 (`prores_videotoolbox`) | — | — | Remotion desde 4.0.228 | — |
| AV1 por hardware (leer) | Sí, desde ffmpeg **8.0**; en 7.1 o anterior, no | — | — | Chrome lo consulta solo | — |
| Varios motores de codificación | No hay fuente de si una sola codificación usa más de uno; cuántas a la vez rinden, se mide | — | — | — | — |
| Dynamic Caching | Automático | Automático | Automático | Automático | Automático |
| Trazado de rayos por hardware | — | — | — | No (WebGPU no lo tiene) | Sí, MetalRT desde M3 ([PR 114296](https://projects.blender.org/blender/blender/pulls/114296)) |
| Neural Accelerators de la GPU | No | Sí, desde v1.8.3; mejor v1.9.5 o posterior | Sí, Core ML y Metal Performance Shaders, solos | — | — |
| Neural Engine | No | Solo compilado con Core ML y con el codificador `.mlmodelc` | Sí, solos | — | — |

Fuentes del código:

- ffmpeg: [hwaccels.h de 8.0](https://github.com/FFmpeg/FFmpeg/blob/n8.0/libavcodec/hwaccels.h) y [Changelog](https://github.com/FFmpeg/FFmpeg/blob/master/Changelog).
- whisper.cpp: [ggml-metal-device.m](https://github.com/ggml-org/whisper.cpp/blob/master/ggml/src/ggml-metal/ggml-metal-device.m).
- Remotion: [aceleración por hardware](https://www.remotion.dev/docs/hardware-acceleration).

**Medido en el M4 Pro piloto** (`medir.py paralelo`, 10 s por copia, dos corridas):

| Codificaciones a la vez | Segundos de video por segundo |
|---|---|
| 1 | 6,6 |
| 2 | 5,7 |
| 4 | 6,0 |

Con un solo motor, lanzar más a la vez no suma. Con clips de 2 s, la Mac virtual de GitHub mostró 1,58× con dos:
el arranque de ffmpeg pesaba más que la codificación. Por eso `medir.py` no registra copias de menos de 5 s.

## Qué se puede detectar y qué no

| Dato | Cómo | ¿Fiable? |
|---|---|---|
| Familia Metal | `MTLDevice.supportsFamily` recorriendo los números (sin nombrarlos, para que compile con SDK viejos) | Sí. Las familias se acumulan: cuenta la más alta. |
| Metal 4 | `supportsFamily` con el número de `metal4` | Sí. Existe desde M1 con macOS 26: no prueba que haya Neural Accelerators. |
| Trazado de rayos por hardware | `supportsRaytracing` **no sirve** (es verdadero desde M1); se usa la familia apple9 | Indirecto |
| Sombreado de mallas y Dynamic Caching | Sin API; se usa la familia apple9 | Indirecto |
| Neural Accelerators de la GPU | Familia apple10 | Sí |
| Decodificación por codec | `VTIsHardwareDecodeSupported` | Sí |
| Codificadores por hardware | `VTCopyVideoEncoderList` con `IsHardwareAccelerated` | Sí, aunque dice que existen, no que estén libres |
| Cuántos motores de codificación | **Ninguna API.** Tabla de Apple y `medir.py paralelo` | No |
| Núcleos del Neural Engine | `MLNeuralEngineComputeDevice.totalCoreCount` | Sí |
| SME en la CPU | `sysctl hw.optional.arm.FEAT_SME*` (la skill lee todas las `FEAT_*` sin lista fija) | Sí |
| Niveles de CPU | `hw.perflevelN.name` («Super», «Performance», «Efficiency») | Sí |

## Ideas que no son ciertas

- **«El motor de medios llegó con M2».** No: M1 ya lo tenía. M1 Pro y M1 Max sumaron ProRes; M2 lo llevó al chip
  base y sumó 8K.
- **«Las APIs de tensores de Metal 4 necesitan M5».** La API existe desde M1 con macOS 26. Lo exclusivo de M5 es el
  hardware que la acelera.
- **«M4 trae una familia Metal nueva».** No: M3 y M4 son apple9. La nueva, apple10, llega con M5.
- **«Cada generación duplica los motores de codificación».** No: el número depende del nivel (base, Pro, Max,
  Ultra), no de la generación.
- **«Core ML en el Neural Engine sigue siendo lo mejor para Whisper en M5».** Ninguna fuente lo muestra frente a
  Metal en estos chips. Se mide.
- **«Apple da los TOPS del Neural Engine de cada chip».** Solo los da para M1, M2, M1 Ultra, M2 Ultra y M4.

## Cuando salga un chip nuevo

1. Agrega su fila a `assets/chips_apple.json` con lo que publique Apple (motores de medios, sobre todo).
2. Si Apple publica su familia Metal y trae algo nuevo, suma una regla en `scripts/arquitectura.py` y sube
   `FAMILIA_CONOCIDA`.
3. Mide en el equipo: `medir.py codificar`, `decodificar` y `paralelo` con `--registrar`. Lo medido manda.
