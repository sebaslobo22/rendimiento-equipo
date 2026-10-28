// capacidades_macos.swift
// Consulta en tiempo de ejecucion lo que el chip realmente ofrece (Metal, VideoToolbox,
// Neural Engine, estado termico, bajo consumo) y lo imprime como JSON en stdout.
// Se ejecuta con: swift capacidades_macos.swift   (lo llama diagnosticar.py con tiempo limite)
// No instala nada, no usa red y no escribe archivos. Cada bloque falla por separado:
// si una API no existe en este macOS, el resto sigue y el motivo queda en "avisos".
import Foundation
import CoreGraphics
import Metal
import VideoToolbox
import CoreML

var salida: [String: Any] = [:]
var avisos: [String] = []

func fourcc(_ t: UInt32) -> String {
    let bytes = [UInt8((t >> 24) & 255), UInt8((t >> 16) & 255), UInt8((t >> 8) & 255), UInt8(t & 255)]
    // Los formatos sin comprimir usan numeros pequenos en lugar de 4 letras: se dejan como numero.
    if bytes.allSatisfy({ $0 >= 32 && $0 < 127 }), let s = String(bytes: bytes, encoding: .ascii) { return s }
    return String(t)
}
func codigo(_ s: String) -> UInt32 {
    var v: UInt32 = 0
    for b in s.utf8 { v = (v << 8) | UInt32(b) }
    return v
}

// ---- Metal -------------------------------------------------------------------------
if let dev = MTLCreateSystemDefaultDevice() {
    var metal: [String: Any] = [
        "nombre": dev.name,
        "hasUnifiedMemory": dev.hasUnifiedMemory,
        "recommendedMaxWorkingSetSize": dev.recommendedMaxWorkingSetSize,
        "maxBufferLength": dev.maxBufferLength,
        "currentAllocatedSize": dev.currentAllocatedSize,
    ]
    // Familias Apple: 1001... (apple1...). Los rawValue desconocidos devuelven nil, asi que
    // recorrer un rango amplio es seguro y no obliga a nombrar chips.
    var mejor = 0
    var soportadas: [String] = []
    for raw in 1001...1020 {
        if let fam = MTLGPUFamily(rawValue: raw), dev.supportsFamily(fam) {
            soportadas.append("apple\(raw - 1000)")
            mejor = raw - 1000
        }
    }
    metal["familias_apple"] = soportadas
    metal["familia_apple_maxima"] = mejor > 0 ? "apple\(mejor)" : NSNull()
    // Familias de version de Metal (metal3 = 5001, metal4 = 5002...). Por numero y no por nombre:
    // un SDK viejo no conoce .metal4 y el script dejaria de compilar.
    var versiones: [String] = []
    for raw in 5001...5010 {
        if let fam = MTLGPUFamily(rawValue: raw), dev.supportsFamily(fam) { versiones.append("metal\(raw - 4998)") }
    }
    metal["familias_metal"] = versiones
    // Que la API exista no prueba que haya hardware dedicado: en M1 y M2 el trazado de rayos corre en
    // los nucleos normales. El salto se lee en la familia (apple9 en adelante), no aqui.
    metal["supportsRaytracing"] = dev.supportsRaytracing
    metal["supportsRaytracingFromRender"] = dev.supportsRaytracingFromRender
    salida["metal"] = metal
} else {
    avisos.append("Metal: no hay dispositivo Metal disponible")
    salida["metal"] = NSNull()
}

// ---- VideoToolbox ------------------------------------------------------------------
var listaCodificadores: CFArray?
let st = VTCopyVideoEncoderList(nil, &listaCodificadores)
if st == noErr, let arr = listaCodificadores as? [[String: Any]] {
    var fourccHw = Set<String>()
    var nombresHw = Set<String>()
    var fourccTodos = Set<String>()
    var nHw = 0
    for d in arr {
        let esHw = (d[kVTVideoEncoderList_IsHardwareAccelerated as String] as? Bool) ?? false
        var cc = "?"
        if let t = d[kVTVideoEncoderList_CodecType as String] as? UInt32 { cc = fourcc(t) }
        else if let t = d[kVTVideoEncoderList_CodecType as String] as? Int { cc = fourcc(UInt32(truncatingIfNeeded: t)) }
        let nombre = (d[kVTVideoEncoderList_CodecName as String] as? String) ?? "?"
        fourccTodos.insert(cc)
        if esHw { fourccHw.insert(cc); nombresHw.insert("\(nombre) (\(cc))"); nHw += 1 }
    }
    salida["codificadores"] = [
        "total": arr.count,
        "por_hardware": nHw,
        "codecs_por_hardware": fourccHw.sorted(),
        "nombres_por_hardware": nombresHw.sorted(),
        "codecs_total": fourccTodos.sorted(),
    ]
} else {
    avisos.append("VideoToolbox: VTCopyVideoEncoderList fallo (estado \(st))")
    salida["codificadores"] = NSNull()
}

let decodificadores: [(String, String)] = [
    ("h264", "avc1"), ("hevc", "hvc1"), ("prores", "apcn"), ("prores_4444", "ap4h"),
    ("prores_raw", "aprn"), ("av1", "av01"), ("vp9", "vp09"),
]
var dec: [String: Bool] = [:]
for (nombre, cc) in decodificadores {
    dec[nombre] = VTIsHardwareDecodeSupported(CMVideoCodecType(codigo(cc)))
}
salida["decodificadores_hw"] = dec

// ---- Neural Engine -----------------------------------------------------------------
if #available(macOS 14.0, *) {
    var ne: [String: Any] = ["disponible": false, "nucleos": 0]
    for d in MLComputeDevice.allComputeDevices {
        if case .neuralEngine(let motor) = d {
            ne = ["disponible": true, "nucleos": motor.totalCoreCount]
        }
    }
    salida["neural_engine"] = ne
} else {
    avisos.append("Neural Engine: MLComputeDevice requiere macOS 14 o superior")
    salida["neural_engine"] = NSNull()
}

// ---- Termico y energia -------------------------------------------------------------
switch ProcessInfo.processInfo.thermalState {
case .nominal: salida["termico"] = "nominal"
case .fair: salida["termico"] = "fair"
case .serious: salida["termico"] = "serious"
case .critical: salida["termico"] = "critical"
@unknown default: salida["termico"] = "desconocido"
}
salida["bajo_consumo"] = ProcessInfo.processInfo.isLowPowerModeEnabled
salida["avisos"] = avisos

if let datos = try? JSONSerialization.data(withJSONObject: salida, options: [.sortedKeys]),
   let texto = String(data: datos, encoding: .utf8) {
    print(texto)
} else {
    FileHandle.standardError.write("capacidades_macos: no se pudo serializar a JSON\n".data(using: .utf8)!)
    exit(1)
}
