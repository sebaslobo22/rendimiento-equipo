# Transcripción local con whisper.cpp

Niveles: Oficial/Mantenedor (whisper.cpp) / Medición / Criterio.

## Qué modelo de dictado usar (punto dulce)

`perfil.py` (sección VOZ) y `scripts/voz.py` recomiendan el modelo local de OpenWhispr con menos error en el
idioma que dictas, entre los que caben en el 20 % de la memoria del equipo (la mitad con el freno de memoria
activo). Si dos quedan a menos de medio punto de error, gana el que ocupa menos (Criterio).

- **El catálogo se lee del OpenWhispr instalado** (`modelRegistryData.json` dentro de `app.asar`, en Mac y en
  Windows). Si la app suma modelos, aparecen solos; sin ficha pública quedan marcados para medir y nunca se les
  inventa una precisión. Sin OpenWhispr, se usa la copia de `assets/fichas_voz.json`.
- **Las fichas** (`assets/fichas_voz.json`) traen el error en español con su conjunto de prueba y su fuente. Vienen
  de fuentes distintas (artículo de Whisper, NVIDIA, Open ASR Leaderboard, autores de Orukeet) y son aproximadas
  entre sí. La única comparación limpia es Parakeet v3 contra Orukeet en los mismos clips: 3,22 contra 2,75 % en
  FLEURS español, publicada por los autores de Orukeet.
- **En Windows e Intel**, OpenWhispr corre Whisper en el procesador (CUDA y Vulkan son descargas aparte), así que
  los Whisper de más de 500 MB se descartan por lentos. Parakeet, Orukeet y Cohere corren en el procesador en los
  dos sistemas (sherpa-onnx).
- **Medir en tu equipo:** `medir.py voz --audio tu-voz.m4a --texto lo-que-dices.txt --registrar` transcribe con
  cada modelo Whisper descargado en un servidor propio (puerto 88xx; nunca toca el de OpenWhispr) y guarda tiempo,
  memoria y porcentaje de error. Los modelos de sherpa-onnx todavía no se pueden medir desde aquí.
- **Medido en el M4 Pro piloto** (29/10/2026, 15 s de voz sintética en español): Whisper Turbo transcribió en
  0,75 s (20 veces el tiempo real) con 1,8 GB de memoria y 10 % de palabras erradas («Mac» lo escribió «máquina»).
- La skill solo sugiere: el modelo se cambia en OpenWhispr, en Configuración > Conversión de voz a texto > Local.

## Un solo servidor

- El servidor serializa las peticiones con un mutex (Mantenedor): un segundo servidor no suma velocidad y
  duplica el modelo en memoria. Por eso: **un solo servidor para todos los agentes**.
- Antes de lanzar uno, mira si ya hay uno propio vivo: `python3 scripts/perfil.py` lo indica (`reutilizar_propio`).
- Si varios agentes necesitan transcribir, se calculan los tiempos por palabra de todo en un solo paso y se guardan
  en archivos. Los agentes leen archivos; no levantan servidores.
- Cada servidor lanzado por un agente usa `-m <modelo> --port 88xx` y se apaga por su PID al terminar. El servidor
  de la app OpenWhispr usa `--model ... --host ...`, es de larga duración y no se toca.

## Backend

- whisper.cpp usa Metal con flash attention por defecto en Apple Silicon (Mantenedor). El registro del servidor
  dice si usa GPU. Para confirmar en tu equipo: arrancar el servidor y mirar su salida.
- Con flash attention, el DTW de tiempos por palabra se desactiva (Mantenedor). Si hacen falta tiempos por palabra
  de DTW, es una decisión aparte (sin flash attention); lo que hoy funciona en el piloto se mide por otra vía.
- Core ML / Neural Engine: «3×» frente a CPU sola, no frente a Metal (Mantenedor). Pide generar el modelo con
  coremltools. `diagnosticar.py` informa si hay un `*-encoder.mlmodelc` junto al modelo
  (`encoder_coreml`). La decisión del piloto es seguir con Metal (Criterio); se cambia solo con una medición en
  `perfil-medido.json` (`whisper.backend`).
- `diagnosticar.py` mira qué bibliotecas `libggml-*.dylib` hay junto al binario (metal, blas, cpu, rpc) para saber
  qué backends trae esa compilación.

## Opciones del servidor (comprobadas con `--help` del servidor de OpenWhispr)

`-m/--model`, `--host`, `--port`, `-t/--threads` (por defecto 4), `-l/--language` (`auto` detecta), `-fa/--flash-attn`
(activo por defecto), `-nfa/--no-flash-attn`, `-ng/--no-gpu`, `--convert` (convierte el audio a WAV y exige ffmpeg
en el servidor), `--vad`, `--inference-path` (por defecto `/inference`).
Otra compilación puede traer opciones distintas: ante la duda, `<servidor> --help`.

## Convención de puertos

`perfil.py` propone el primer puerto libre de 8801 a 8899. Ese patrón (`-m` y `--port 88xx`) es el que
`limpiar.py` reconoce como servidor de agente. Si lanzas un servidor con otras opciones, `limpiar.py` lo
clasifica como «en uso» y no lo apaga.

## Higiene

- Al terminar el lote: apagar el servidor propio por PID (`python3 scripts/limpiar.py --aplicar --pid <PID>`).
- Borrar los WAV intermedios de la carpeta temporal cuando ya no sirvan.
- El modelo grande ocupa memoria mientras el servidor vive; con presión de memoria ≥2, no lanzar uno nuevo.
