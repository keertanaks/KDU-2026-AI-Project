"""
S3 + KMS verification checklist.
Run this BEFORE switching USE_LOCAL_STORAGE=false in config/.env.

Usage:
    python scripts/verify_s3_kms.py
"""
import os
import sys
import io
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

results = []


def check(label: str, fn):
    try:
        ok = fn()
        status = PASS if ok else FAIL
    except Exception as e:
        status = f"FAIL ({e})"
    results.append((label, status))
    print(f"[{status}] {label}")


def check_env_var(name: str) -> bool:
    val = os.getenv(name, "")
    return bool(val) and "your_" not in val.lower() and "placeholder" not in val.lower()


# --- Env-var checks ---
check("AWS_ACCESS_KEY_ID set", lambda: check_env_var("AWS_ACCESS_KEY_ID"))
check("AWS_SECRET_ACCESS_KEY set", lambda: check_env_var("AWS_SECRET_ACCESS_KEY"))
check("AWS_REGION set", lambda: check_env_var("AWS_REGION"))
check("S3_BUCKET_NAME set", lambda: check_env_var("S3_BUCKET_NAME"))
check("KMS_KEY_ID set", lambda: check_env_var("KMS_KEY_ID"))

# Only attempt live checks if credentials are present
creds_ok = all(check_env_var(v) for v in [
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION",
    "S3_BUCKET_NAME", "KMS_KEY_ID",
])

if not creds_ok:
    print("\nAWS credentials not configured — skipping live AWS checks.")
    print("Complete Section 0.3.1 (S3 bucket + KMS key setup) then re-run this script.")
    for label in [
        "boto3 client initializes",
        "S3 bucket accessible",
        "S3 bucket blocks public access",
        "KMS key accessible",
        "Test upload with SSE-KMS succeeds",
        "Test object has ServerSideEncryption=aws:kms",
        "Test object deleted after check",
    ]:
        results.append((label, BLOCKED))
        print(f"[{BLOCKED}] {label}")
else:
    import boto3
    from botocore.exceptions import ClientError

    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION"),
        )
        check("boto3 client initializes", lambda: True)
    except Exception as e:
        check("boto3 client initializes", lambda: (_ for _ in ()).throw(e))
        s3 = None

    bucket = os.getenv("S3_BUCKET_NAME")
    kms_key = os.getenv("KMS_KEY_ID")

    def bucket_accessible():
        s3.head_bucket(Bucket=bucket)
        return True

    def bucket_blocks_public():
        resp = s3.get_public_access_block(Bucket=bucket)
        cfg = resp["PublicAccessBlockConfiguration"]
        return all([
            cfg.get("BlockPublicAcls"),
            cfg.get("IgnorePublicAcls"),
            cfg.get("BlockPublicPolicy"),
            cfg.get("RestrictPublicBuckets"),
        ])

    def kms_accessible():
        kms = boto3.client(
            "kms",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION"),
        )
        kms.describe_key(KeyId=kms_key)
        return True

    test_key = "verify-test/sse-kms-check.txt"

    def upload_with_kms():
        s3.put_object(
            Bucket=bucket,
            Key=test_key,
            Body=b"sse-kms-check",
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=kms_key,
        )
        return True

    def object_has_kms():
        resp = s3.head_object(Bucket=bucket, Key=test_key)
        return resp.get("ServerSideEncryption") == "aws:kms"

    def cleanup_test_object():
        s3.delete_object(Bucket=bucket, Key=test_key)
        return True

    if s3:
        check("S3 bucket accessible", bucket_accessible)
        check("S3 bucket blocks public access", bucket_blocks_public)
        check("KMS key accessible", kms_accessible)
        check("Test upload with SSE-KMS succeeds", upload_with_kms)
        check("Test object has ServerSideEncryption=aws:kms", object_has_kms)
        check("Test object deleted after check", cleanup_test_object)

# Summary
print("\n--- S3/KMS Checklist Summary ---")
for label, status in results:
    print(f"  [{status}] {label}")

blocked = sum(1 for _, s in results if s == BLOCKED)
failed = sum(1 for _, s in results if s.startswith("FAIL"))
passed = sum(1 for _, s in results if s == PASS)
print(f"\n{passed} PASS / {failed} FAIL / {blocked} BLOCKED")

if failed:
    sys.exit(1)
