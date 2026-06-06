#!/usr/bin/env bash
# Render Build Script for Sikka ERP
set -o errexit   # exit on error

echo ">>> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ">>> Build complete!"
