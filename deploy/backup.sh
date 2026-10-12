#!/usr/bin/env bash
# Back up the hub's data (uploaded profiles and counters) to /var/backups/plunge, keeping 14 days.
# Copy the newest file somewhere off this server now and then (your own PC, or object storage): a backup on the same disk
# does not survive losing the server.
set -euo pipefail
dest=/var/backups/plunge
mkdir -p "$dest"
vol="$(docker volume ls -q | grep -E 'hub-data$' | head -n1)"
[ -n "$vol" ] || { echo "hub-data volume not found"; exit 1; }
docker run --rm -v "$vol":/data:ro -v "$dest":/out alpine tar czf "/out/hub-$(date +%F).tgz" -C /data .
find "$dest" -name 'hub-*.tgz' -mtime +14 -delete
echo "backup written to $dest"
