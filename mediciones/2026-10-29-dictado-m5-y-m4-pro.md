# Dictado local en dos Mac: M5 base de 16 GB y M4 Pro de 24 GB

Mediciones del 29.10.2026 con los modelos que trae OpenWhispr. El M5 lo midió un usuario con la skill instalada
y escribió un informe; el M4 Pro es el Mac piloto. Las dos mediciones cambiaron la skill (versión 1.4.0).

## Qué se aprendió

1. **En el M5 base, Parakeet le gana a Whisper en precisión y Whisper base le gana en velocidad.** Parakeet TDT
   0.6B v3 tuvo 2,3 % de palabras erradas; los Whisper, entre 5,4 y 6,9 %. Parakeet corre en el procesador y deja
   libre la GPU. A cambio ocupa más memoria que Whisper Turbo: 1,7 GB frente a 1,2 GB.
2. **Los Neural Accelerators del M5 no se usaban.** El whisper-server de OpenWhispr 1.10.4 intenta activar la API
   de tensores de Metal, no logra compilarla y la apaga (`has tensor = false`). La skill daba por hecho que
   whisper.cpp los usa. Ahora lo lee del registro del servidor y dice lo que encuentra.
3. **El mismo modelo da otra respuesta en otro equipo.** Whisper Turbo con Metal fue 7,9 veces más rápido que en
   el procesador en el M5 base (GPU de 10 núcleos) y 15 veces en el M4 Pro (GPU de 20 núcleos). Por eso la skill
   recomienda por equipo, no por chip: cuenta la memoria (tamaño y ancho de banda), la GPU y lo medido ahí.
4. **El porcentaje de error castigaba los números.** Casi todo el error de los Whisper venía de escribir «12 %»
   donde la referencia decía «doce por ciento». Ahora la skill convierte cifras a palabras antes de comparar.
5. **Bajar Parakeet de 4 a 2 hilos** cuesta 12 % de velocidad y ahorra 250 MB.
6. **El swap creció de 2 a 4 GB sin que la presión de memoria dejara de ser normal.** La skill ahora frena el
   trabajo pesado cuando el swap pasa del 75 % de su tamaño, aunque no esté creciendo.

## MacBook Pro M5 base, 16 GB

CPU de 10 núcleos (4 super y 6 de eficiencia), GPU de 10 núcleos, Neural Engine de 16, macOS 27.2,
OpenWhispr 1.10.4. 42,7 s de voz sintética en español con cifras y nombres de países. Una pasada de
calentamiento y la media de 3.

| Modelo | Dónde corre | Tiempo | Veces el tiempo real | Memoria pico | Palabras erradas |
|---|---|---|---|---|---|
| Whisper Base | GPU (Metal) | 0,50 s | 85 | 315 MB | 5,4 % |
| Whisper Small | GPU (Metal) | 1,21 s | 35 | 330 MB | 6,9 % |
| Whisper Medium | GPU (Metal) | 3,28 s | 13 | 730 MB | 5,4 % |
| Whisper Turbo | GPU (Metal) | 2,42 s | 18 | 1.159 MB | 6,9 % |
| Whisper Turbo | Procesador | 19,18 s | 2,2 | 1.816 MB | 6,9 % |
| **Parakeet TDT 0.6B v3** | Procesador, 4 hilos | **1,36 s** | 31 | 1.748 MB | **2,3 %** |
| Parakeet TDT 0.6B v3 | Procesador, 2 hilos | 1,53 s | 28 | 1.499 MB | 2,3 % |

Los errores de Whisper se midieron antes de normalizar cifras: con la normalización nueva serían menores.

## Mac piloto: M4 Pro, 24 GB

GPU de 20 núcleos, 273 GB/s de memoria, OpenWhispr 1.11.0. 12 s de voz sintética, con `medir.py voz`.

| Modelo | Dónde corre | Tiempo | Veces el tiempo real | Memoria pico | Palabras erradas |
|---|---|---|---|---|---|
| Whisper Turbo | GPU (Metal) | 0,53 s | 23 | 1.809 MB | 6,3 % |
| Whisper Turbo | Procesador | 7,92 s | 1,5 | 1.768 MB | 6,3 % |

El error que queda es un nombre propio: «Parakeet» lo escribió «Para KED».

## Límites

- Voz sintética (`say` de macOS), no voz humana. Sirve para comparar modelos entre sí, no para prometer la
  precisión que tendrás dictando.
- Un audio por equipo. Un solo equipo de cada tipo.
- La memoria es la del servidor de prueba, no la de OpenWhispr entero.

## Repetirlo en tu equipo

```
python3 scripts/medir.py voz --audio tu-voz.m4a --texto lo-que-dices.txt --backends metal,cpu --registrar
```

Mide todos los modelos de dictado que tengas descargados en OpenWhispr, cada uno en un servidor propio que se
apaga al terminar. Si quieres sumar tu resultado, abre un issue con la salida.
