# Windows: diagnóstico y mediciones, sin recomendaciones todavía

En Windows la skill describe el equipo y mide, pero **no recomienda** nada hasta tener mediciones de equipos
reales. Mientras tanto, cada herramienta trabaja con sus valores por defecto. La diferencia con macOS: Apple hace
todo el chip, y en Windows cada equipo mezcla procesador, tarjeta gráfica y controladores de marcas distintas.

## Qué hace cada script en Windows

| Script | En Windows |
|---|---|
| `diagnosticar.py` | Lee CPU, memoria, archivo de paginación, adaptadores de video, NPU y energía. Abre de verdad cada codificador y acelerador por hardware con un clip sintético de 1 s. Marca `"soporte"`: hay diagnóstico, no recomendaciones. `--sin-pruebas-video` omite las pruebas. |
| `perfil.py` | Resume el diagnóstico y lo medido en ese equipo, y entrega un bloque para subagentes solo con reglas que no dependen del equipo. No recomienda codificadores ni concurrencias. |
| `medir.py` | `codificar`: libx264 frente a cada codificador que abre (`h264_nvenc`, `h264_qsv`, `h264_amf`, `h264_mf`). `decodificar`: CPU frente a cada acelerador que abre (`cuda`, `qsv`, `d3d11va`). Mismo criterio que en macOS y mismo registro por huella. `remotion` todavía no. |
| `limpiar.py` | Solo muestra. `--aplicar` se niega: en Windows no hay SIGTERM y cerrar a la fuerza puede dejar archivos a medias. |
| `install.ps1` | Enlaza la skill con junctions en `%USERPROFILE%\.claude\skills` y `%USERPROFILE%\.agents\skills`. No pide administrador. |

## Cómo se lee cada cosa

| Dato | De dónde sale | Nivel |
|---|---|---|
| Núcleos por tipo | `GetLogicalProcessorInformationEx`: cada núcleo trae una clase de eficiencia; más alta, más rendimiento. La clase más alta se llama «Performance»; las demás, «Efficiency (clase N)». | Oficial (Microsoft) |
| Memoria | `GlobalMemoryStatusEx`: total, disponible, carga y memoria comprometida. | Oficial |
| Archivo de paginación | CIM `Win32_PageFileUsage`. Es lo más parecido al swap de macOS y se usa igual para decir si crece. | Oficial |
| Presión de memoria | Windows no publica niveles como macOS: queda en `null`. No se inventa un umbral. | — |
| Adaptadores de video | CIM `Win32_VideoController`. La VRAM sale del registro (`HardwareInformation.qwMemorySize`), porque CIM la corta en 4 GB. | Oficial |
| NPU | Dispositivos de la clase `ComputeAccelerator`. Solo dice si hay; nada la usa todavía. | Oficial |
| Estado térmico | Windows no tiene uno estándar: queda en `null`. | — |
| Ahorro de energía | `GetSystemPowerStatus`. | Oficial |
| Procesos pesados | CIM `Win32_Process`. Un proceso es huérfano si su padre ya no existe (Windows no los pasa a otro padre). | Criterio |
| Tiempo de CPU en `medir.py` | `GetProcessTimes` del proceso de ffmpeg (no cuenta hijos; ffmpeg no lanza otros). | Oficial |

Que un ffmpeg traiga un codificador no prueba que el equipo lo abra: sin la tarjeta o su controlador, falla al
abrir. Por eso `diagnosticar.py` lo abre con un clip de prueba. Que abra tampoco prueba que convenga: eso lo
decide `medir.py`. Dos detalles que evitan medir otra cosa sin saberlo:

- `h264_mf` va con `-hw_encoding 1`: sin eso, Media Foundation puede caer a un codificador por software.
- Las pruebas de decodificación usan `-hwaccel_output_format`: sin eso, ffmpeg vuelve a la CPU sin avisar si el
  acelerador falla.

## Lo que falta para recomendar

1. **Mediciones en equipos reales.** Al menos uno con tarjeta NVIDIA, uno con gráfica Intel y uno con AMD.
   Las máquinas de GitHub donde se prueban los scripts no tienen tarjeta gráfica: ahí no se mide rendimiento.
2. Con eso, `perfil.py` recomienda en Windows lo medido en cada huella, igual que en macOS.
3. Después, por separado: Remotion en Windows, Whisper con CUDA o Vulkan, la prioridad de fondo (el «modo de
   eficiencia» de Windows 11) y recortes de personas, que no tienen un equivalente incluido como Vision.

## Para quien quiera medir su equipo

Con la skill instalada, pega esto en Claude Code o Codex, en la carpeta de un video tuyo de unos 30 s:

```text
Usa la skill rendimiento-equipo. Corre perfil.py --formato texto, después medir.py codificar y medir.py decodificar con mi video y --registrar, y muéstrame el resultado y el archivo mediciones.md.
```

Lo que conviene compartir es la salida de `perfil.py --formato texto` y `mediciones.md`. El JSON completo de
`diagnosticar.py` trae rutas de tu carpeta de usuario y la línea de comandos de algunos procesos: revísalo antes
de mandarlo.

Las reglas que no dependen del sistema valen igual en Windows: un solo servidor de transcripción, encargos
autosuficientes para subagentes, dos escritores nunca en el mismo archivo, verificar con evidencia y apagar solo
lo propio (ver `agentes.md`).
