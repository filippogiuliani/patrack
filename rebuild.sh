#!/bin/sh
# Rebuild and restart paTrack. Data stays in ./paTrack_data (mounted on /app/data).
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "The .env file is missing: copy .env.example to .env and configure it." >&2
  exit 1
fi
sudo docker build -t patrack .
sudo docker rm -f patrack 2>/dev/null || true
sudo docker run -d --restart unless-stopped -p 3002:3002 --env-file .env \
  -v "$(pwd)/paTrack_data:/app/data" --name patrack patrack
echo "paTrack started on http://localhost:3002"
