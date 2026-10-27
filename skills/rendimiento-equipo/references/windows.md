# Windows (fase 2): sin soporte medido todavía

Esta skill **no tiene** diagnóstico, perfil ni mediciones para Windows. Todo lo de abajo son preguntas por
investigar y medir, no afirmaciones. Hasta que se midan, en Windows se usan los valores por defecto de cada
herramienta y la skill no recomienda nada.

## Qué hacen hoy los scripts en Windows

- `diagnosticar.py` devuelve el SO, la arquitectura, una huella y `"soporte": "sin soporte medido todavía"`. No
  consulta GPU, memoria ni procesos.
- `perfil.py` imprime el mismo aviso y no entrega recomendaciones.
- `medir.py` sale con error 2 y remite aquí. `limpiar.py` no tiene lógica específica de Windows.

## Candidatos a investigar (no verificados)

| Tema | Pregunta abierta | Cómo se mediría |
|---|---|---|
| NVENC (NVIDIA) | ¿Está en el ffmpeg instalado? ¿Gana a libx264 en tiempo y calidad con la fuente real? | `ffmpeg -encoders` buscando el codificador; luego prueba A/B equivalente a `medir.py codificar`. |
| Quick Sync, QSV (Intel) | Igual | Igual |
| AMF (AMD) | Igual | Igual |
| Decodificación por hardware | ¿Qué método de aceleración expone ese ffmpeg y conviene frente a CPU? | `ffmpeg -hwaccels` y prueba A/B de decodificación. |
| Remotion | ¿`--hardware-acceleration` y `--gl` se comportan igual? ¿Qué concurrencia es estable? | `npx remotion benchmark` y prueba A/B de render. |
| whisper.cpp | ¿Qué backend de GPU trae la compilación disponible (CUDA, Vulkan u otro)? | Opciones de `--help` del servidor y prueba de transcripción. |
| Memoria y térmico | ¿Qué equivale a la presión de memoria y al estado térmico? | A investigar; no se asume equivalencia con macOS. |

## Qué hay que construir para cerrar la fase 2

1. Un diagnóstico de Windows que no dependa de nombres de GPU sino de lo que el ffmpeg y los controladores
   realmente exponen.
2. Una prueba A/B por cada fila de la tabla, con el mismo criterio que en macOS (≥15 % más rápido y diferencia
   visual media <2/255).
3. Un perfil medido por huella, igual que en macOS, antes de que `perfil.py` recomiende nada.
4. Anotar en `fuentes.md` cada fuente consultada con su nivel de evidencia.

Mientras tanto, las reglas que no dependen del sistema siguen valiendo: un solo servidor de transcripción,
encargos autosuficientes para subagentes, dos escritores nunca en el mismo archivo, verificar con evidencia y
apagar solo lo propio (ver `agentes.md`).
