#!/usr/bin/env python3
"""Saltos de arquitectura de Apple Silicon: que trae este chip y que hace la skill con cada cosa.

Se decide por lo que el diagnostico DETECTA (familia Metal, codecs por hardware, extensiones de la CPU,
nucleos del Neural Engine), no por el nombre del chip: un chip nuevo con las mismas capacidades recibe
las mismas reglas sin tocar nada, y uno con una familia Metal mas nueva que las conocidas se marca para
medir en vez de suponer.

Orden de confianza: lo medido en el equipo (perfil-medido.json) > lo detectado > la tabla de Apple
(assets/chips_apple.json), que solo sirve de referencia para lo que ninguna API dice, como cuantos motores
de codificacion de video hay.

Solo biblioteca estandar. Lo usa perfil.py; no se corre solo.
"""
from __future__ import annotations

import json
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
TABLA_APPLE = os.path.join(os.path.dirname(AQUI), "assets", "chips_apple.json")
FAMILIA_CONOCIDA = 10  # la familia Metal mas nueva con reglas propias; una mayor se marca para medir


def capacidades(d):
    """Lo que el diagnostico detecto, en una forma comoda para las reglas."""
    gpu = d.get("gpu") or {}
    metal = gpu.get("metal") or {}
    m = re.search(r"(\d+)", metal.get("familia_apple_maxima") or "")
    vid = d.get("video") or {}
    cod = (vid.get("codificadores") or {}).get("codecs_por_hardware")
    cpu = d.get("cpu") or {}
    return {
        "chip": cpu.get("marca"),
        "familia": int(m.group(1)) if m else None,
        "metal": metal.get("familias_metal") or [],
        "codifica_hw": cod,                              # None = sin dato (falta Swift)
        "decodifica_hw": vid.get("decodificadores_hw"),  # None = sin dato
        "extensiones": cpu.get("extensiones") or [],
        "ne_nucleos": (d.get("neural_engine") or {}).get("nucleos"),
        "gpu_nucleos": gpu.get("nucleos"),
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
    nombre = re.sub(r"^Apple\s+", "", chip.strip())
    return (tabla_apple().get("chips") or {}).get(nombre)


# Cada regla: (si, modulo, salto, que hace la skill, nivel de evidencia). `si` recibe capacidades().
REGLAS = [
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("h264") and c["decodifica_hw"].get("hevc"),
     "Motor de video", "H.264 y HEVC por hardware (desde M1)",
     "Codifica con h264_videotoolbox y lee con -hwaccel videotoolbox; bitrate fijo y -allow_sw 0.", "Oficial + medido"),
    (lambda c: c["codifica_hw"] is not None and ("apcn" in c["codifica_hw"] or "ap4h" in c["codifica_hw"]),
     "Motor de video", "ProRes por hardware (desde M1 Pro y M1 Max; en los chips base desde M2)",
     "Intermedios de edicion en ProRes con prores_videotoolbox en vez de prores_ks en la CPU.", "Oficial (detectado)"),
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("av1"),
     "Motor de video", "Decodificacion AV1 por hardware (desde M3)",
     "Los videos AV1 se leen con -hwaccel videotoolbox; sin esto, AV1 se decodifica en la CPU.", "Oficial (detectado)"),
    (lambda c: c["decodifica_hw"] is not None and c["decodifica_hw"].get("prores_raw"),
     "Motor de video", "ProRes RAW por hardware",
     "Se informa: lo aprovechan Final Cut Pro y las apps de Apple; la skill no lo usa todavia.", "Oficial (detectado)"),
    (lambda c: c["familia"] is not None and c["familia"] >= 9,
     "GPU", "Dynamic Caching, sombreado de mallas y trazado de rayos por hardware (desde M3, familia Metal apple9)",
     "Dynamic Caching es automatico: nada que configurar. El trazado de rayos por hardware lo usa Blender Cycles "
     "con Metal; Chrome, Remotion y ffmpeg no lo usan.", "Oficial"),
    (lambda c: c["familia"] is not None and c["familia"] >= 10,
     "GPU", "Neural Accelerators en cada nucleo de la GPU (desde M5)",
     "La IA en la GPU puede ir mucho mas rapido si la biblioteca usa los tensores de Metal 4. Para Whisper, mide "
     "Metal frente a Core ML en este equipo antes de cambiar el backend.", "Oficial; uso por herramienta: ver arquitectura.md"),
    (lambda c: "metal4" in c["metal"],
     "GPU", "Metal 4 disponible (API de tensores para IA en la GPU)",
     "Se informa: lo aprovechan las bibliotecas que lo implementan, no se activa desde la skill.", "Oficial (detectado)"),
    (lambda c: "FEAT_SME2" in c["extensiones"] or "FEAT_SME" in c["extensiones"],
     "CPU", "Extension de matrices SME (desde M4)",
     "Automatico: lo usa Accelerate y lo que se apoya en Accelerate (por ejemplo whisper.cpp en la CPU). Nada que configurar.",
     "Oficial (detectado)"),
    (lambda c: bool(c["ne_nucleos"]),
     "Neural Engine", "Neural Engine detectado",
     "Recortes de personas con Vision y modelos de Core ML lo usan solos. No instalar modelos de Python para recortar.",
     "Oficial (detectado)"),
    (lambda c: c["familia"] is not None and c["familia"] > FAMILIA_CONOCIDA,
     "GPU", "Familia Metal mas nueva que las que la skill conoce",
     "Se aplican las reglas comunes y conviene medir cada metodo con medir.py antes de adoptarlo.", "Criterio"),
]


def saltos(d):
    """Lista de saltos de arquitectura que este equipo tiene, con lo que la skill hace con cada uno."""
    c = capacidades(d)
    out = []
    for si, modulo, salto, uso, nivel in REGLAS:
        try:
            ok = si(c)
        except (TypeError, KeyError, AttributeError):
            ok = False
        if ok:
            out.append({"modulo": modulo, "salto": salto, "uso": uso, "nivel": nivel})
    return out


def codificaciones_paralelas(d, medido):
    """Cuantas codificaciones por hardware a la vez: lo medido manda; si no, la referencia de Apple, marcada."""
    m = (medido.get("video") or {}).get("codificaciones_paralelas")
    if isinstance(m, dict) and m.get("estado") in ("gana", "adoptado") and m.get("valor"):
        return {"valor": m["valor"], "origen": "medido (%s)" % m.get("fecha", "sin fecha"), "escalado": m.get("escalado")}
    ref = referencia_apple(capacidades(d)["chip"])
    if ref and ref.get("enc"):
        return {"valor": None, "origen": "sin medir",
                "referencia": "Apple publica %d motor(es) de codificacion de video en este chip" % ref["enc"],
                "medir": "medir.py paralelo --archivo <video> --registrar"}
    return {"valor": None, "origen": "sin medir", "medir": "medir.py paralelo --archivo <video> --registrar"}


CODECS_FFMPEG = ("h264", "hevc", "prores", "prores_4444", "av1", "vp9")  # los que ffmpeg lee con -hwaccel videotoolbox


def decodificacion_por_codec(d, usa_hw):
    """Para cada codec que lee ffmpeg: hardware si el motor lo decodifica y el metodo medido o por formula es hardware."""
    dec = (d.get("video") or {}).get("decodificadores_hw")
    if dec is None:
        return None
    return {k: ("videotoolbox" if (dec.get(k) and usa_hw) else "cpu") for k in CODECS_FFMPEG if k in dec}
