#!/bin/bash
export PATH="/c/Program\ Files/nodejs:/c/Users/Angus/AppData/Roaming/npm:$PATH"
NODE="/c/Program Files/nodejs/node.exe"
CARDEX_DIR="$(cd "$(dirname "$0")/../cardex" && pwd)"
cd "$CARDEX_DIR/apps/web" || exit 1
NEXT_BIN="$CARDEX_DIR/node_modules/.pnpm/next@15.5.14_react-dom@19.2.4_react@19.2.4__react@19.2.4/node_modules/next/dist/bin/next"
"$NODE" "$NEXT_BIN" dev --turbopack
