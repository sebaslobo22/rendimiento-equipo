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


def modelos(cat):
    """Lista plana de modelos locales de dictado del catalogo, con lo que hace falta para decidir."""
    out = []
    raiz = raiz_cache()
    for mid, m in (cat.get("whisperModels") or {}).items():
        archivo = os.path.join(raiz, "whisper-models", m.get("fileName") or "")
        out.append({"id": mid, "nombre": "Whisper " + m.get("name", mid), "familia": "whisper", "motor": "whisper.cpp",
                    "mb": m.get("sizeMb"), "idiomas": None, "auto_idioma": True,
                    "instalado": os.path.isfile(archivo), "ruta": archivo if os.path.isfile(archivo) else None,
                    "streaming": False})
    for mid, m in (cat.get("parakeetModels") or {}).items():
        carpeta = os.path.join(raiz, "parakeet-models", m.get("extractDir") or mid)
        out.append({"id": mid, "nombre": m.get("name", mid), "familia": "sherpa-onnx", "motor": "sherpa-onnx",
                    "mb": round(m["sizeMb"]) if isinstance(m.get("sizeMb"), (int, float)) else None,
                    "idiomas": m.get("supportedLanguages"), "auto_idioma": m.get("language") == "multilingual",
                    "instalado": os.path.isdir(carpeta), "ruta": carpeta if os.path.isdir(carpeta) else None,
                    "streaming": m.get("runtime") == "online"})
    return out


def habla(m, idioma):
    return m["idiomas"] is None or idioma in m["idiomas"]


def recomendar(memsize, idioma="es", medido=None, frenos_memoria=False, whisper_gpu=True):
    """Punto dulce: el menor error en el idioma, entre los modelos que caben en el presupuesto de memoria.

    Empates de menos de medio punto de error se resuelven por menos memoria. Con el freno de memoria activo,
    el presupuesto se reduce a la mitad.
    """
    cat, version, ruta = catalogo_openwhispr()
    origen = "OpenWhispr %s" % version if cat else "tabla de la skill (OpenWhispr no esta instalado)"
    if not cat:
        cat = fichas().get("catalogo_respaldo") or {}
    fx = fichas().get("modelos", {})
    medido = medido or {}
    presupuesto = (memsize or 0) / 1024 ** 2 * MEMORIA_MAX * (0.5 if frenos_memoria else 1)
    candidatos = []
    for m in modelos(cat):
        f = fx.get(m["id"], {})
        wer = (f.get("wer_" + idioma) or {}).get("valor")
        mem = (medido.get(m["id"]) or {}).get("memoria_mb") or (f.get("memoria_mb") or {}).get("valor") \
            or (m["mb"] * FACTOR_MEMORIA if m["mb"] else None)
        m.update({"wer": wer, "wer_fuente": (f.get("wer_" + idioma) or {}).get("dataset"), "memoria_mb": round(mem) if mem else None,
                  "ficha": bool(f), "medido": medido.get(m["id"])})
        if not habla(m, idioma):
            m["descarte"] = "no transcribe este idioma"
        elif m["streaming"]:
            m["descarte"] = "es para transcribir en vivo; aqui se comparan los de archivo completo"
        elif m["familia"] == "whisper" and not whisper_gpu and (m["mb"] or 0) > 500:
            m["descarte"] = "aqui OpenWhispr corre Whisper en el procesador (CUDA o Vulkan son descargas aparte): un modelo grande va lento"
        elif mem is None or (presupuesto and mem > presupuesto):
            m["descarte"] = "ocupa %s MB: pasa del %d %% de la memoria" % (round(mem) if mem else "?", MEMORIA_MAX * 100)
        elif wer is None:
            m["descarte"] = "sin datos publicos de precision: medir antes de elegir"
        candidatos.append(m)
    validos = sorted((m for m in candidatos if "descarte" not in m), key=lambda m: m["wer"])
    elegido = None
    if validos:
        mejor = validos[0]["wer"]
        cerca = [m for m in validos if m["wer"] - mejor < EMPATE_WER]
        elegido = min(cerca, key=lambda m: m["memoria_mb"])
    return {"idioma": idioma, "catalogo": origen, "presupuesto_mb": round(presupuesto),
            "recomendado": elegido, "modelos": candidatos,
            "nuevos_sin_ficha": [m["nombre"] for m in candidatos if not m["ficha"]],
            "como_cambiarlo": "OpenWhispr > Configuracion > Conversion de voz a texto > Local > elige el modelo y descargalo"}


if __name__ == "__main__":
    import argparse
    sys.path.insert(0, AQUI)
    import diagnosticar as dg
    ap = argparse.ArgumentParser(description="Recomienda el modelo local de dictado de OpenWhispr para este equipo.")
    ap.add_argument("--idioma", default="es", help="codigo del idioma que mas dictas (por defecto %(default)s)")
    a = ap.parse_args()
    print(json.dumps(recomendar(dg.memoria_total(), a.idioma), ensure_ascii=False, indent=2))
