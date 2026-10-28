#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export HOST=127.0.0.1
export VBOT_DEMO=1
exec "./Open Chess Coach.command"
