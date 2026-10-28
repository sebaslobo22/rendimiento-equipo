# rendimiento-equipo

Una skill para Claude Code y Codex que mira el equipo antes de lanzar trabajo pesado (video, transcripción,
recortes, lotes, agentes en paralelo) y manda cada tarea al motor que mejor la hace: núcleos de rendimiento o de
eficiencia, GPU, Neural Engine o motor de video. Guarda lo que mide en cada máquina y lo usa por encima de las
recetas genéricas.

Piloto: macOS en Apple Silicon. Windows queda para una segunda fase, sin soporte medido todavía.

Página: https://sebaslobo22.github.io/rendimiento-equipo/ (fuente en [`docs/index.html`](docs/index.html))

## Por qué la hice

El 27.10.2026, renderizando videos para mi marca personal, medí que mi Mac (M4 Pro, 24 GB) codificaba el video en
la CPU mientras el motor de video estaba ocioso, y que había cuatro servidores de Whisper vivos con 9 GB de swap.
Corregí cada cosa midiendo y dejé el método en esta skill, para que el agente lo aplique antes de empezar y no
después del problema.

## Lo que midió en el Mac piloto

| Tarea | Antes | Ahora |
|---|---|---|
| Codificar 15 s de video vertical (HEVC de iPhone a H.264 1080×1920) | 22,1 s en la CPU, 263 s de CPU | 4,1 s en el motor de video, 5 s de CPU |
| Decodificar 30 s de HEVC | 4,4–5,4 s, 35–38 s de CPU | 2,4–2,6 s, 3,3 s de CPU |
| 4 láminas de carrusel a 2× con Chrome sin ventana | 15,3 s con GPU | 11,8 s con `--disable-gpu` |

Son cifras de un solo equipo. En el tuyo, `medir.py` las vuelve a medir antes de cambiar nada.

## Instalar

Te sirve si usas Claude Code o Codex en una Mac con Apple Silicon para video, audio, Remotion o lotes de archivos.
Si solo chateas con una IA en el navegador, no hace nada.

### Desde las apps (Claude Desktop o Codex)

Abre Claude Desktop en la pestaña Code, o la app de Codex. Tienen que trabajar en tu Mac: el chat normal de Claude
y las tareas en la nube de Codex no ven tu equipo. Pega este mensaje y acepta cuando el agente te pida permiso:

```text
Instala la skill rendimiento-equipo. Clona https://github.com/sebaslobo22/rendimiento-equipo en ~/rendimiento-equipo, muéstrame qué hará ./install.sh --prueba y, si te digo que sí, ejecuta ./install.sh.
```

Después abre una conversación nueva y pide lo de siempre, por ejemplo «convierte estos 3 videos a vertical». Para
actualizarla, pídele «Actualiza la skill rendimiento-equipo con git pull en ~/rendimiento-equipo».

### Desde la terminal

```bash
git clone https://github.com/sebaslobo22/rendimiento-equipo.git ~/rendimiento-equipo
cd ~/rendimiento-equipo
./install.sh
```

`install.sh` enlaza `skills/rendimiento-equipo` en `~/.claude/skills/` (Claude Code) y en `~/.agents/skills/`
(Codex). No copia archivos, no instala dependencias y no usa la red. Si ya había algo con ese nombre, lo aparta en
`.respaldos/` antes de enlazar. Para actualizar basta `git pull`.

| Opción | Qué hace |
|---|---|
| `--destino ambos\|claude\|agentes` | Dónde enlazar. Por defecto, en los dos. |
| `--prueba` | Muestra lo que haría sin cambiar nada. |
| `--desinstalar` | Quita solo los enlaces que apuntan a este repositorio. |

Requisitos: Python 3. Para el diagnóstico completo (Metal, motores de video, Neural Engine y estado térmico) hacen
falta las herramientas de línea de comandos de Xcode (`xcode-select --install`). Sin ellas funciona con menos
datos y lo avisa.

## Primeros pasos

No vas a notar nada: la skill trabaja por detrás cuando le pides al agente algo pesado. Para verla en acción, pega
una de estas pruebas en Claude Code o Codex:

| Prueba | Qué pasa |
|---|---|
| «Usa la skill rendimiento-equipo y dime qué tiene mi Mac y qué recomienda.» | Te dice tu chip, sus núcleos y tu memoria, qué parte del chip conviene para video, audio y renders, y si la Mac va justa de memoria o está caliente. |
| «Convierte este video a vertical 1080×1920.» | Lo hace con el motor de video y no con la CPU. En el Mac piloto, 15 s de video pasaron de 22,1 s a 4,1 s. Necesita ffmpeg: si falta, el agente te avisa. |
| «Renderiza estos 3 videos en paralelo sin que se cuelgue la Mac.» | Reparte los hilos y la memoria entre los renders y deja un solo servidor de Whisper. |

Si no le pides al agente nada de eso, la skill no aparece: está pensada para cuando la Mac trabaja duro.

## Usar

La skill se activa sola cuando le pides al agente un render, una transcripción, una conversión o un lote. Los
scripts también se corren a mano desde `skills/rendimiento-equipo/`:

| Script | Qué hace |
|---|---|
| `scripts/diagnosticar.py` | JSON del equipo: CPU por niveles, memoria y presión, GPU y familia Metal, codificadores y decodificadores por hardware, Neural Engine, estado térmico y procesos pesados vivos. |
| `scripts/perfil.py --renders N --formato texto` | Recomendaciones para N renders en paralelo, frenos activos y un bloque listo para pegar en el encargo de cada subagente. |
| `scripts/medir.py codificar\|decodificar\|remotion` | Compara dos métodos en tu equipo. Con `--registrar` anota al ganador si mejora al menos un 15 % sin diferencia visual (menos de 2/255). |
| `scripts/limpiar.py` | Lista los procesos que lanzaron los agentes y siguen vivos. Con `--aplicar` los apaga por PID. Nunca toca los protegidos ni los que están en uso. |

Todos aceptan `--help` y devuelven 0 si todo fue bien o 2 si los argumentos no sirven.

## Lo medido gana a lo genérico

Cada equipo tiene una huella: un hash corto del sistema, la arquitectura, el chip, la memoria y los niveles de
núcleos. Lo medido vive fuera del repositorio, en `~/.local/share/rendimiento-equipo/<huella>/`
(`mediciones.md` y `perfil-medido.json`). Si cambias de equipo cambia la huella y la skill empieza de cero, sin
heredar cifras de otra máquina. Una actualización menor del sistema no cambia la huella.

## Frenos

Antes de lanzar, `perfil.py` revisa la presión de memoria, si el swap está creciendo, el estado térmico y el modo
de bajo consumo. Con la presión en aviso o crítica, el swap creciendo o el térmico en *serious* o *critical*,
recomienda serializar o bajar la concurrencia a la mitad.

## Compatibilidad

| Sistema | Estado |
|---|---|
| macOS en Apple Silicon | Diagnóstico completo. Medido en un M4 Pro de 24 GB. |
| macOS sin herramientas de Xcode | Diagnóstico parcial, con aviso. |
| Windows | Segunda fase. Responde «sin soporte medido todavía». |
| Linux | Sin soporte. |

## Estructura

```
skills/rendimiento-equipo/
  SKILL.md                 lo que lee el agente (67 líneas, lo esencial arriba)
  scripts/                 diagnosticar, perfil, medir, limpiar y la consulta en Swift
  references/              macos, ffmpeg, remotion, whisper, memoria, agentes, windows, fuentes
  evals/evals.json         consultas de disparo y casos de comportamiento
  assets/perfil.ejemplo.json
install.sh
docs/index.html            la página del proyecto
```

Los casos de `evals/evals.json` se escribieron en el Mac piloto y algunos usan sus rutas.

## Fuentes

Cada afirmación de la skill está en `references/fuentes.md` con su nivel de evidencia: oficial (Apple, Remotion,
ffmpeg, whisper.cpp, Anthropic, OpenAI), del mantenedor, medida en el equipo o criterio propio.

## Licencia

MIT. Ver [LICENSE](LICENSE).

---

**In English.** A skill for Claude Code and Codex that inspects the machine before heavy local work (video encoding,
transcription, segmentation, batches, parallel agents), routes each task to the engine that does it best, and keeps
per-machine measurements outside the repo. Pilot: macOS on Apple Silicon. The skill and its docs are in Spanish.
