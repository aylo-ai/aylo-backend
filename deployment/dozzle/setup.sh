#!/bin/bash
# Create the Dozzle login file before the first `docker compose --profile logs up`.
#
# Dozzle refuses to start with DOZZLE_AUTH_PROVIDER=simple and no
# deployment/dozzle/users.yml, so run this once per host:
#
#   ./deployment/dozzle/setup.sh admin
#
# The password is read from stdin (never passed as an argument, so it stays out
# of the shell history and the process table) and stored bcrypt-hashed.
# users.yml is gitignored — it is a host secret, like .env.
#
# Re-run to add another user; the new entry is appended to the existing file.
set -euo pipefail

USERNAME="${1:-}"
if [ -z "$USERNAME" ]; then
    echo "usage: $0 <username> [display name] [email]" >&2
    exit 1
fi
DISPLAY_NAME="${2:-$USERNAME}"
EMAIL="${3:-}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USERS_FILE="$DIR/users.yml"
IMAGE="$(grep -oE 'amir20/dozzle:[^ ]+' "$DIR/../../compose.yml" | head -1)"

read -r -s -p "Password for '$USERNAME': " PASSWORD
echo
read -r -s -p "Confirm: " PASSWORD_CONFIRM
echo
if [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
    echo "Passwords do not match." >&2
    exit 1
fi
if [ "${#PASSWORD}" -lt 12 ]; then
    echo "Use at least 12 characters — this page is reachable from the internet." >&2
    exit 1
fi

# --user-roles none: a viewer that can read logs and nothing else. Without it
# Dozzle grants the `all` role, which re-enables actions and shell for that
# user regardless of DOZZLE_ENABLE_ACTIONS.
ENTRY=$(printf '%s' "$PASSWORD" | docker run -i --rm "$IMAGE" generate \
    "$USERNAME" \
    --name "$DISPLAY_NAME" \
    ${EMAIL:+--email "$EMAIL"} \
    --user-roles none)

if [ -s "$USERS_FILE" ]; then
    # Append just the user entry, dropping the leading `users:` key.
    printf '%s\n' "$ENTRY" | sed '1{/^users:/d}' >> "$USERS_FILE"
else
    printf '%s\n' "$ENTRY" > "$USERS_FILE"
fi

# Dozzle runs as root inside the container but with `cap_drop: ALL`, so it has
# no CAP_DAC_OVERRIDE: it can only read this file as its owner or through the
# world bit. On the server (deploying as root) 600 is readable and correct;
# from a personal account the file would be unreadable at 600.
if [ "$(id -u)" -eq 0 ]; then
    chmod 600 "$USERS_FILE"
    MODE=600
else
    chmod 644 "$USERS_FILE"
    MODE=644
    echo "Note: not running as root, so $USERS_FILE is mode 644 — the container" >&2
    echo "      could not read it otherwise. On the server, run this as root." >&2
fi

echo "Wrote $USERS_FILE (mode $MODE)."
echo "Start the viewer with: docker compose --profile logs up -d"
