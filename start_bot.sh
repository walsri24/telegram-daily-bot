
#!/bin/bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

PROJECT_DIR="$HOME/Documents/Coding/telegram_daily_bot"
cd "$PROJECT_DIR"

if ! docker info >/dev/null 2>&1; then
    echo "Docker Desktop is not running. Start Docker Desktop first."
    exit 1
fi

docker compose up -d --build

