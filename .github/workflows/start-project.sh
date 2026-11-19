#!/bin/bash

# ==========================================
# HealthGuardian AI - Start Everything
# ==========================================

BACKEND="/c/gajjab/healthguardian_ai/smart-health-poc-backend"
FRONTEND="/c/gajjab/healthguardian_ai/smart-health-poc-frontend"

echo ""
echo "=========================================="
echo "      HealthGuardian AI Starting..."
echo "=========================================="
echo ""

# -----------------------------
# Start Backend
# -----------------------------
echo "[1/2] Starting Backend..."

cd "$BACKEND" || exit 1

source venv/Scripts/activate

python -m uvicorn main:app --reload &
BACKEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Backend: http://127.0.0.1:8000"
echo ""

# Give backend a few seconds
sleep 3

# -----------------------------
# Start Frontend
# -----------------------------
echo "[2/2] Starting Frontend..."

cd "$FRONTEND" || exit 1

export PATH="/c/Program Files/nodejs:$PATH"

echo "Frontend: Expo"
echo ""

# -----------------------------
# Cleanup when Ctrl+C
# -----------------------------
cleanup() {
    echo ""
    echo "Stopping HealthGuardian AI..."

    kill $BACKEND_PID 2>/dev/null

    echo "Backend stopped."
    echo "Frontend stopped."
    echo "Done."
}

trap cleanup INT TERM

# -----------------------------
# Start Expo in same terminal
# -----------------------------
npm start

cleanup
