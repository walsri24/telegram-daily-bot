
#!/bin/bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

PROJECT_DIR="$HOME/Documents/Coding/telegram_daily_bot"
cd "$PROJECT_DIR"

docker compose stop

