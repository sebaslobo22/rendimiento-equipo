#!/usr/bin/env python3
"""Saltos de arquitectura de Apple Silicon: que trae este chip y que hace la skill con cada cosa.

Se decide por lo que el diagnostico DETECTA (familia Metal, codecs por hardware, extensiones de la CPU,
nucleos del Neural Engine, version de ffmpeg), no por el nombre del chip: un chip nuevo con las mismas
capacidades recibe las mismas reglas sin tocar nada, y uno con una familia Metal mas nueva que las
conocidas se marca para medir en vez de suponer.

Orden de confianza: lo medido en el equipo (perfil-medido.json) > lo detectado > la tabla de Apple
(assets/chips_apple.json), que solo sirve de referencia para lo que ninguna API dice, como cuantos motores
de codificacion de video hay. Fuentes y citas de cada regla: references/arquitectura.md.

Solo biblioteca estandar. Lo usa perfil.py; no se corre solo.
"""
from __future__ import annotations

import json
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
TABLA_APPLE = os.path.join(os.path.dirname(AQUI), "assets", "chips_apple.json")
FAMILIA_CONOCIDA = 10  # apple10 = serie M5 (tabla de Metal de Apple, mayo 2026); una mayor se marca para medir
# Version minima de ffmpeg para leer cada codec con -hwaccel videotoolbox (verificado en el codigo de ffmpeg)
FFMPEG_MINIMO = {"prores": 5, "prores_4444": 5, "av1": 8}
CODECS_FFMPEG = ("h264", "hevc", "prores", "prores_4444", "av1", "vp9")


def version_mayor(texto):
    """'6.0' -> 6, 'n7.1' -> 7, '8.0.1-tessus' -> 8; compilaciones de git ('N-12345-g...') -> None."""
    m = re.match(r"n?(\d+)\.\d+", texto or "")
    return int(m.group(1)) if m else None


def _ffmpeg(d):
    h = (d.get("herramientas") or {}).get("ffmpeg") or {}
    return next((c for c in h.get("candidatos", []) if c.get("ruta") == h.get("elegido")), {})


def capacidades(d, medido=None):
    """Lo que el diagnostico detecto (y lo medido que cambia una regla), en una forma comoda para las reglas."""
    t = ((medido or {}).get("whisper") or {}).get("api_tensores")
    gpu = d.get("gpu") or {}
    metal = gpu.get("metal") or {}
    m = re.search(r"(\d+)", metal.get("familia_apple_maxima") or "")
    vid = d.get("video") or {}
    cpu = d.get("cpu") or {}
    ff = _ffmpeg(d)
    return {
        "chip": cpu.get("marca"),
        "familia": int(m.group(1)) if m else None,
        "metal": metal.get("familias_metal") or [],
        "codifica_hw": (vid.get("codificadores") or {}).get("codecs_por_hardware"),  # None = sin dato (falta Swift)
        "decodifica_hw": vid.get("decodificadores_hw"),                             # None = sin dato
        "extensiones": cpu.get("extensiones") or [],
        "ne_nucleos": (d.get("neural_engine") or {}).get("nucleos"),
        "ffmpeg_version": ff.get("version"),
        "ffmpeg_mayor": version_mayor(ff.get("version")),
        "api_tensores": t.get("valor") if isinstance(t, dict) else None,
    }


def tabla_apple():
    try:
        with open(TABLA_APPLE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def referencia_apple(chip):
    """Fila de la tabla de Apple para la marca exacta del chip ("Apple M4 Pro"), o None."""
    if not chip:
        return None
    return (tabla_apple().get("chips") or {}).get(re.sub(r"^Apple\s+", "", chip.strip()))


def _uso_av1(c):
    if c["ffmpeg_mayor"] is not None and c["ffmpeg_mayor"] >= FFMPEG_MINIMO["av1"]:
        return "Los videos AV1 se leen con -hwaccel videotoolbox (ffmpeg %s)." % c["ffmpeg_version"]
    return ("El chip lo decodifica, pero ffmpeg solo lo usa desde la 8.0 y el de este equipo es %s: AV1 va a la CPU. "
            "Para usar el motor, instala un ffmpeg 8.0 o posterior." % (c["ffmpeg_version"] or "desconocido"))


def _uso_motores(c):
    ref = referencia_apple(c["chip"]) or {}
    return ("Apple publica %d motores de codificacion de video en este chip: varias codificaciones a la vez pueden rendir "
            "mas. Medido o no, el numero sale de medir.py paralelo." % ref.get("enc", 0))


# Cada regla: (si, modulo, salto, que hace la skill, nivel). `si` recibe capacidades(); `uso` puede ser una funcion de ellas.
REGLAS = [
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("h264") and c["decodifica_hw"].get("hevc"),
     "Motor de video", "H.264 y HEVC por hardware (desde M1)",
     "Codifica con h264_videotoolbox y lee con -hwaccel videotoolbox; bitrate fijo y -allow_sw 0.", "Oficial + medido"),
    (lambda c: c["codifica_hw"] is not None and ("apcn" in c["codifica_hw"] or "ap4h" in c["codifica_hw"]),
     "Motor de video", "ProRes por hardware (desde M1 Pro y M1 Max; en los chips base desde M2)",
     "Intermedios de edicion en ProRes con prores_videotoolbox (ffmpeg 5.0 o posterior) en vez de prores_ks en la CPU.",
     "Oficial (detectado)"),
    (lambda c: (referencia_apple(c["chip"]) or {}).get("enc", 0) >= 2,
     "Motor de video", "Varios motores de codificacion de video (Max y Ultra)", _uso_motores, "Oficial (tabla de Apple)"),
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("av1"),
     "Motor de video", "Decodificacion AV1 por hardware (desde M3; ningun chip codifica AV1)", _uso_av1,
     "Oficial (detectado) + codigo de ffmpeg"),
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("prores_raw"),
     "Motor de video", "ProRes RAW por hardware",
     "Se informa: lo aprovechan Final Cut Pro y las apps de Apple; la skill no lo usa todavia.", "Oficial (detectado)"),
    (lambda c: c["familia"] is not None and c["familia"] >= 9,
     "GPU", "Dynamic Caching, sombreado de mallas y trazado de rayos por hardware (desde M3, familia Metal apple9)",
     "Dynamic Caching es automatico. El trazado de rayos por hardware lo usa Blender Cycles solo (MetalRT desde M3); "
     "Chrome, Remotion y ffmpeg no lo usan. Las APIs existen desde M1, pero sin hardware dedicado.", "Oficial"),
    (lambda c: c["familia"] is not None and c["familia"] >= 10,
     "GPU", "Neural Accelerators en cada nucleo de la GPU (desde M5, familia Metal apple10)",
     lambda c: "Core ML y Metal Performance Shaders los usan solos. whisper.cpp puede usarlos desde v1.8.3, pero "
     "depende de como se compilo: el whisper-server de OpenWhispr 1.10.4 los tenia apagados en un M5 (\"has tensor = "
     "false\"). " + {True: "Medido en este equipo: el whisper-server de OpenWhispr SI los usa.",
                      False: "Medido en este equipo: el whisper-server de OpenWhispr NO los usa; Whisper corre en la GPU "
                             "normal y Parakeet (en el procesador) suele ganarle.",
                      None: "Sin medir aqui: medir.py voz lo lee del registro del servidor."}[c.get("api_tensores")]
     + " Core ML no tiene ventaja demostrada frente a Metal: mide antes de cambiar el backend.",
     "Oficial (Apple) + codigo de whisper.cpp + medicion en M5"),
    (lambda c: "metal4" in c["metal"],
     "GPU", "Metal 4 (API de tensores; macOS 26 o posterior, desde M1)",
     "Se informa: lo aprovechan las bibliotecas que lo implementan. En M5 o posterior corre en los Neural Accelerators.",
     "Oficial (detectado)"),
    (lambda c: "FEAT_SME2" in c["extensiones"] or "FEAT_SME" in c["extensiones"],
     "CPU", "Extension de matrices SME (detectada; la declaran los chips desde M4)",
     "Automatico: la usa Accelerate y lo que se apoya en Accelerate. Nada que configurar.", "Detectado"),
    (lambda c: bool(c["ne_nucleos"]),
     "Neural Engine", "Neural Engine detectado",
     "Recortes de personas con Vision y modelos de Core ML lo usan solos. No instalar modelos de Python para recortar.",
     "Oficial (detectado)"),
    (lambda c: c["familia"] is not None and c["familia"] > FAMILIA_CONOCIDA,
     "GPU", "Familia Metal mas nueva que las que la skill conoce",
     "Se aplican las reglas comunes y conviene medir cada metodo con medir.py antes de adoptarlo.", "Criterio"),
]


def saltos(d, medido=None):
    """Lista de saltos de arquitectura que este equipo tiene, con lo que la skill hace con cada uno."""
    c = capacidades(d, medido)
    out = []
    for si, modulo, salto, uso, nivel in REGLAS:
        try:
            ok = si(c)
        except (TypeError, KeyError, AttributeError):
            ok = False
        if ok:
            out.append({"modulo": modulo, "salto": salto, "uso": uso(c) if callable(uso) else uso, "nivel": nivel})
    return out


def codificaciones_paralelas(d, medido):
    """Cuantas codificaciones por hardware a la vez: lo medido manda; si no, la referencia de Apple, marcada."""
    m = (medido.get("video") or {}).get("codificaciones_paralelas")
    if isinstance(m, dict) and m.get("estado") in ("gana", "adoptado") and m.get("valor"):
        return {"valor": m["valor"], "origen": "medido (%s)" % m.get("fecha", "sin fecha"), "escalado": m.get("escalado")}
    ref = referencia_apple(capacidades(d)["chip"])
    out = {"valor": None, "origen": "sin medir", "medir": "medir.py paralelo --archivo <video> --registrar"}
    if ref and ref.get("enc"):
        out["referencia"] = "Apple publica %d motor(es) de codificacion de video en este chip" % ref["enc"]
    return out


def decodificacion_por_codec(d, usa_hw):
    """Para cada codec que lee ffmpeg: 'videotoolbox' si el motor lo decodifica, el metodo elegido es hardware y
    este ffmpeg ya lo soporta; si no, 'cpu' con el motivo."""
    dec = (d.get("video") or {}).get("decodificadores_hw")
    if dec is None:
        return None
    c = capacidades(d)
    out = {}
    for k in CODECS_FFMPEG:
        if k not in dec:
            continue
        minimo = FFMPEG_MINIMO.get(k)
        if not dec[k]:
            out[k] = "cpu"
        elif not usa_hw:
            out[k] = "cpu (metodo medido: CPU)"
        elif minimo and (c["ffmpeg_mayor"] is None or c["ffmpeg_mayor"] < minimo):
            out[k] = "cpu (el chip puede; hace falta ffmpeg %d.0 o posterior, este es %s)" % (minimo, c["ffmpeg_version"] or "desconocido")
        else:
            out[k] = "videotoolbox"
    return out
