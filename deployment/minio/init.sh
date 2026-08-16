#!/bin/sh
set -eu

BUCKET="${MINIO_BUCKET_NAME:?MINIO_BUCKET_NAME is required}"
ROOT_USER="${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
APP_KEY="${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY is required}"
APP_SECRET="${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required}"
POLICY_NAME="aylo-media-rw"

MINIO_INTERNAL_ENDPOINT="${MINIO_INTERNAL_ENDPOINT:-http://minio:9000}"
MAX_ATTEMPTS="${MINIO_INIT_MAX_ATTEMPTS:-30}"

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

echo "==> revoking anonymous access"
mc anonymous set none "local/$BUCKET"

if [ "${MINIO_VERSIONING:-off}" = "on" ]; then
    echo "==> enabling versioning"
    mc version enable "local/$BUCKET"
fi

echo "==> policy: $POLICY_NAME"
# Rendered inline — no sed/envsubst available in the mc image, and this
# needs nothing but the shell itself.
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

mc admin user add local "$APP_KEY" "$APP_SECRET" 2>/dev/null || true
mc admin policy attach local "$POLICY_NAME" --user "$APP_KEY" 2>/dev/null || true
mc admin user enable local "$APP_KEY"

echo "==> minio ready: bucket=$BUCKET anonymous=none policy=$POLICY_NAME"
