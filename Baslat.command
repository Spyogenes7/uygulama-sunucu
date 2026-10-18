#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================================="
echo "  MedPaper AI — Tıbbi Makale, Metrik & Not Asistanı"
echo "  Başlatılıyor... Lütfen bekleyin."
echo "=========================================================="

# Detect Python
if [ -d "venv" ]; then
    PYTHON_BIN="./venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
else
    echo "Hata: Python 3 bulunamadı!"
    exit 1
fi

# Open user's default web browser after 1.5s
(sleep 2 && open "http://localhost:5050") &

# Run server
$PYTHON_BIN app.py
