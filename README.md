# rendimiento-equipo

Una skill para Claude Code y Codex que mira el equipo antes de lanzar trabajo pesado (video, transcripción,
recortes, lotes, agentes en paralelo) y manda cada tarea al motor que mejor la hace: núcleos de rendimiento o de
eficiencia, GPU, Neural Engine o motor de video. Guarda lo que mide en cada máquina y lo usa por encima de las
recetas genéricas.

Piloto: macOS en Apple Silicon. En Windows ya diagnostica y mide, pero no recomienda nada hasta tener mediciones
de equipos reales ([cómo ayudar](#windows)).

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
En Windows describe y mide el equipo, sin recomendar todavía. Si solo chateas con una IA en el navegador, no hace
nada.

### Desde las apps (Claude Desktop o Codex)

Abre Claude Desktop en la pestaña Code, o la app de Codex. Tienen que trabajar en tu equipo: el chat normal de
Claude y las tareas en la nube de Codex no lo ven. Pega este mensaje y acepta cuando el agente te pida permiso:

```text
Instala la skill rendimiento-equipo. Clona https://github.com/sebaslobo22/rendimiento-equipo en la carpeta rendimiento-equipo de mi usuario, muéstrame qué hará el instalador en modo de prueba (./install.sh --prueba en Mac, .\install.ps1 -Prueba en Windows) y, si te digo que sí, ejecútalo.
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

### Desde PowerShell, en Windows

```powershell
git clone https://github.com/sebaslobo22/rendimiento-equipo.git $HOME\rendimiento-equipo
cd $HOME\rendimiento-equipo
.\install.ps1
```

`install.ps1` hace lo mismo con *junctions* en `%USERPROFILE%\.claude\skills` y `%USERPROFILE%\.agents\skills`,
sin pedir permisos de administrador. Opciones: `-Destino`, `-Prueba`, `-Desinstalar`. Si Windows bloquea el
script, usa `powershell -ExecutionPolicy Bypass -File .\install.ps1`. Windows no trae Python: instálalo desde
python.org o con `winget install Python.Python.3.12`. Para medir video hace falta ffmpeg
(`winget install Gyan.FFmpeg`).

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
| `scripts/perfil.py --renders N --formato texto` | Recomendaciones para N renders en paralelo, frenos activos, qué trae la arquitectura de tu chip y qué hace la skill con cada cosa, y un bloque listo para pegar en el encargo de cada subagente. |
| `scripts/medir.py codificar\|decodificar\|remotion` | Compara dos métodos en tu equipo. Con `--registrar` anota al ganador si mejora al menos un 15 % sin diferencia visual (menos de 2/255). |
| `scripts/medir.py voz --audio <archivo> --texto <lo que dice>` | Mide los modelos de dictado de OpenWhispr descargados (Whisper, Parakeet, Orukeet, Cohere): tiempo, memoria y porcentaje de error en tu equipo. |
| `scripts/medir.py paralelo` | Cuántas codificaciones por hardware rinden a la vez. Los chips Max y Ultra traen 2 y 4 motores de video, y ninguna API lo dice. |

### Cada generación, a fondo

La skill tiene en cuenta los saltos de arquitectura de cada generación, de M1 a M6. Por ejemplo, el ProRes por
hardware, la decodificación AV1 desde M3, los varios motores de video de los Max y Ultra, y los Neural
Accelerators de la GPU desde M5.

Decide por lo que el equipo declara, no por el nombre del chip. Por eso un chip que todavía no existe recibe las
reglas que le correspondan, y si trae algo desconocido, la skill pide medirlo. El detalle, con fuentes, está en
[`references/arquitectura.md`](skills/rendimiento-equipo/references/arquitectura.md).
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
| Windows 10 y 11 | Diagnóstico y mediciones. Sin recomendaciones hasta medir equipos reales. Probado en las máquinas Windows de GitHub, que no tienen tarjeta gráfica. |
| Linux | Sin soporte. |

## Windows

Para recomendar en Windows faltan mediciones en equipos reales: al menos uno con tarjeta NVIDIA, uno con gráfica
Intel y uno con AMD. Si tienes uno y quieres ayudar, instala la skill y pega esto en Claude Code o Codex, en la
carpeta de un video tuyo de unos 30 s:

```text
Usa la skill rendimiento-equipo. Corre perfil.py --formato texto, después medir.py codificar y medir.py decodificar con mi video y --registrar, y muéstrame el resultado y el archivo mediciones.md.
```

Comparte la salida de `perfil.py` y `mediciones.md`. El detalle de qué lee y cómo está en
[`references/windows.md`](skills/rendimiento-equipo/references/windows.md).

## Estructura

```
skills/rendimiento-equipo/
  SKILL.md                 lo que lee el agente (67 líneas, lo esencial arriba)
  scripts/                 diagnosticar, perfil, medir, limpiar, arquitectura, la consulta en Swift y plataforma_windows
  references/              macos, arquitectura, ffmpeg, remotion, whisper, memoria, agentes, windows, fuentes
  evals/evals.json         consultas de disparo y casos de comportamiento
  assets/                  perfil.ejemplo.json y chips_apple.json (tabla de Apple de referencia)
install.sh                 instalador para macOS
install.ps1                instalador para Windows
pruebas/                   pruebas de humo que corre GitHub Actions en Windows y macOS
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
per-machine measurements outside the repo. Pilot: macOS on Apple Silicon. On Windows it diagnoses and measures,
but makes no recommendations until real machines are measured. The skill and its docs are in Spanish.
