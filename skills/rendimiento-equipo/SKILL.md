---
name: rendimiento-equipo
description: Diagnostica el equipo donde corre (CPU por niveles, GPU, Neural Engine, motores de video, memoria, estado térmico) y recomienda cómo ejecutar trabajo pesado en él, usando lo medido en ese equipo por encima de lo genérico. Cubre video con ffmpeg y Remotion, transcripción local con whisper.cpp, segmentación con Vision, lotes y agentes en paralelo. Úsala antes de lanzar renders, transcripciones, conversiones, recortes o procesos en lote, y al escribir el encargo de un subagente que los vaya a hacer, aunque nadie hable de rendimiento. Piloto: macOS en Apple Silicon. En Windows diagnostica y mide, pero no recomienda nada hasta tener mediciones de equipos reales. No la uses para escribir contenido, diseño visual ni el método editorial de carruseles y reels (eso es carrusel-editorial-lobo y expediente-lobo).
---

# Rendimiento del equipo

**Principio:** cada tarea va al motor que mejor la hace, se mide antes de cambiar un método, y lo medido en este
equipo gana a lo genérico. Las cifras de cada máquina no viven aquí: están en
`~/.local/share/rendimiento-equipo/<huella>/` (`mediciones.md`, `perfil-medido.json`). Si cambias de equipo, la
huella cambia y se empieza de cero sin heredar nada falso.

## Flujo

Rutas relativas a la carpeta de esta skill. Necesita Python 3; no instala nada y solo usa la red con `calibrar.py --descargar`, con permiso. En Windows el
comando suele ser `python` o `py -3` en lugar de `python3`, y el paso 2 no recomienda: lee `references/windows.md`.

0. **Calibración.** Si `perfil.py` dice «calibrar» (equipo sin calibrar, OpenWhispr nuevo o con modelos nuevos),
   corre `python3 scripts/calibrar.py`: mide dictado y video con lo que ya hay, sin descargar nada, y guarda el
   punto dulce de este equipo. `--plan` dice qué mediría. `--descargar` baja los candidatos de dictado que faltan
   a una carpeta de la skill (nunca a OpenWhispr) y los borra al terminar: **pide un sí antes**, son cientos de MB
   o varios GB. Con `--audio`/`--texto` (tu voz) y `--video` (un video real) el resultado vale más; un clip
   sintético no se guarda porque engaña.
1. `python3 scripts/diagnosticar.py` (con `--proyecto <ruta>` si hay un proyecto Remotion). Entrega un JSON del
   equipo. Si falta Swift sigue sin Metal, video, Neural Engine y térmico, y lo dice en `avisos`.
2. `python3 scripts/perfil.py --renders N --formato texto`, con N = cuántos renders irán en paralelo. Entrega
   recomendaciones, los frenos activos y un **bloque para subagentes** ya relleno.
3. Aplica las recomendaciones y pega el bloque en cada encargo a un subagente (no heredan skills ni contexto).
4. Si vas a cambiar un método: `python3 scripts/medir.py codificar|decodificar|remotion|paralelo|voz ... --registrar`, con nadie
   más renderizando. Solo actualiza el perfil con un ganador claro (≥15 % mejor y diferencia visual <2/255).
5. Al terminar: `python3 scripts/limpiar.py` (solo muestra) y luego `python3 scripts/limpiar.py --aplicar`.

`--help` en cualquier script explica sus opciones. Los códigos de salida: 0 bien, 2 argumentos inválidos.

## Reglas que más se rompen

1. No fijes valores de hardware: consúltalos. Otro chip trae otros núcleos, niveles, motores y nombres. Las
   capacidades de cada generación se deciden por lo detectado, no por el nombre del chip (`references/arquitectura.md`).
2. `memory_pressure` sin argumentos: con `-l` o `-p` aplica presión real y altera lo que quieres medir.
3. Mira la presión y si el swap crece, no la memoria libre: Apple dice que «libre» no es una estadística útil.
4. `--crf` desactiva el hardware en Remotion: cae a libx264 sin avisar. Con hardware se usa `--video-bitrate`.
5. Un solo Whisper: el servidor serializa las peticiones, así que el segundo no suma velocidad y duplica el modelo.
6. Caché de OffthreadVideo por render: por defecto es el 50 % de la memoria disponible en cada uno y tres se pasan de la RAM.
7. ffmpeg con `-nostdin`, `-allow_sw 0` y bitrate explícito: que falle antes de caer a CPU sin avisar.
8. HDR a SDR una sola vez por tramo y guardado: es el paso sin ruta por hardware validada.
9. Más concurrencia no es más velocidad: demasiada da «Target closed» o SIGKILL; sigue el número de `perfil.py`.
10. Lo no medido no se adopta: `--gl` solo entra al comando si el perfil medido lo trae, y se mide sin otros renders.
11. Con un freno activo (presión ≥2, swap creciendo, térmico serious o critical) se serializa o se baja a la mitad.
12. Nunca tocar los procesos protegidos (el whisper-server de OpenWhispr usa `--model` y `--host`); cada agente
    apaga por PID solo lo que lanzó.
13. Más codificaciones por hardware a la vez no suman con un solo motor de video: respeta el máximo de `perfil.py`
    (sección ARQUITECTURA) y, si no está medido, mídelo con `medir.py paralelo`.

## Cuándo leer qué

| Si necesitas... | Lee |
|---|---|
| Saber qué API o comando da cada capacidad, qué tarea va a qué motor, QoS, térmico | `references/macos.md` |
| Qué trae cada generación (M1 a M6), qué herramienta lo usa y cómo se detecta | `references/arquitectura.md` |
| Argumentos de ffmpeg, bitrates, HDR a SDR, qué ffmpeg usar | `references/ffmpeg.md` |
| Flags de Remotion, concurrencia, caché, `--gl`, cómo medirlo | `references/remotion.md` |
| Lanzar, reutilizar o apagar el servidor de transcripción; Core ML o Metal; qué modelo de dictado conviene | `references/whisper.md` |
| Entender presión de memoria, swap y los frenos | `references/memoria.md` |
| Escribir encargos para subagentes, repartir trabajo, verificar, limpiar | `references/agentes.md` |
| Trabajar en Windows (diagnóstico y mediciones; sin recomendaciones todavía) | `references/windows.md` |
| Ver de dónde sale cada afirmación y qué tan fuerte es | `references/fuentes.md` |
| Formato del perfil medido que crea `medir.py` | `assets/perfil.ejemplo.json` |
| Probar la skill (consultas de disparo y casos de comportamiento) | `evals/evals.json` |

## Cuando algo no encaja

- Sin Swift (`xcode-select --install`): el diagnóstico sigue incompleto y `perfil.py` usa ffmpeg como respaldo,
  con aviso. Con `-allow_sw 0` ffmpeg falla en vez de caer a CPU sin avisar.
- Sin perfil medido para esta huella: todo viene de fórmula y `perfil.py` lo dice. Se corrige midiendo.
- Windows: `diagnosticar.py` describe el equipo y prueba qué codificadores por hardware abren; `medir.py` compara
  codificar y decodificar; `perfil.py` resume sin recomendar y da un bloque para subagentes con las reglas que no
  dependen del equipo. `limpiar.py` solo muestra. Remotion no se mide todavía.
- Otro sistema (Linux): `diagnosticar.py` responde «sin soporte medido todavía» y no hay recomendaciones.
- Un proceso que `limpiar.py` marca como protegido o en uso no se toca con ninguna opción, ni con `--pid`.
- Para registrar una decisión a mano, edita `perfil-medido.json` con el formato de `assets/perfil.ejemplo.json`
  y anota el porqué en `mediciones.md`.
