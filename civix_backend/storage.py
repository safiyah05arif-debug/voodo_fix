"""
CIVIX — Supabase Storage Service
==================================
Handles image uploads for issue photos and resolution proof photos to Supabase Storage.

Features:
    - Automatic bucket creation (with public access if permitted)
    - Unique filename generation with timestamp + UUID
    - Content-type detection & validation
    - Direct bytes or file path uploading
    - Generates public URLs for display on Leaflet maps & UI
"""

import os
import uuid
import datetime
import mimetypes
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Lazy client singleton
_supabase_client = None


def get_supabase_client():
    """
    Get or initialize the Supabase client using credentials from environment.
    Uses SUPABASE_SECRET_KEY if available (for storage admin privileges),
    otherwise falls back to SUPABASE_ANON_KEY.
    """
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client, Client

        supabase_url = os.getenv("SUPABASE_URL", "")
        # Prefer secret key for backend storage administration, fallback to anon key
        supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "Missing Supabase configuration. Please set SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_ANON_KEY in .env"
            )

        _supabase_client = create_client(supabase_url, supabase_key)
    return _supabase_client


def get_bucket_name():
    """Get the default bucket name from settings/env."""
    return os.getenv("SUPABASE_BUCKET_NAME", "civix-uploads")


def ensure_bucket_exists(bucket_name=None):
    """
    Ensure the target storage bucket exists.
    If not, attempts to create it as a public bucket.
    """
    bucket_name = bucket_name or get_bucket_name()
    supabase = get_supabase_client()

    try:
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets] if hasattr(buckets, '__iter__') else []
        if bucket_name not in bucket_names:
            supabase.storage.create_bucket(
                bucket_name,
                options={"public": True, "file_size_limit": 10485760} # 10MB limit
            )
            print(f"[CIVIX] [STORAGE] Created bucket: {bucket_name}")
    except Exception as e:
        # If bucket already exists or permissions restrict listing, proceed
        pass


def upload_image_bytes(file_bytes, filename, folder="issues", content_type=None, bucket_name=None):
    """
    Upload raw image bytes to Supabase Storage.

    Args:
        file_bytes (bytes): The raw image bytes.
        filename (str): The original filename (used to extract extension).
        folder (str): Target subfolder ('issues', 'resolutions', 'avatars').
        content_type (str, optional): MIME type, e.g. 'image/jpeg'.
        bucket_name (str, optional): Target bucket name.

    Returns:
        dict: {
            "public_url": str,
            "path": str,
            "filename": str
        }
    """
    bucket_name = bucket_name or get_bucket_name()
    supabase = get_supabase_client()
    ensure_bucket_exists(bucket_name)

    # Determine extension and unique path
    ext = Path(filename).suffix or ".jpg"
    unique_name = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    storage_path = f"{folder}/{unique_name}"

    if not content_type:
        content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"

    # Upload to Supabase Storage
    res = supabase.storage.from_(bucket_name).upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "true"}
    )

    # Get public URL
    public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)

    return {
        "public_url": public_url,
        "path": storage_path,
        "filename": unique_name,
    }


def upload_image_file(file_path, folder="issues", bucket_name=None):
    """
    Upload an image from a local file path to Supabase Storage.

    Args:
        file_path (str or Path): Path to the local image file.
        folder (str): Target subfolder ('issues', 'resolutions', 'avatars').
        bucket_name (str, optional): Target bucket name.

    Returns:
        dict: Upload result with public_url.
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path_obj, "rb") as f:
        file_bytes = f.read()

    content_type = mimetypes.guess_type(str(path_obj))[0] or "image/jpeg"
    return upload_image_bytes(
        file_bytes=file_bytes,
        filename=path_obj.name,
        folder=folder,
        content_type=content_type,
        bucket_name=bucket_name,
    )
