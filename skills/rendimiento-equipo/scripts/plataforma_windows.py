#!/usr/bin/env python3
"""Lecturas del equipo en Windows para diagnosticar.py y medir.py.

Solo biblioteca estandar: ctypes (API de Windows), winreg (registro) y PowerShell con CIM, que
viene con Windows. No instala nada, no usa red y no cambia nada del sistema. Cada lectura
devuelve lo que pudo y deja un aviso si algo falla: el diagnostico no se cae por una consulta.

Lo que Windows no expone de forma estandar se deja en None y se dice: presion de memoria con
niveles (como la de macOS) y estado termico.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import struct
import subprocess
from ctypes import wintypes

RELACION_NUCLEO = 0  # RelationProcessorCore de GetLogicalProcessorInformationEx
CLASE_ADAPTADORES = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
FABRICANTES = {"10DE": "NVIDIA", "8086": "Intel", "1002": "AMD", "1022": "AMD", "5143": "Qualcomm",
               "QCOM": "Qualcomm", "1414": "Microsoft"}


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def powershell(script, timeout=60):
    """Corre PowerShell sin perfil y devuelve su salida JSON ya leida, o None si falla."""
    pre = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'SilentlyContinue'; "
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", pre + script]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _registro(ruta, valor):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta) as k:
            v = winreg.QueryValueEx(k, valor)[0]
            return v.strip() if isinstance(v, str) else v
    except OSError:
        return None


# ---------------------------------------------------------------- CPU

def leer_cpu(avisos):
    """Nucleos por clase de eficiencia (GetLogicalProcessorInformationEx).

    Windows numera la clase de eficiencia de cada nucleo: mas alta, mas rendimiento. Con una sola
    clase todos los nucleos son iguales. Con varias, la mas alta se llama "Performance" y las demas
    "Efficiency (clase N)": asi perfil.py solo reparte Remotion entre los mas rapidos.
    """
    clases = {}
    try:
        k32 = _kernel32()
        k32.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        k32.GetLogicalProcessorInformationEx.restype = wintypes.BOOL
        largo = wintypes.DWORD(0)
        k32.GetLogicalProcessorInformationEx(RELACION_NUCLEO, None, ctypes.byref(largo))
        buf = ctypes.create_string_buffer(largo.value)
        if not k32.GetLogicalProcessorInformationEx(RELACION_NUCLEO, buf, ctypes.byref(largo)):
            raise OSError(ctypes.get_last_error())
        datos, off = buf.raw, 0
        ancho = ctypes.sizeof(ctypes.c_void_p)            # KAFFINITY mide lo que un puntero
        paso, fmt = (16, "<Q") if ancho == 8 else (12, "<I")
        while off < largo.value:
            relacion, tam = struct.unpack_from("<II", datos, off)
            if relacion == RELACION_NUCLEO:
                clase = datos[off + 9]
                grupos = struct.unpack_from("<H", datos, off + 30)[0]
                logicos = sum(bin(struct.unpack_from(fmt, datos, off + 32 + g * paso)[0]).count("1") for g in range(grupos))
                c = clases.setdefault(clase, [0, 0])
                c[0] += 1
                c[1] += logicos
            off += tam
    except (OSError, AttributeError, struct.error) as e:
        avisos.append("No se pudieron leer los nucleos por clase (%s): se usa el total de procesadores logicos." % e)
    orden = sorted(clases, reverse=True)
    niveles = []
    for i, clase in enumerate(orden):
        nombre = "Performance" if i == 0 else "Efficiency (clase %d)" % clase
        niveles.append({"indice": i, "nombre": nombre, "nucleos_fisicos": clases[clase][0],
                        "nucleos_logicos": clases[clase][1], "cpus_por_l2": None, "clase_eficiencia": clase})
    fabricante = _registro(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer")
    producto = _registro(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName")
    return {
        "marca": _registro(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString"),
        "modelo": " ".join(x for x in (fabricante, producto) if x) or None,
        "niveles": niveles,  # el nivel 0 es el de clase mas alta; no se asume cuantas clases hay
        "logicalcpu": os.cpu_count(),
        "pagesize": None,
    }


# ---------------------------------------------------------------- memoria y energia

class _EstadoMemoria(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def leer_memoria(avisos):
    """Memoria fisica y carga (GlobalMemoryStatusEx). El commit es memoria comprometida, no swap."""
    e = _EstadoMemoria()
    e.dwLength = ctypes.sizeof(_EstadoMemoria)
    try:
        if not _kernel32().GlobalMemoryStatusEx(ctypes.byref(e)):
            raise OSError(ctypes.get_last_error())
    except (OSError, AttributeError) as err:
        avisos.append("GlobalMemoryStatusEx fallo: %s" % err)
        return {"memsize": None}
    mb = 1024 ** 2
    return {
        "memsize": e.ullTotalPhys,
        "disponible_mb": round(e.ullAvailPhys / mb),
        "libre_porcentaje": round(e.ullAvailPhys * 100 / e.ullTotalPhys) if e.ullTotalPhys else None,
        "carga_porcentaje": e.dwMemoryLoad,
        "commit_limite_mb": round(e.ullTotalPageFile / mb),
        "commit_usado_mb": round((e.ullTotalPageFile - e.ullAvailPageFile) / mb),
    }


class _EstadoEnergia(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def leer_energia(avisos):
    """Enchufe, bateria y ahorro de energia de Windows (GetSystemPowerStatus)."""
    s = _EstadoEnergia()
    try:
        if not _kernel32().GetSystemPowerStatus(ctypes.byref(s)):
            raise OSError(ctypes.get_last_error())
    except (OSError, AttributeError) as err:
        avisos.append("GetSystemPowerStatus fallo: %s" % err)
        return None
    hay_bateria = s.BatteryFlag != 255 and not (s.BatteryFlag & 128)
    return {
        "enchufado": None if s.ACLineStatus == 255 else s.ACLineStatus == 1,
        "bateria": hay_bateria,
        "bateria_porcentaje": s.BatteryLifePercent if hay_bateria and s.BatteryLifePercent != 255 else None,
        "ahorro_energia": s.SystemStatusFlag == 1,
    }


# ---------------------------------------------------------------- GPU, NPU, paginacion y sistema

def _vram_por_nombre():
    """VRAM por adaptador desde el registro: Win32_VideoController la corta en 4 GB."""
    import winreg
    res = {}
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CLASE_ADAPTADORES)
    except OSError:
        return res
    with k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            if not re.fullmatch(r"\d{4}", sub):
                continue
            try:
                with winreg.OpenKey(k, sub) as s:
                    nombre = winreg.QueryValueEx(s, "DriverDesc")[0]
                    for valor in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            v = winreg.QueryValueEx(s, valor)[0]
                        except OSError:
                            continue
                        if isinstance(v, bytes):
                            v = int.from_bytes(v[:8], "little")
                        if isinstance(v, int) and v > 0:
                            res[nombre] = max(res.get(nombre, 0), v)
                            break
            except OSError:
                continue
    return res


def leer_sistema(avisos):
    """Una sola consulta CIM: adaptadores de video, NPU, archivo de paginacion y version de Windows."""
    script = (
        "$r = [ordered]@{}; "
        "$r.gpus = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterCompatibility, DriverVersion, AdapterRAM, PNPDeviceID, Status); "
        "$r.npus = @(Get-CimInstance Win32_PnPEntity -Filter \"PNPClass='ComputeAccelerator'\" | Select-Object Name, Status, PNPDeviceID); "
        "$r.paginacion = @(Get-CimInstance Win32_PageFileUsage | Select-Object Name, AllocatedBaseSize, CurrentUsage, PeakUsage); "
        "$r.so = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber; "
        "$r | ConvertTo-Json -Depth 4 -Compress"
    )
    d = powershell(script)
    if not isinstance(d, dict):
        avisos.append("La consulta CIM de PowerShell fallo: faltan GPU, NPU y archivo de paginacion.")
        return {"gpus": [], "npus": [], "paginacion": [], "so": None}
    for k in ("gpus", "npus", "paginacion"):
        v = d.get(k)
        d[k] = v if isinstance(v, list) else ([v] if v else [])
    return d


def adaptadores(sistema):
    vram = _vram_por_nombre()
    lista = []
    for g in sistema.get("gpus", []):
        nombre = (g.get("Name") or "").strip()
        m = re.search(r"VEN_([0-9A-Z]{4})", g.get("PNPDeviceID") or "", re.I)
        fabricante = FABRICANTES.get(m.group(1).upper()) if m else None
        fabricante = fabricante or (g.get("AdapterCompatibility") or None)
        virtual = fabricante == "Microsoft" or bool(re.search(r"Basic Display|Basic Render|Remote Display|Hyper-V", nombre, re.I))
        bytes_vram = vram.get(nombre) or g.get("AdapterRAM")
        lista.append({"nombre": nombre or None, "fabricante": fabricante, "controlador": g.get("DriverVersion"),
                      "vram_mb": round(bytes_vram / 1024 ** 2) if isinstance(bytes_vram, int) and bytes_vram > 0 else None,
                      "virtual": virtual, "estado": g.get("Status")})
    return lista


def paginacion(sistema):
    """Archivo de paginacion de Windows en MB: es lo que mas se parece al swap de macOS."""
    p = sistema.get("paginacion") or []
    if not p:
        return None
    total = sum(x.get("AllocatedBaseSize") or 0 for x in p)
    usado = sum(x.get("CurrentUsage") or 0 for x in p)
    return {"total_mb": total, "usado_mb": usado, "libre_mb": total - usado,
            "pico_mb": sum(x.get("PeakUsage") or 0 for x in p)}


# ---------------------------------------------------------------- procesos

def _normalizar(cmd, nombre):
    """Lleva una linea de comandos de Windows a la forma que reconocen los patrones de diagnosticar.py.

    Barras normales, sin comillas ni .exe en el ejecutable, y los espacios de su ruta como guion bajo.
    """
    c = (cmd or nombre or "").strip()
    if c.startswith('"'):
        fin = c.find('"', 1)
        exe, resto = (c[1:fin], c[fin + 1:]) if fin > 0 else (c[1:], "")
    else:
        exe, sep, resto = c.partition(" ")
        resto = sep + resto
    exe = re.sub(r"\.(exe|cmd|bat)$", "", exe.replace("\\", "/"), flags=re.I).replace(" ", "_")
    return exe + resto.replace("\\", "/")


def a_etime(segundos):
    """Segundos a la forma de ps: [[dd-]hh:]mm:ss."""
    d, r = divmod(max(0, int(segundos)), 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return ("%d-" % d if d else "") + ("%02d:" % h if d or h else "") + "%02d:%02d" % (m, s)


def listar_procesos():
    """Tabla pid -> {pid, ppid, etime, cmd} con la misma forma que en macOS."""
    script = (
        "$ahora = Get-Date; "
        "@(Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{ "
        "pid = $_.ProcessId; ppid = $_.ParentProcessId; nombre = $_.Name; cmd = $_.CommandLine; "
        "edad = $(if ($_.CreationDate) { [int](($ahora - $_.CreationDate).TotalSeconds) } else { 0 }) } }) "
        "| ConvertTo-Json -Compress -Depth 2"
    )
    datos = powershell(script) or []
    if isinstance(datos, dict):
        datos = [datos]
    tabla = {}
    for p in datos:
        try:
            pid = int(p["pid"])
        except (KeyError, TypeError, ValueError):
            continue
        tabla[pid] = {"pid": pid, "ppid": int(p.get("ppid") or 0), "etime": a_etime(p.get("edad") or 0),
                      "cmd": _normalizar(p.get("cmd"), p.get("nombre"))}
    return tabla


# ---------------------------------------------------------------- tiempo de CPU para medir.py

CREAR_SUSPENDIDO = 0x00000004
CONTABILIDAD_BASICA = 1  # JobObjectBasicAccountingInformation


class _Contabilidad(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


def lanzar_contado(cmd, **kw):
    """subprocess.Popen dentro de un Job Object, para que el tiempo de CPU cuente tambien a los hijos.

    Hace falta porque el ffmpeg de Chocolatey o Scoop es un atajo que lanza el ffmpeg real como hijo:
    sin esto se mediria solo el atajo. El proceso nace suspendido, entra al trabajo y recien ahi arranca,
    asi ningun hijo se escapa. Si algo falla, cae a un Popen normal.
    """
    try:
        k32 = _kernel32()
        ntdll = ctypes.WinDLL("ntdll")
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        trabajo = k32.CreateJobObjectW(None, None)
    except (OSError, AttributeError):
        return subprocess.Popen(cmd, **kw)
    if not trabajo:
        return subprocess.Popen(cmd, **kw)
    p = subprocess.Popen(cmd, creationflags=CREAR_SUSPENDIDO, **kw)
    asignado = bool(k32.AssignProcessToJobObject(trabajo, wintypes.HANDLE(int(p._handle))))
    if ntdll.NtResumeProcess(wintypes.HANDLE(int(p._handle))) != 0:  # no arranco: no dejarlo colgado
        p.kill()
        k32.CloseHandle(trabajo)
        return subprocess.Popen(cmd, **kw)
    if asignado:
        p._trabajo = trabajo
    else:
        k32.CloseHandle(trabajo)
    return p


def tiempo_cpu(proceso):
    """Segundos de CPU (usuario + nucleo) de un proceso ya terminado y de sus hijos. None si no se puede.

    Con lanzar_contado lee el Job Object (incluye hijos); si no, solo el proceso (GetProcessTimes).
    """
    trabajo = getattr(proceso, "_trabajo", None)
    if trabajo:
        k32 = _kernel32()
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        k32.QueryInformationJobObject.restype = wintypes.BOOL
        info = _Contabilidad()
        ok = k32.QueryInformationJobObject(trabajo, CONTABILIDAD_BASICA, ctypes.byref(info), ctypes.sizeof(info), None)
        k32.CloseHandle(trabajo)
        proceso._trabajo = None
        if ok:
            return round((info.TotalUserTime + info.TotalKernelTime) / 1e7, 2)
    ft = [wintypes.FILETIME() for _ in range(4)]
    try:
        k32 = _kernel32()
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        if not k32.GetProcessTimes(wintypes.HANDLE(int(proceso._handle)), *[ctypes.byref(f) for f in ft]):
            return None
    except (OSError, AttributeError, TypeError):
        return None

    def seg(f):
        return ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7
    return round(seg(ft[2]) + seg(ft[3]), 2)
