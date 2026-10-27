# Fuentes y nivel de evidencia

Niveles: **Oficial** (documentación del fabricante o del proyecto), **Mantenedor** (issue, discusión o respuesta
de un mantenedor, o guía de la comunidad reconocida), **Medición** (hecha en un equipo concreto; vive en
`~/.local/share/rendimiento-equipo/<huella>/mediciones.md`), **Criterio** (decisión práctica sin fuente directa).

«HTTP 200 (27/10/2026)» significa que la página existe; no que se haya releído entera. Las afirmaciones sobre
cada herramienta vienen de la síntesis de investigación que originó la skill y, donde se indica, de una
comprobación local (`--help`, `man`, ejecución).

## Cómo escribir skills

| Fuente | Nivel | Para qué se usó |
|---|---|---|
| https://agentskills.io/specification (HTTP 200) | Oficial | Formato de `name` y `description` (≤1.024 caracteres), estructura de carpetas |
| https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices (HTTP 200) | Oficial | Revelación progresiva, un valor por defecto, evals |
| https://learn.chatgpt.com/docs/build-skills (HTTP 200) | Oficial | Portabilidad con Codex (`~/.agents/skills/`) |
| https://code.claude.com/docs/en/context-window (HTTP 200) | Oficial | Tras compactar solo se reinyectan los primeros ~5.000 tokens: lo esencial va arriba |
| https://agentskills.io/skill-creation/using-scripts.md (HTTP 200) | Oficial | Scripts sin interacción, `--help`, JSON a stdout, errores accionables, idempotentes |
| https://agentskills.io/skill-creation/evaluating-skills.md | Oficial | Formato de `evals/evals.json` (`skill_name`, `evals[]` con `prompt`, `expected_output`, `assertions`). Leído al construir |
| https://agentskills.io/skill-creation/optimizing-descriptions.md | Oficial | Formato de consultas de disparo (`query`, `should_trigger`); ~20 consultas, mitad negativas. Leído al construir |
| https://code.claude.com/docs/en/sub-agents (HTTP 200) | Oficial | Los subagentes no heredan skills ni contexto |

## Hardware Apple

| Fuente | Nivel | Para qué se usó |
|---|---|---|
| https://developer.apple.com/documentation/apple-silicon/addressing-architectural-differences-in-your-macos-code (HTTP 200) | Oficial | Consultar capacidades en tiempo de ejecución; niveles de CPU |
| https://developer.apple.com/documentation/apple-silicon/porting-your-metal-code-to-apple-silicon (HTTP 200) | Oficial | Metal: memoria unificada, tamaños recomendados |
| https://developer.apple.com/documentation/apple-silicon/tuning-your-code-s-performance-for-apple-silicon (HTTP 200) | Oficial | QoS y reparto entre núcleos de rendimiento y de eficiencia |
| WWDC20 sesiones 10009 y 10010 | Oficial | HDR a SDR con AVFoundation y `AVAssetExportSession` |
| `man taskpolicy`, `man memory_pressure`, `sysctl`, `system_profiler` en el equipo piloto | Oficial (local) | Opciones de QoS; advertencia sobre `-l` y `-p`; claves de sysctl |
| APIs de Swift: `MTLDevice`, `VTCopyVideoEncoderList`, `VTIsHardwareDecodeSupported`, `MLComputeDevice`, `ProcessInfo.thermalState` | Oficial | Ejecutadas en el piloto desde `capacidades_macos.swift` |

## Herramientas

| Fuente | Nivel | Para qué se usó |
|---|---|---|
| https://www.remotion.dev/docs/hardware-acceleration (HTTP 200) | Oficial | `--hardware-acceleration`, `required`, bitrate, efecto de `crf` |
| https://www.remotion.dev/docs/cli/render (HTTP 200) | Oficial | Opciones del render; comprobadas también con `remotion render --help` (4.0.537) |
| https://www.remotion.dev/docs/offthreadvideo (HTTP 200) | Oficial | Caché de OffthreadVideo, `transparent` |
| https://www.remotion.dev/docs/cli/benchmark (HTTP 200) | Oficial | `remotion benchmark --concurrencies` |
| https://www.remotion.dev/docs/gl-options (HTTP 200) | Oficial | `--gl=angle`; fuga de memoria conocida |
| https://github.com/ggml-org/whisper.cpp (HTTP 200) | Mantenedor | Metal, flash attention, Core ML |
| https://github.com/ggml-org/whisper.cpp/tree/master/examples/server (HTTP 200) | Mantenedor | Servidor HTTP; opciones comprobadas además con `--help` del binario del piloto |
| https://ffmpeg.org/ffmpeg-codecs.html (HTTP 200) | Oficial | Opciones de los codificadores; `-allow_sw` comprobado con `ffmpeg -h encoder=h264_videotoolbox` |
| https://trac.ffmpeg.org/wiki/HWAccelIntro (HTTP 200) | Mantenedor | Aceleración por hardware en ffmpeg (guía genérica: no coincide con la medición del piloto en decodificación) |

Afirmaciones sin enlace propio en los insumos (nivel indicado):

- `h264_videotoolbox -q:v 70` ≈ x264 crf 22: Mantenedor, fuente única, no verificada.
- Mutex del servidor de whisper.cpp que serializa peticiones: Mantenedor.
- Reporte de colores erróneos de `scale_vt`: Mantenedor (ticket de ffmpeg), no releído.
- Receta de tonemap `zscale`/`tonemap`: comunidad (FFmpeg wiki); ejecuta en el ffmpeg 6.0 del piloto, aspecto visual sin revisar.

## Medición y criterio de esta skill

- Umbral de ganador claro (≥15 % mejor y diferencia visual media <2/255): Criterio.
- Fracciones de concurrencia y de caché de Remotion (0,6; 0,9; 0,25): Criterio, heredadas de una regla práctica
  anterior. Se sustituyen con lo medido.
- Umbral de «swap creciendo» (256 MB en 1 h): Criterio.
- Cifras del equipo piloto: Medición, en su `mediciones.md` local. No se copian a la skill.
