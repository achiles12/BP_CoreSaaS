#!/usr/bin/env bash
# `make ports`: is every host port of this clone free?  Args: KEY=PORT:SERVICE:CONTAINER_PORT ...
# Each line: free | this project | taken | duplicate | invalid. Exit 1 on the last three.
# Bash 3.2 compatible (macOS). A port is in use if it accepts a connection or a
# running container publishes it (Docker Desktop); stopped clones are not seen.
set -uo pipefail
rc=0; seen=" "
published="$(docker ps --format '{{.Ports}}' 2>/dev/null | grep -oE ':[0-9]+->' | grep -oE '[0-9]+' | sort -u)"
for arg in "$@"; do
  key="${arg%%=*}"; IFS=: read -r port svc cport <<<"${arg#*=}"
  if ! [[ "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then state="invalid"; rc=1
  else
    port=$((10#$port))
    if [[ "$seen" == *" $port "* ]]; then state="duplicate"; rc=1
    elif grep -qx "$port" <<<"$published" || (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      if docker compose port "$svc" "$cport" 2>/dev/null | grep -q ":$port\$"; then state="this project"
      else state="taken"; rc=1; fi
    else state="free"; fi
    seen="$seen$port "
  fi
  printf '%-20s %-6s %s\n' "$key" "$port" "$state"
done
[ $rc = 0 ] || echo "Change the marked ports in .env, then run make ports again."
exit $rc
