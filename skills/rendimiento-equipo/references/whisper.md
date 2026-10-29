# Transcripción local con whisper.cpp

Niveles: Oficial/Mantenedor (whisper.cpp) / Medición / Criterio.

## Qué modelo de dictado usar (punto dulce)

`perfil.py` (sección VOZ) y `scripts/voz.py` recomiendan el modelo local de OpenWhispr para **este equipo**, no
para su chip: cuentan la memoria (tamaño y ancho de banda), si Whisper corre en la GPU o en el procesador, el
freno de memoria y lo medido ahí. El punto dulce es el de menos error en el idioma que dictas entre los que:

1. caben en el 20 % de la memoria del equipo (la mitad con el freno de memoria activo), y
2. transcriben al menos 4 veces el tiempo real en ese equipo (30 s de dictado en menos de 8 s).

Si dos quedan a menos de medio punto de error, gana el que ocupa menos, y luego el más rápido (Criterio).

Qué dato manda, en orden:

- **Lo medido en el equipo** con `medir.py voz --registrar`. Si dos o más modelos se midieron con `--texto` sobre
  el mismo audio, se elige entre ellos por su error medido (el error medido no se mezcla con el publicado). Si un
  modelo sin medir promete menos error en su ficha, la sección VOZ lo lista en «medir también».
- **Lo estimado con el ancho de banda de la memoria**: Whisper en la GPU de Apple relee el modelo por cada
  palabra, así que su velocidad sigue al ancho de banda. Calibrado con Turbo en el M4 Pro (273 GB/s, unas 21 veces
  el tiempo real): un M5 base (153 GB/s) daría unas 12 y Whisper Large en un M1 (68 GB/s) unas 3, por debajo del
  mínimo. Es una estimación marcada como tal; medir la reemplaza.
- **La ficha pública** (`assets/fichas_voz.json`): error en español con su conjunto de prueba y su fuente. Vienen
  de fuentes distintas y son aproximadas entre sí. La única comparación limpia publicada es Parakeet v3 contra
  Orukeet en los mismos clips: 3,22 contra 2,75 % en FLEURS español (autores de Orukeet).

- **El catálogo se lee del OpenWhispr instalado** (`modelRegistryData.json` dentro de `app.asar`, en Mac y en
  Windows). Si la app suma modelos, aparecen solos; sin ficha pública quedan marcados para medir y nunca se les
  inventa una precisión. Sin OpenWhispr, se usa la copia de `assets/fichas_voz.json`.
- **En Windows e Intel**, OpenWhispr corre Whisper en el procesador (CUDA y Vulkan son descargas aparte), así que
  los Whisper de más de 500 MB se descartan por lentos. Parakeet, Orukeet y Cohere corren en el procesador en los
  dos sistemas (sherpa-onnx).
- La skill solo sugiere: el modelo se cambia en OpenWhispr, en Configuración > Conversión de voz a texto > Local.

### Calibrar: que la skill lo encuentre sola

`calibrar.py` hace la búsqueda del punto dulce de punta a punta, en cualquier equipo, sin lista de chips ni de
modelos fija:

1. Lee el catálogo del OpenWhispr instalado y filtra por este equipo (idioma, memoria, velocidad).
2. Mide todo lo útil que ya está descargado, con un audio de prueba en español que lee la voz del sistema
   (`say` en macOS, System.Speech en Windows) o con tu voz (`--audio`, `--texto`; tiene prioridad).
3. Propone los candidatos que faltan: los de menos error público a menos de 1,5 puntos del mejor (hasta 3) y el
   modelo nuevo más liviano que no tenga ficha, porque solo midiéndolo se sabe si gana. Con `--descargar` (y un
   sí del usuario) los baja a `~/.local/share/rendimiento-equipo/modelos-voz/`, los mide y los borra.
4. Con dos o más modelos medidos sobre el mismo audio, el punto dulce sale de lo medido. Las velocidades de los
   no medidos se estiman desde el modelo del mismo motor medido en el equipo (la velocidad baja en proporción al
   tamaño): sirve igual para un chip que salga mañana.
5. Guarda `calibracion.json` con la versión de OpenWhispr y su catálogo. Si cambian, `perfil.py` avisa que toca
   calibrar otra vez.

El instalador ofrece calibrar al terminar. Nunca cambia la configuración de OpenWhispr.

### Medir en tu equipo

```
python3 scripts/medir.py voz --audio tu-voz.m4a --texto lo-que-dices.txt --registrar
```

- Mide **todos** los modelos descargados: Whisper con whisper-server y Parakeet, Orukeet y Cohere con
  `sherpa-onnx-ws`, cada uno en un servidor propio (puerto 88xx) que se apaga al terminar. Nunca toca el de
  OpenWhispr. sherpa-onnx se lanza con los argumentos de OpenWhispr (`parakeetWsServer.js`): `--encoder`,
  `--decoder`, `--joiner`, `--tokens`, `--model-type` según el catálogo (Cohere usa `--cohere-transcribe-*`),
  `--num-threads` = mín(4, 75 % de los núcleos) y `--num-work-threads=3`. El audio va por WebSocket:
  `[int32 tasa][int32 bytes][float32…]`, luego el texto «Done».
- Una pasada de calentamiento que no cuenta y luego 3 repeticiones (`--repeticiones`).
- `--backends metal,cpu` compara Whisper con Metal y en el procesador (`-ng`).
- El error normaliza tildes, puntuación, cifras («12» = «doce», hasta 999.999) y «%» = «por ciento»: así no
  castiga a un modelo por escribir números.
- Del registro de whisper-server lee `has tensor = true|false`: si la compilación usa los Neural Accelerators de
  M5 en adelante. Se guarda en el perfil y la sección ARQUITECTURA lo dice.
- Cada medición guarda un `audio_id` (huella del audio): solo se comparan errores medidos sobre el mismo audio.

### Medido

- **M4 Pro piloto** (29/10/2026, 12 s de voz sintética, OpenWhispr 1.11.0): Whisper Turbo con Metal 0,53 s (23
  veces el tiempo real, 1,8 GB, 6 % de error: «Parakeet» lo escribió «Para KED»); en el procesador 7,9 s. Metal
  fue 15 veces más rápido. `has tensor = false`, lo esperado en un M4.
- **MacBook Pro M5 base, 16 GB** (informe del usuario, OpenWhispr 1.10.4): el whisper-server venía con la API de
  tensores apagada (`has tensor = false`), así que Whisper no usaba los Neural Accelerators. Parakeet transcribió
  con 2,3 % de error contra cerca de 6 % de Whisper, en el procesador y con menos memoria.

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
