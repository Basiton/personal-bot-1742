#!/usr/bin/env bash
# Supervisor: keep the bot running (restart on crash) for maximum time (168 hours = 7 days)
LOG="/workspaces/personal-bot-1742/bot.log"
PY="/workspaces/personal-bot-1742/.venv/bin/python"
SCRIPT="/workspaces/personal-bot-1742/main.py"
DURATION=604800  # 168 hours = 7 days in seconds

echo "Supervisor start (MAX MODE): $(date)" >> "$LOG"
START_SECS=$SECONDS
END_SECS=$((START_SECS + DURATION))

while [ $SECONDS -lt $END_SECS ]; do
  # Check for any running main.py processes
  PIDS=$(pgrep -f "$SCRIPT" | tr '\n' ' ')
  if [ -n "$PIDS" ]; then
    echo "Found existing bot PIDs: $PIDS at $(date)" >> "$LOG"
    # Monitor existing PIDs until they exit or time limit reached
    for pid in $PIDS; do
      while kill -0 $pid 2>/dev/null && [ $SECONDS -lt $END_SECS ]; do
        sleep 1
      done
      if [ $SECONDS -ge $END_SECS ]; then
        break
      fi
    done
    # loop will check again whether to start or continue monitoring
    continue
  fi

  echo "No running bot found. Launching bot at $(date)" >> "$LOG"
  "$PY" "$SCRIPT" >> "$LOG" 2>&1 &
  CHILD=$!

  # Wait while child is alive or until time limit
  while kill -0 $CHILD 2>/dev/null && [ $SECONDS -lt $END_SECS ]; do
    sleep 1
  done

  if kill -0 $CHILD 2>/dev/null; then
    kill $CHILD 2>/dev/null || true
  fi

  # If time remains, sleep briefly then restart
  if [ $SECONDS -lt $END_SECS ]; then
    echo "Bot exited; will restart (time remaining: $((END_SECS-SECONDS))s)" >> "$LOG"
    sleep 1
  fi
done

echo "Supervisor finished at $(date)" >> "$LOG"
