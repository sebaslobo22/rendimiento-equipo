#!/usr/bin/env python3
"""Modelo de dictado local: el punto dulce entre precision y lo que el equipo puede cargar sin estorbar.

Lee el catalogo que trae OpenWhispr instalado (asi, cuando la app suma modelos, la skill los ve sin cambiar
nada), cruza cada modelo con su ficha publica (assets/fichas_voz.json: error por idioma, tamano, memoria) y con
lo que este equipo tiene y midio, y recomienda. Funciona igual en macOS y en Windows.

Orden de confianza: lo medido aqui (medir.py voz) > la ficha publica > el tamano del archivo. Un modelo nuevo sin
ficha aparece igual, marcado para medir: nunca se le inventa una precision.

Solo sugiere: el modelo se cambia en OpenWhispr (Configuracion > Conversion de voz a texto > Local). Solo
biblioteca estandar; no usa red.
"""
from __future__ import annotations

import json
import os
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
FICHAS = os.path.join(os.path.dirname(AQUI), "assets", "fichas_voz.json")
MEMORIA_MAX = 0.20     # criterio: el modelo no deberia ocupar mas del 20 % de la memoria total (deja sitio a renders y apps)
EMPATE_WER = 0.5       # criterio: diferencias de menos de medio punto de error no justifican mas memoria
FACTOR_MEMORIA = 1.3   # criterio: sin dato publicado, memoria al transcribir ~ 1,3 veces el archivo del modelo
VELOCIDAD_MIN = 4.0    # criterio: dictar 30 s y tener el texto en menos de 8 s (4 veces el tiempo real)
# Whisper en la GPU de Apple esta limitado por el ancho de banda de la memoria: cada palabra relee el modelo.
# Calibrado con turbo (1549 MB) en un M4 Pro de 273 GB/s: 20 a 23 veces el tiempo real (medir.py voz, 29.10.2026).
# Es una estimacion para equipos sin medir; lo medido en el equipo la reemplaza.
K_ANCHO_BANDA = 119.0


def rutas_app():
    """Donde puede estar el app.asar de OpenWhispr en este sistema."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        return [os.path.join(base, "Programs", "OpenWhispr", "resources", "app.asar"),
                os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "OpenWhispr", "resources", "app.asar")]
    return ["/Applications/OpenWhispr.app/Contents/Resources/app.asar",
            os.path.expanduser("~/Applications/OpenWhispr.app/Contents/Resources/app.asar")]


def raiz_cache():
    """Carpeta de modelos de OpenWhispr, con las mismas reglas que la app (modelDirUtils.js)."""
    if os.environ.get("OPENWHISPR_CACHE_ROOT"):
        return os.environ["OPENWHISPR_CACHE_ROOT"]
    casa = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".cache", "openwhispr")
    if sys.platform == "win32" and not os.path.isdir(casa):
        for alt in (os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "OpenWhispr", "cache"),
                    os.path.join(os.environ.get("SystemDrive", "C:"), os.sep, "OpenWhispr", "cache")):
            if os.path.isdir(alt):
                return alt
    return casa


def leer_asar(ruta, interno):
    """Lee un archivo de dentro de un .asar de Electron (cabecera JSON + datos), sin dependencias."""
    with open(ruta, "rb") as f:
        cab = f.read(16)
        largo = struct.unpack("<I", cab[12:16])[0]
        indice = json.loads(f.read(largo))
        base = 8 + struct.unpack("<I", cab[4:8])[0]
        nodo = indice
        for parte in interno.strip("/").split("/"):
            nodo = nodo["files"][parte]
        f.seek(base + int(nodo["offset"]))
        return f.read(nodo["size"])


def catalogo_openwhispr():
    """(catalogo, version, ruta) del OpenWhispr instalado, o (None, None, None) si no esta."""
    for ruta in rutas_app():
        if os.path.isfile(ruta):
            try:
                datos = json.loads(leer_asar(ruta, "/src/models/modelRegistryData.json"))
            except (OSError, ValueError, KeyError, struct.error):
                continue
            version = None
            try:
                version = json.loads(leer_asar(ruta, "/package.json")).get("version")
            except (OSError, ValueError, KeyError, struct.error):
                pass
            return datos, version, ruta
    return None, None, None


def fichas():
    try:
        with open(FICHAS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"modelos": {}}


def carpeta_pruebas():
    """Modelos que descarga calibrar.py solo para medir: fuera de OpenWhispr, que nunca se toca."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "rendimiento-equipo", "modelos-voz")


def modelos(cat):
    """Lista plana de modelos locales de dictado del catalogo, con lo que hace falta para decidir y para medir.

    instalado: descargado en OpenWhispr. ruta: donde esta, en OpenWhispr o en la carpeta de pruebas de la skill.
    """
    out = []
    raiz, prueba = raiz_cache(), carpeta_pruebas()

    def ubicar(sub, nombre, es_archivo):
        existe = os.path.isfile if es_archivo else os.path.isdir
        ow, pr = os.path.join(raiz, sub, nombre), os.path.join(prueba, sub, nombre)
        return existe(ow), (ow if existe(ow) else pr if existe(pr) else None)
    for mid, m in (cat.get("whisperModels") or {}).items():
        inst, ruta = ubicar("whisper-models", m.get("fileName") or "?", True)
        out.append({"id": mid, "nombre": "Whisper " + m.get("name", mid), "familia": "whisper", "motor": "whisper.cpp",
                    "mb": m.get("sizeMb"), "idiomas": None, "auto_idioma": True,
                    "instalado": inst, "ruta": ruta, "streaming": False,
                    "url": m.get("downloadUrl"), "archivo": m.get("fileName")})
    for mid, m in (cat.get("parakeetModels") or {}).items():
        inst, ruta = ubicar("parakeet-models", m.get("extractDir") or mid, False)
        out.append({"id": mid, "nombre": m.get("name", mid), "familia": "sherpa-onnx", "motor": "sherpa-onnx",
                    "mb": round(m["sizeMb"]) if isinstance(m.get("sizeMb"), (int, float)) else None,
                    "idiomas": m.get("supportedLanguages"), "auto_idioma": m.get("language") == "multilingual",
                    "instalado": inst, "ruta": ruta, "streaming": m.get("runtime") == "online",
                    "sherpa_tipo": m.get("sherpaModelType"), "tipo_modelo": m.get("modelType"),
                    "url": m.get("downloadUrl"), "archivo": m.get("extractDir") or mid})
    return out


def habla(m, idioma):
    return m["idiomas"] is None or idioma in m["idiomas"]


def _audio_comun(medido):
    """El audio con mas modelos medidos con error (--texto). Solo comparando el mismo audio el error medido sirve para elegir."""
    por_audio = {}
    for mid, r in (medido or {}).items():
        if isinstance(r, dict) and r.get("wer") is not None and r.get("audio_id"):
            por_audio.setdefault(r["audio_id"], []).append(mid)
    if not por_audio:
        return None, []
    sintetico = {r.get("audio_id"): bool(r.get("audio_sintetico")) for r in medido.values() if isinstance(r, dict)}
    validos = {a: m for a, m in por_audio.items() if len(m) >= 2}
    if not validos:
        return None, []
    # tu voz real primero; despues el audio con mas modelos medidos
    aid, mids = max(validos.items(), key=lambda kv: (not sintetico.get(kv[0]), len(kv[1])))
    return (aid, mids) if len(mids) >= 2 else (None, [])


def recomendar(memsize, idioma="es", medido=None, frenos_memoria=False, whisper_gpu=True, equipo=None):
    """Punto dulce de ESTE equipo: el menor error en el idioma entre los modelos que caben en su memoria y que
    transcriben al menos VELOCIDAD_MIN veces el tiempo real en su hardware.

    Lo que manda, en orden: lo medido en el equipo con medir.py voz (error sobre el mismo audio, memoria y
    velocidad reales), luego lo estimado con su ancho de banda de memoria (Whisper en GPU), luego la ficha publica.
    El presupuesto de memoria es el 20 % de la del equipo, la mitad con el freno de memoria activo. Empates de
    menos de medio punto de error se resuelven por menos memoria y despues por mas velocidad.
    """
    cat, version, ruta = catalogo_openwhispr()
    origen = "OpenWhispr %s" % version if cat else "tabla de la skill (OpenWhispr no esta instalado)"
    if not cat:
        cat = fichas().get("catalogo_respaldo") or {}
    fx = fichas().get("modelos", {})
    medido = {k: v for k, v in (medido or {}).items() if isinstance(v, dict)}
    equipo = equipo or {}
    bw = equipo.get("ancho_banda_gbs")
    audio_id, con_error_medido = _audio_comun(medido)
    presupuesto = (memsize or 0) / 1024 ** 2 * MEMORIA_MAX * (0.5 if frenos_memoria else 1)
    lista = modelos(cat)
    referencia_propia = {}  # por motor: (veces tiempo real, MB del modelo, nombre) del mas grande medido aqui
    for m in lista:
        r = medido.get(m["id"])
        if r and r.get("veces_tiempo_real") and m["mb"] and (r.get("backend") != "cpu" or m["familia"] != "whisper" or not whisper_gpu):
            if m["mb"] > referencia_propia.get(m["familia"], (0, 0))[1]:
                referencia_propia[m["familia"]] = (r["veces_tiempo_real"], m["mb"], m["nombre"])
    candidatos = []
    for m in lista:
        f = fx.get(m["id"], {})
        med = medido.get(m["id"])
        wer_pub = (f.get("wer_" + idioma) or {}).get("valor")
        usa_medido = m["id"] in con_error_medido
        wer = med["wer"] if usa_medido else wer_pub
        mem = (med or {}).get("memoria_mb") or (f.get("memoria_mb") or {}).get("valor") \
            or (m["mb"] * FACTOR_MEMORIA if m["mb"] else None)
        vel, vel_origen = (med or {}).get("veces_tiempo_real"), "medida"
        ref = referencia_propia.get(m["familia"])
        if vel is None and ref and m["mb"]:
            # mismo equipo, mismo motor: la velocidad baja en proporcion al tamano del modelo
            vel, vel_origen = round(ref[0] * ref[1] / m["mb"], 1), "estimada desde %s medido en este equipo" % ref[2]
        elif vel is None and m["familia"] == "whisper" and whisper_gpu and bw and m["mb"]:
            vel, vel_origen = round(K_ANCHO_BANDA * bw / m["mb"], 1), "estimada con %s GB/s de memoria" % bw
        elif vel is None:
            vel_origen = None
        m.update({"wer": wer, "wer_publico": wer_pub,
                  "wer_fuente": ("medido en este equipo con %s" % ("voz sintetica" if (med or {}).get("audio_sintetico") else "tu voz")) if usa_medido else (f.get("wer_" + idioma) or {}).get("dataset"),
                  "memoria_mb": round(mem) if mem else None, "velocidad": vel, "velocidad_origen": vel_origen,
                  "ficha": bool(f), "medido": med})
        if not habla(m, idioma):
            m["descarte"] = "no transcribe este idioma"
        elif m["streaming"]:
            m["descarte"] = "es para transcribir en vivo; aqui se comparan los de archivo completo"
        elif m["familia"] == "whisper" and not whisper_gpu and (m["mb"] or 0) > 500:
            m["descarte"] = "aqui OpenWhispr corre Whisper en el procesador (CUDA o Vulkan son descargas aparte): un modelo grande va lento"
        elif mem is None or (presupuesto and mem > presupuesto):
            m["descarte"] = "ocupa %s MB: pasa del %d %% de la memoria" % (round(mem) if mem else "?", MEMORIA_MAX * 100)
        elif vel is not None and vel < VELOCIDAD_MIN:
            m["descarte"] = "en este equipo va a %s veces el tiempo real (%s): dictar se sentiria lento" % (vel, vel_origen)
        elif wer is None:
            m["descarte"] = "sin datos publicos de precision: medir antes de elegir"
            m["medible"] = True
        candidatos.append(m)
    validos = [m for m in candidatos if "descarte" not in m]
    if con_error_medido and any(m["id"] in con_error_medido for m in validos):
        validos = [m for m in validos if m["id"] in con_error_medido]  # el error medido no se mezcla con el publicado
    validos.sort(key=lambda m: m["wer"])
    elegido, por_medir = None, []
    if validos:
        mejor = validos[0]["wer"]
        cerca = [m for m in validos if m["wer"] - mejor < EMPATE_WER]
        elegido = min(cerca, key=lambda m: (m["memoria_mb"], -(m["velocidad"] or 0)))
        if con_error_medido and elegido.get("wer_publico") is not None:
            por_medir = [m["nombre"] for m in candidatos if "descarte" not in m and m["id"] not in con_error_medido
                         and m["wer"] is not None and m["wer"] < elegido["wer_publico"] - EMPATE_WER]
    return {"idioma": idioma, "catalogo": origen, "presupuesto_mb": round(presupuesto),
            "equipo": {"memoria_gb": round((memsize or 0) / 1024 ** 3), "ancho_banda_gbs": bw, "gpu_nucleos": equipo.get("gpu_nucleos"),
                       "whisper_en_gpu": whisper_gpu, "freno_memoria": frenos_memoria},
            "criterio": "error medido sobre el mismo audio (%d modelos)" % len(con_error_medido) if con_error_medido else "error publico",
            "recomendado": elegido, "modelos": candidatos, "medir_tambien": por_medir,
            "nuevos_sin_ficha": [m["nombre"] for m in candidatos if not m["ficha"]],
            "como_cambiarlo": "OpenWhispr > Configuracion > Conversion de voz a texto > Local > elige el modelo y descargalo"}


def candidatos_prueba(rec, max_descargas=3, margen=1.5):
    """Que medir en este equipo: todo lo que ya esta y sirve (gratis), mas los mejores por ficha publica que faltan.

    Entran los que pasaron los filtros del equipo (idioma, memoria, velocidad) o solo les falta un dato de error.
    De los que faltan, los que quedan a menos de `margen` puntos del mejor error publico, el recomendado siempre,
    hasta `max_descargas`, los de menos error primero.
    """
    sirven = [m for m in rec["modelos"] if "descarte" not in m or m.get("medible")]
    ya = [m for m in sirven if m.get("ruta")]
    faltan = sorted((m for m in sirven if not m.get("ruta") and m.get("url") and m.get("wer") is not None), key=lambda m: m["wer"])
    mejor = faltan[0]["wer"] if faltan else None
    bajar = [m for m in faltan if m["wer"] - mejor <= margen][:max_descargas]
    # modelos que el catalogo trajo despues de la ficha: solo midiendolos se sabe si ganan. Entra el mas liviano.
    nuevos = sorted((m for m in sirven if not m.get("ruta") and m.get("url") and m.get("wer") is None and not m["ficha"]),
                    key=lambda m: m["mb"] or 1e9)
    bajar += nuevos[:1]
    r = rec.get("recomendado")
    if r and not r.get("ruta") and r.get("url") and all(m["id"] != r["id"] for m in bajar):
        bajar = ([r] + bajar)[:max_descargas]
    return ya, bajar


if __name__ == "__main__":
    import argparse
    sys.path.insert(0, AQUI)
    import diagnosticar as dg
    ap = argparse.ArgumentParser(description="Recomienda el modelo local de dictado de OpenWhispr para este equipo.")
    ap.add_argument("--idioma", default="es", help="codigo del idioma que mas dictas (por defecto %(default)s)")
    a = ap.parse_args()
    print(json.dumps(recomendar(dg.memoria_total(), a.idioma), ensure_ascii=False, indent=2))
