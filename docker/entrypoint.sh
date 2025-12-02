#!/usr/bin/env bash
set -euo pipefail

normalize_bool() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

XVFB_PID=""
if ! normalize_bool "${ALITA_BROWSER_HEADLESS:-false}"; then
    export DISPLAY="${ALITA_XVFB_DISPLAY:-:99}"
    XVFB_SCREEN="${ALITA_XVFB_SCREEN:-1600x900x24}"
    XVFB_CMD=(Xvfb "${DISPLAY}" -screen 0 "${XVFB_SCREEN}" -nolisten tcp)
    "${XVFB_CMD[@]}" &
    XVFB_PID=$!
    cleanup() {
        if [ -n "$XVFB_PID" ] && kill -0 "$XVFB_PID" >/dev/null 2>&1; then
            kill "$XVFB_PID" || true
        fi
    }
    trap cleanup EXIT INT TERM
    # Give Xvfb a moment to finish initialization
    sleep 0.5
fi

if [ "$#" -eq 0 ]; then
    exec uvicorn src.main:app --host "${ALITA_HOST:-0.0.0.0}" --port "${ALITA_PORT:-4000}" --proxy-headers
fi

exec "$@"
