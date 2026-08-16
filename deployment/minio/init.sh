#!/bin/sh
#
# One-shot MinIO bootstrap. Runs on every `docker compose up` and is idempotent
# — re-running it must never destroy data or rotate a working credential.
#
# What it guarantees:
#   1. The media bucket exists.
#   2. The bucket denies anonymous access. Nothing is world-readable; Django
#      hands out short-lived presigned URLs instead.
#   3. The application has its OWN credential, scoped by policy to this one
#      bucket. The root credential stays inside the minio container and is
#      never put in the app's environment — a leaked app key cannot create
#      users, read other buckets, or reach the admin API.
#
set -eu

BUCKET="${MINIO_BUCKET_NAME:?MINIO_BUCKET_NAME is required}"
ROOT_USER="${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
APP_KEY="${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY is required}"
APP_SECRET="${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required}"
POLICY_NAME="aylo-media-rw"

MINIO_INTERNAL_ENDPOINT="${MINIO_INTERNAL_ENDPOINT:-http://minio:9000}"
MAX_ATTEMPTS="${MINIO_INIT_MAX_ATTEMPTS:-30}"

# Bounded, and it reports *why* it gave up. An unbounded `until` loop here hangs
# forever on a wrong credential, which looks identical to "still booting" —
# the failure mode this exact script was caught by.
echo "==> waiting for minio at $MINIO_INTERNAL_ENDPOINT"
attempt=0
until mc alias set local "$MINIO_INTERNAL_ENDPOINT" "$ROOT_USER" "$ROOT_PASSWORD" \
        >/tmp/mc-alias.log 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
        echo "ERROR: could not authenticate to minio after $attempt attempts." >&2
        cat /tmp/mc-alias.log >&2
        echo "" >&2
        echo "If that mentions credentials or AccessDenied, the minio container is" >&2
        echo "still running with the MINIO_ROOT_USER/MINIO_ROOT_PASSWORD it started" >&2
        echo "with — compose reuses a healthy container and does not re-read .env." >&2
        echo "Recreate it:  docker compose up -d --force-recreate minio" >&2
        exit 1
    fi
    sleep 1
done

echo "==> bucket: $BUCKET"
mc mb --ignore-existing "local/$BUCKET"

# Belt and braces: `mc mb` creates buckets private, but an operator may have
# opened this one by hand from the console. Force it shut on every boot.
echo "==> revoking anonymous access"
mc anonymous set none "local/$BUCKET"

# Object versioning turns a malicious or buggy overwrite into a recoverable
# event. It costs disk, so it is opt-in via MINIO_VERSIONING=on.
if [ "${MINIO_VERSIONING:-off}" = "on" ]; then
    echo "==> enabling versioning"
    mc version enable "local/$BUCKET"
fi

echo "==> policy: $POLICY_NAME"
# Rendered inline — the mc image ships no sed/envsubst, and this needs
# nothing but the shell itself.
cat > /tmp/policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListOwnBucketOnly",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET}"
      ]
    },
    {
      "Sid": "ObjectReadWriteWithinBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET}/*"
      ]
    }
  ]
}
EOF
mc admin policy create local "$POLICY_NAME" /tmp/policy.json 2>/dev/null \
    || mc admin policy update local "$POLICY_NAME" /tmp/policy.json

echo "==> application user"
# `user add` fails loudly if the user already exists, so check first instead
# of blanket-suppressing errors — a suppressed real failure here (e.g. a
# secret key that's too short) previously surfaced as a confusing error two
# steps later on `user enable`, on a user that was never actually created.
if ! mc admin user info local "$APP_KEY" >/dev/null 2>&1; then
    mc admin user add local "$APP_KEY" "$APP_SECRET"
fi
mc admin policy attach local "$POLICY_NAME" --user "$APP_KEY" 2>/dev/null || true
mc admin user enable local "$APP_KEY"

echo "==> minio ready: bucket=$BUCKET anonymous=none policy=$POLICY_NAME"