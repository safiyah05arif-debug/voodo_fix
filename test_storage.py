"""
CIVIX — Supabase Storage Test Script
======================================
Verifies Supabase connection, bucket creation, image upload, and public URL generation.

Usage:
    python test_storage.py
"""

import sys
import os

# Set django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civix_backend.settings")

from civix_backend.storage import (
    get_supabase_client,
    get_bucket_name,
    ensure_bucket_exists,
    upload_image_bytes,
)

def test_supabase_storage():
    print("=" * 60)
    print("  CIVIX -- Supabase Storage Test")
    print("=" * 60)

    # 1. Initialize client
    print("\n[1] Initializing Supabase client...")
    try:
        client = get_supabase_client()
        bucket = get_bucket_name()
        print(f"   [OK] Connected to Supabase at: {os.getenv('SUPABASE_URL')}")
        print(f"   [INFO] Target bucket: {bucket}")
    except Exception as e:
        print(f"   [FAIL] Client initialization failed: {e}")
        return False

    # 2. Ensure bucket exists
    print("\n[2] Ensuring bucket exists and is configured...")
    try:
        ensure_bucket_exists(bucket)
        print(f"   [OK] Bucket '{bucket}' verified.")
    except Exception as e:
        print(f"   [WARN] Bucket check note: {e}")

    # 3. Test image upload (minimal 1x1 PNG)
    print("\n[3] Uploading test image bytes...")
    try:
        # 1x1 transparent PNG binary
        tiny_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
            b'\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf'
            b'\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        result = upload_image_bytes(
            file_bytes=tiny_png,
            filename="test_pothole_proof.png",
            folder="issues",
            content_type="image/png"
        )

        print(f"   [OK] Upload successful!")
        print(f"   [INFO] Storage Path: {result['path']}")
        print(f"   [LINK] Public URL:   {result['public_url']}")
    except Exception as e:
        print(f"   [FAIL] Image upload failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("  [SUCCESS] Supabase Storage is FULLY WORKING!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = test_supabase_storage()
    sys.exit(0 if success else 1)
