#!/usr/bin/env bash
# ==============================================================================
# Helper: Inicialización de Red Docker idci_network
# ==============================================================================
set -e

NETWORK_NAME="idci_network"

if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "-> Creando red Docker '$NETWORK_NAME'..."
    docker network create "$NETWORK_NAME"
    echo "-> ✅ Red '$NETWORK_NAME' creada exitosamente."
else
    echo "-> ✅ Red Docker '$NETWORK_NAME' ya existe y está lista."
fi
