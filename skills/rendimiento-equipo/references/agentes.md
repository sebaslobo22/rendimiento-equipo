# Agentes y subagentes: cómo repartir trabajo pesado

Los subagentes no heredan skills ni contexto (Oficial: docs de subagentes de Claude Code). Todo lo que necesitan
debe ir en el encargo. Esta guía es el porqué de cada regla; el bloque ya relleno sale de `scripts/perfil.py`.

## Índice
1. Encargos autosuficientes
2. Paralelismo sin conflictos
3. Un solo Whisper y tiempos precalculados
4. Verificar con evidencia
5. Apagar lo propio
6. Plantilla de encargo

## 1. Encargos autosuficientes

- Pega el **bloque para subagentes** de `perfil.py` (rutas absolutas incluidas: el subagente no sabe cuál ffmpeg es
  el bueno ni dónde está el modelo).
- Di el objetivo, las rutas de entrada y salida exactas, qué archivos puede tocar y cuáles no, y qué devolver.
- Pide **resúmenes, no volcados**: tiempos, tamaños, rutas y errores en pocas líneas.
- Si el encargo incluye video, transcripción o recortes, el bloque va siempre, aunque parezca obvio.

## 2. Paralelismo sin conflictos

- Dos escritores nunca en el mismo archivo, sesión o cuenta. Cada agente escribe en su carpeta de salida.
- Cuántos renders en paralelo: lo dice `perfil.py --renders N`. Más renders no es más velocidad: pasado el punto de
  reparto de núcleos solo sube la memoria y el riesgo de «Target closed».
- Las conversiones pesadas de CPU (tonemap) no corren mientras hay varios renders.
- Si hay un freno activo (memoria o térmico), el bloque ya lo trae: se obedece.
- Un agente que va a medir (`medir.py`) lo avisa al hilo principal: la medición exige que nadie más renderice.

## 3. Un solo Whisper y tiempos precalculados

- Un único servidor para todos. Quien lo necesita primero lo lanza y lo anuncia (puerto y PID); los demás lo
  reutilizan o, mejor, leen los tiempos por palabra ya calculados.
- Antes de repartir, el hilo principal transcribe todo en un solo paso y deja los resultados en archivos
  (por ejemplo una carpeta `_tiempos_palabra/`). Los agentes leen archivos y no levantan servidores.
- Nunca un servidor por agente: duplica el modelo en memoria y el servidor serializa de todos modos.

## 4. Verificar con evidencia

- «Hecho» sin evidencia no vale: cada resultado trae el comando que lo produjo y su salida (o el fragmento
  relevante). Para un render: ruta, tamaño, duración y cuánto tardó.
- Lo que entrega un subagente es un borrador: el hilo principal lo comprueba contra el archivo real, no contra el
  resumen.
- Una medición sin evidencia no entra al perfil. El único camino es `medir.py --registrar`.

## 5. Apagar lo propio

- Cada agente apaga **por PID y con SIGTERM** lo que lanzó. Si él lanzó un servidor: `limpiar.py --aplicar --pid <PID>`.
- `limpiar.py` sin `--pid` apaga todos los procesos propios (servidores de agentes y Remotion o Chrome huérfanos).
  Eso es del hilo principal, al cerrar el lote, porque podría apagar el servidor que otro agente aún usa.
- Primero se corre sin `--aplicar` y se lee la lista. Los protegidos (OpenWhispr) y los «en uso» no se tocan nunca.
- Si un proceso no cierra con SIGTERM, se informa y lo decide una persona; no se fuerza con SIGKILL.
- Borrar también los intermedios (WAV, tramos SDR) que ya no sirven.

## 6. Plantilla de encargo

```
Objetivo: <una frase>.
Entradas: <rutas exactas>. Salida: <ruta exacta, carpeta propia>. No toques: <rutas>.
<bloque para subagentes de perfil.py, pegado tal cual>
Devuelve: lista de archivos generados con tamaño y duración; el comando final y su salida;
cuánto tardó el paso pesado; confirmación de que apagaste lo que lanzaste (PID).
Si algo falla: dime el comando, el error y qué probaste. No cambies de método sin avisar.
```
