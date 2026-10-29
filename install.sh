#!/usr/bin/env bash
# Enlaza la skill rendimiento-equipo en las carpetas que leen los agentes.
# No copia archivos, no instala dependencias y no usa la red.
set -euo pipefail

NOMBRE="rendimiento-equipo"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ORIGEN="$RAIZ/skills/$NOMBRE"
RESPALDOS="$RAIZ/.respaldos"
DESTINO_CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/$NOMBRE"
DESTINO_AGENTES="$HOME/.agents/skills/$NOMBRE"

destino="ambos"
prueba=0
desinstalar=0

ayuda() {
  cat <<EOF
Uso: ./install.sh [opciones]

Enlaza skills/$NOMBRE en:
  Claude Code  $DESTINO_CLAUDE
  Codex        $DESTINO_AGENTES

Opciones:
  --destino ambos|claude|agentes   dónde enlazar (por defecto: ambos)
  --prueba                         muestra lo que haría, sin cambiar nada
  --desinstalar                    quita los enlaces que apuntan a este repositorio
  --ayuda                          muestra esta ayuda

Si ya existe algo con ese nombre y no es este repositorio, se mueve a
$RESPALDOS antes de enlazar. Nada se borra.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --destino)
      [ $# -ge 2 ] || { echo "--destino necesita un valor: ambos, claude o agentes" >&2; exit 2; }
      destino="$2"; shift 2 ;;
    --prueba) prueba=1; shift ;;
    --desinstalar) desinstalar=1; shift ;;
    -h|--ayuda|--help) ayuda; exit 0 ;;
    *) echo "Opción desconocida: $1 (usa --ayuda)" >&2; exit 2 ;;
  esac
done

# Claude primero: su enlace puede pasar por el de ~/.agents, y al desinstalar
# hay que quitarlo antes de que ese otro deje de existir.
case "$destino" in
  ambos)   destinos=("claude:$DESTINO_CLAUDE" "agentes:$DESTINO_AGENTES") ;;
  claude)  destinos=("claude:$DESTINO_CLAUDE") ;;
  agentes) destinos=("agentes:$DESTINO_AGENTES") ;;
  *) echo "--destino debe ser ambos, claude o agentes" >&2; exit 2 ;;
esac

[ -f "$ORIGEN/SKILL.md" ] || { echo "No encuentro $ORIGEN/SKILL.md: corre el instalador desde el repositorio." >&2; exit 1; }

hacer() { if [ "$prueba" = 1 ]; then echo "         (prueba) $*"; else "$@"; fi; }

# Verdadero si la ruta, siguiendo enlaces, termina en la carpeta de este repositorio.
apunta_al_origen() { [ -d "$1" ] && [ "$(cd "$1" && pwd -P)" = "$ORIGEN" ]; }

enlazar() {
  local etiqueta="$1" dest="$2"
  if apunta_al_origen "$dest"; then
    echo "ok       $dest (ya apunta a este repositorio)"
    return
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    local resp="$RESPALDOS/$etiqueta-$(date +%Y%m%d-%H%M%S)"
    echo "respalda $dest -> $resp"
    hacer mkdir -p "$RESPALDOS"
    hacer mv "$dest" "$resp"
  fi
  echo "enlaza   $dest -> $ORIGEN"
  hacer mkdir -p "$(dirname "$dest")"
  hacer ln -s "$ORIGEN" "$dest"
}

desenlazar() {
  local dest="$2"
  if [ -L "$dest" ] && apunta_al_origen "$dest"; then
    echo "quita    $dest"
    hacer rm "$dest"
  elif [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "deja     $dest (no es un enlace a este repositorio)"
  else
    echo "nada     $dest (no existe)"
  fi
}

if [ "$desinstalar" = 1 ]; then
  for d in "${destinos[@]}"; do desenlazar "${d%%:*}" "${d#*:}"; done
  echo
  echo "Las mediciones de cada equipo siguen en ~/.local/share/$NOMBRE/ y no se tocan."
  exit 0
fi

for d in "${destinos[@]}"; do enlazar "${d%%:*}" "${d#*:}"; done

echo
command -v python3 >/dev/null 2>&1 || echo "Aviso: falta python3. Los scripts de la skill lo necesitan."
if [ "$(uname -s)" != "Darwin" ]; then
  echo "Aviso: este sistema no es macOS. La skill responde «sin soporte medido todavía» y no recomienda nada."
elif ! xcode-select -p >/dev/null 2>&1; then
  echo "Aviso: sin las herramientas de línea de comandos de Xcode el diagnóstico no ve Metal, los motores de video,"
  echo "       el Neural Engine ni el estado térmico. Se instalan con: xcode-select --install"
fi
[ "$prueba" = 1 ] && { echo "Prueba terminada: no se cambió nada."; exit 0; }
echo "Listo. Abre una sesión nueva de Claude Code o Codex para que la detecten."
echo "Para ver lo que recomienda en este equipo:"
echo "  python3 \"$ORIGEN/scripts/perfil.py\" --formato texto"
calibrar="$ORIGEN/scripts/calibrar.py"
if [ "$(uname -s)" = "Darwin" ] && command -v python3 >/dev/null 2>&1 && [ -t 0 ] && [ -t 1 ]; then
  echo
  echo "Calibrar mide este equipo: qué modelo de dictado de OpenWhispr y qué método de video le convienen."
  echo "Usa solo lo que ya tienes: no descarga nada ni cambia OpenWhispr. Tarda de 1 a 3 minutos."
  printf "¿Calibrar ahora? [s/N] "
  read -r respuesta || respuesta=""
  case "$respuesta" in
    s|S|si|sí|Si|Sí) python3 "$calibrar" ;;
    *) echo "Cuando quieras: python3 \"$calibrar\"" ;;
  esac
else
  echo "Para calibrar este equipo: python3 \"$calibrar\""
fi
