# Memoria: presión, swap y qué hacer

Niveles: Oficial (Apple) / Medición / Criterio.

## Cómo mirarla

- `memory_pressure` **sin argumentos**. Con `-l` o `-p` aplica presión real al sistema (Oficial: `man memory_pressure`
  la describe como herramienta para aplicar o simular presión de memoria): un diagnóstico no debe alterar lo que mide. Se lee la línea
  «System-wide memory free percentage».
- `sysctl vm.swapusage` (total, usado, libre) y `sysctl kern.memorystatus_vm_pressure_level`:
  1 = normal, 2 = aviso, 4 = crítica.
- Apple: la memoria libre «no es una estadística útil». Lo que importa es la presión y que el swap crezca
  durante el trabajo. Por eso `perfil.py` frena por presión ≥2 o swap creciendo, **no** por un porcentaje libre.
  (La skill anterior usaba «menos del 30 % libre, esperar»; se descartó por esta razón.)
- El swap de macOS es dinámico: el «total» sube y baja. Compara siempre el usado, no el porcentaje.

## «Swap creciendo»

Un solo diagnóstico no ve tendencias. `diagnosticar.py` guarda una muestra del swap usado (como máximo una por
minuto, 12 en total, ventana de 1 h) en `~/.local/share/rendimiento-equipo/<huella>/estado-memoria.json` y
compara con la muestra más antigua de la ventana. Si el usado subió **256 MB o más** (Criterio, no medido),
marca `swap_creciendo: true`. Sin muestras previas dice `null` («sin datos»), que no frena.
Se desactiva con `--sin-estado`.

Para que la señal sirva, corre `diagnosticar.py` (o `perfil.py`) antes y durante un lote largo.

## Frenos

| Señal | Acción |
|---|---|
| Presión ≥2 o swap creciendo | Serializar: un render a la vez, sin conversiones pesadas en paralelo, no levantar otro servidor de Whisper. |
| Térmico serious o critical | Mitad de concurrencia. |
| Swap usado alto pero estable | Informativo. No frena por sí solo; un swap lleno de otra sesión puede seguir ahí. |

## Qué consume memoria en estos flujos

- Cada `whisper-server` carga el modelo completo: un servidor extra duplica ese gasto sin ganar velocidad.
- Cada render de Remotion: pestañas de Chrome (una por unidad de concurrencia) más la caché de OffthreadVideo
  (por defecto el 50 % de la memoria disponible, por render: fíjala).
- Tonemaps de HDR a SDR en CPU: trabajan en punto flotante y son pesados; en serie.
- Intermedios en disco (tramos SDR, WAV): se archivan o se borran al cerrar cada pieza.

En el equipo piloto el swap llegó a casi llenarse con 4 whisper-server vivos (uno huérfano de otra sesión),
3 renders y varios tonemaps en paralelo. El detalle con fecha está en el `mediciones.md` local, no aquí.

## Antes de lanzar algo grande

1. `python3 scripts/perfil.py --renders N --formato texto` y leer FRENOS.
2. Si hay un freno activo, seguir la acción de la tabla, no tu intuición.
3. Si la presión sigue alta con nada corriendo, mirar `procesos_pesados` en el diagnóstico antes de culpar al
   trabajo nuevo: puede haber servidores o Chrome huérfanos (ver `scripts/limpiar.py`).
