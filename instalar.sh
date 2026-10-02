#!/usr/bin/env bash
# Instala claudemon en Mac o Linux: copia el programa a ~/.local/bin y crea el comando «claudemon».
# Uso:  bash instalar.sh
set -e
AQUI="$(cd "$(dirname "$0")" && pwd)"
DESTINO="${CLAUDEMON_BIN:-$HOME/.local/bin}"

# 1) Python 3.8 o más nuevo
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "✗ No encontré Python 3.8 o más nuevo."
  echo "  Mac:   brew install python     (o bajalo de https://www.python.org/downloads/)"
  echo "  Linux: sudo apt install python3   (o el gestor de tu distribución)"
  exit 1
fi
echo "✓ Python: $($PY --version)"

# 2) copiar el programa y crear el comando
mkdir -p "$DESTINO"
cp "$AQUI/claudemon.py" "$DESTINO/claudemon.py"
printf '#!/bin/sh\nexec %s "%s/claudemon.py" "$@"\n' "$(command -v $PY)" "$DESTINO" > "$DESTINO/claudemon"
chmod +x "$DESTINO/claudemon" "$DESTINO/claudemon.py"
echo "✓ Instalado en $DESTINO/claudemon"

# 3) psutil (solo para la pantalla en vivo)
if "$PY" -c 'import psutil' 2>/dev/null; then
  echo "✓ psutil ya está instalado"
else
  echo
  echo "La pantalla en vivo necesita la librería psutil (los informes andan sin ella)."
  if [ -t 0 ] && [ -z "$CLAUDEMON_SIN_PREGUNTAS" ]; then
    printf "¿La instalo ahora? [S/n] "; read -r r
  else
    r="n"
  fi
  case "$r" in
    n|N) echo "  Después, cuando quieras:  $PY -m pip install --user psutil" ;;
    *)
      if "$PY" -m pip install --user psutil 2>/dev/null || "$PY" -m pip install --user --break-system-packages psutil 2>/dev/null; then
        echo "✓ psutil instalado"
      else
        echo "✗ No pude instalar psutil. Probá:  $PY -m pip install --user psutil   (o con pipx / un entorno virtual)"
      fi ;;
  esac
fi

# 4) ¿está la carpeta en el PATH?
case ":$PATH:" in
  *":$DESTINO:"*) ;;
  *)
    echo
    echo "⚠ $DESTINO no está en tu PATH. Agregá esta línea a ~/.zshrc (Mac) o ~/.bashrc (Linux) y abrí una terminal nueva:"
    echo "    export PATH=\"$DESTINO:\$PATH\""
    ;;
esac

echo
echo "Listo. Probalo con:   claudemon demo"
echo "Ayuda:                claudemon ayuda"
