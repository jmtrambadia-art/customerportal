#!/bin/bash
cd "$(dirname "$0")"
PORT="${PORT:-8070}" python3 server/app.py
