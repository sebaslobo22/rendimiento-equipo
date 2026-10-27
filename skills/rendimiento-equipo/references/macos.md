# macOS (Apple Silicon): capacidades, motores y límites

Piloto de la skill. Nada de lo de abajo fija un chip: cada capacidad se consulta en tiempo de ejecución
(`scripts/diagnosticar.py` lo hace por ti). Las cifras de un equipo concreto viven en
`~/.local/share/rendimiento-equipo/<huella>/`.

## Índice
1. Capacidad → API o comando
2. Tarea → motor
3. QoS: trabajo de fondo
4. Estado térmico y energía
5. Huella del equipo y datos propios
6. Swift: qué hace `capacidades_macos.swift` y qué hacer si falta

## 1. Capacidad → API o comando

Nivel de evidencia: Oficial (docs de Apple) salvo donde se indica. Enlaces en `fuentes.md`.

| Capacidad | Cómo se consulta | Nota |
|---|---|---|
| Niveles de CPU | `sysctl hw.nperflevels`; para cada N: `hw.perflevelN.{name,physicalcpu,logicalcpu,cpusperl2}` | El nivel 0 es el más rápido. No asumir 2 niveles ni que el 1 se llame «Efficiency» (hay reportes de chips con «Super» y «Performance»). |
| Núcleos lógicos, página, memoria | `hw.logicalcpu`, `hw.pagesize`, `hw.memsize` | |
| Marca y modelo | `machdep.cpu.brand_string`, `hw.model` | Solo informativos. No decidir por nombre de chip. |
| Núcleos de GPU | `system_profiler SPDisplaysDataType -json` → `sppci_cores` | Tarda ~0,2 s. |
| Metal | Swift: `MTLCreateSystemDefaultDevice()` → `hasUnifiedMemory`, `recommendedMaxWorkingSetSize`, `maxBufferLength`, `currentAllocatedSize` | `recommendedMaxWorkingSetSize` es el tope razonable de memoria para la GPU. |
| Familia de GPU | `supportsFamily(MTLGPUFamily(rawValue: 1001…))`; la más alta que responda sí | `MTLGPUFamily(rawValue:)` devuelve nil para valores que el SO no conoce, así que el rango amplio es seguro. |
| Codificadores de video | Swift: `VTCopyVideoEncoderList(nil,&lista)`; filtrar `kVTVideoEncoderList_IsHardwareAccelerated` | No fijar `EncoderID`. |
| Decodificadores de video | Swift: `VTIsHardwareDecodeSupported(codec)` para h264, hevc, prores, av1, vp9 | |
| Neural Engine | Swift (macOS 14+): `MLComputeDevice.allComputeDevices` → `.neuralEngine(let ne)` → `ne.totalCoreCount` | Vision informa qué dispositivos usa cada etapa con `supportedComputeStageDevices`. |
| Térmico | `ProcessInfo.processInfo.thermalState`: nominal, fair, serious, critical | Con serious el sistema ya reduce CPU y GPU. |
| Bajo consumo | `ProcessInfo.processInfo.isLowPowerModeEnabled` | |
| Memoria | `memory_pressure` sin argumentos; `sysctl vm.swapusage kern.memorystatus_vm_pressure_level` | Ver `memoria.md`. |

HDR a SDR en el sistema (Mantenedor/WWDC): AVFoundation convierte a SDR si la composición usa colores Rec.709,
y `AVAssetExportSession` con presets H.264 sale en SDR (WWDC20 10009 y 10010). `avconvert` existe pero no se
probó con HLG real aquí.

## 2. Tarea → motor

Regla: cada tarea al motor que mejor la hace, y la medición decide. Esta tabla es el punto de partida; el
perfil medido de cada equipo la corrige.

| Tarea | Motor | Cómo | Evidencia |
|---|---|---|---|
| Decodificar video H.264, HEVC, ProRes | Motor de video (VideoToolbox) | ffmpeg `-hwaccel videotoolbox` antes de `-i` | Medición en el equipo piloto: gana al CPU. Contradice la guía genérica de ffmpeg, así que se mide en cada equipo (`medir.py decodificar`). |
| Codificar H.264, HEVC, ProRes | Motor de video | `h264_videotoolbox`, `hevc_videotoolbox`, `prores_videotoolbox` con bitrate explícito | Medición en el piloto. Detalle en `ffmpeg.md`. |
| HDR a SDR | CPU (zscale + tonemap) | Una vez por tramo, guardado | Criterio: `scale_vt` tiene un reporte de colores erróneos y no viene en el ffmpeg del piloto. Se cambia solo con validación en el perfil medido. |
| Render de Remotion | Chrome sin ventana (dibujo) + codificador de video | Ver `remotion.md` | Medición con ruido en el piloto; `--gl` pendiente. |
| Transcripción | GPU por Metal con flash attention (whisper.cpp) | Un solo servidor. Ver `whisper.md` | Oficial/Mantenedor para el comportamiento; Medición para la decisión de no usar Core ML. |
| Recortar personas u objetos en imagen o video | Neural Engine o GPU, a elección de Vision | `VNGenerateForegroundInstanceMaskRequest`, `VNGeneratePersonSegmentationRequest` en Swift | Oficial. `VNGenerateForegroundInstanceMaskRequest` corre en [ANE, GPU]. No instalar modelos de Python para esto. |
| Láminas de carrusel (Chrome sin ventana, captura 2×) | CPU con `--disable-gpu` | Mantener el flag | Medición en el piloto: la CPU ganó y la GPU dio diferencias de suavizado. Otro equipo puede dar otro resultado. |
| Fotos HEIC a JPG, miniaturas | `sips` (Core Image) o PIL | Liviano: no optimizar | Criterio. |

## 3. QoS: trabajo de fondo

`taskpolicy -c utility <comando>` (o `background`, o `maintenance`) ejecuta un comando con ese tope de QoS; los
hijos lo heredan. Útil para lotes que no deben competir con lo que el usuario está haciendo: el sistema decide
dinámicamente cuándo usar núcleos de rendimiento y de eficiencia. Verificado con `man taskpolicy` en el piloto.
Para un render con prisa no se usa: el QoS bajo lo ralentiza a propósito.

## 4. Estado térmico y energía

- `serious` o `critical`: el sistema ya está limitando CPU y GPU. `perfil.py` recomienda la mitad de la
  concurrencia (renders en paralelo y `--concurrency`). No es una cifra medida: es un freno de seguridad.
- Modo de bajo consumo activo: macOS limita el rendimiento. Se avisa; la decisión de apagarlo es del usuario.

## 5. Huella del equipo y datos propios

- Huella = hash corto de SO (nombre, sin versión) + arquitectura + `machdep.cpu.brand_string` + `hw.memsize` +
  `hw.perflevel*` (nombre, núcleos físicos y lógicos, `cpusperl2`). No incluye la versión del SO a propósito:
  una actualización menor no debe borrar lo medido. Si una actualización cambia el comportamiento de una
  herramienta, se vuelve a medir con `medir.py` y `--registrar`.
- Datos: `~/.local/share/rendimiento-equipo/<huella>/` (respeta `XDG_DATA_HOME`). Contiene `mediciones.md`
  (bitácora), `perfil-medido.json` (lo que gana al calcular) y `estado-memoria.json` (muestras de swap).
- No hay ruta oficial para datos de una skill fuera de un plugin; es una convención de esta skill.
- Lo medido se invalida por cambio de huella, no por fecha.

## 6. Swift

`scripts/capacidades_macos.swift` se ejecuta con `swift` (tarda ~1 s; necesita Xcode o las Command Line Tools).
Imprime un JSON con Metal, VideoToolbox, Neural Engine, estado térmico y modo de bajo consumo. Cada bloque falla
por separado y deja su motivo en `avisos`.

Si falta `swift`: `diagnosticar.py` sigue con sysctl, memoria, GPU por `system_profiler` y herramientas, y avisa
qué faltó. `perfil.py` entonces usa el detector de ffmpeg como respaldo y deja un aviso; `-allow_sw 0` hace que
ffmpeg falle en vez de caer a CPU sin avisar. Para instalarlo: `xcode-select --install`.
