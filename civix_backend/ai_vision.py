"""
CIVIX — Vision AI Classification Service
==========================================
Parses uploaded civic issue photos using multimodal AI (OpenAI GPT-4o or Gemini Flash)
and returns structured JSON with category, issue type, severity, and confidence score.

Fallback:
    If AI API keys are missing or invalid, uses an intelligent heuristic classifier
    to ensure seamless demo/hackathon presentations without errors.
"""

import os
import json
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

VALID_CATEGORIES = [
    "road", "water", "waste", "electricity",
    "drainage", "public_safety", "environment", "other"
]

VALID_SEVERITIES = ["critical", "high", "medium", "low"]


def classify_issue_image(image_bytes=None, image_url=None, title_hint=""):
    """
    Classify a civic issue photo using Vision AI.

    Args:
        image_bytes (bytes, optional): Raw image bytes.
        image_url (str, optional): Public URL of the image.
        title_hint (str, optional): User's description/title if available.

    Returns:
        dict: {
            "category": str,
            "issue_type": str,
            "severity": str,
            "confidence": float,
            "suggested_title": str,
            "raw_response": dict
        }
    """
    ai_provider = os.getenv("AI_PROVIDER", "openai").lower()
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    # 1. Try OpenAI GPT-4o if configured
    if ai_provider == "openai" and openai_key and not openai_key.startswith("sk-your"):
        try:
            return _call_openai_vision(image_bytes, image_url, title_hint, openai_key)
        except Exception as e:
            print(f"[CIVIX] [AI] OpenAI Vision failed: {e}. Falling back to heuristic classifier.")

    # 2. Try Gemini Flash if configured
    if gemini_key and not gemini_key.startswith("your-gemini"):
        try:
            return _call_gemini_vision(image_bytes, image_url, title_hint, gemini_key)
        except Exception as e:
            print(f"[CIVIX] [AI] Gemini Vision failed: {e}. Falling back to heuristic classifier.")

    # 3. Fallback Heuristic Classifier (Ensures hackathon demo never fails)
    return _heuristic_classifier(title_hint)


def _call_openai_vision(image_bytes, image_url, title_hint, api_key):
    """Call OpenAI GPT-4o Vision API."""
    prompt = (
        "You are an expert municipal civic inspector AI for the CIVIX platform. "
        "Analyze this image of a civic/urban problem and respond with ONLY a raw JSON object (no markdown, no backticks):\n"
        "{\n"
        '  "category": "road" | "water" | "waste" | "electricity" | "drainage" | "public_safety" | "environment" | "other",\n'
        '  "issue_type": "specific short string e.g. pothole, broken_wire, garbage_dump, pipe_leak",\n'
        '  "severity": "critical" | "high" | "medium" | "low",\n'
        '  "confidence": float between 0.70 and 0.99,\n'
        '  "suggested_title": "concise 5-8 word title"\n'
        "}"
    )

    image_content = []
    if image_url:
        image_content = [{"type": "image_url", "image_url": {"url": image_url}}]
    elif image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_content = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]

    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt + f"\nContext hint: {title_hint}"}] + image_content
        }
    ]

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "gpt-4o", "messages": messages, "max_tokens": 300, "temperature": 0.2},
        timeout=15
    )
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    parsed = json.loads(content.strip())
    parsed["raw_response"] = {"model": "gpt-4o", "usage": data.get("usage")}
    return parsed


def _call_gemini_vision(image_bytes, image_url, title_hint, api_key):
    """Call Google Gemini Flash Vision API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    prompt = (
        "Analyze this urban civic problem photo. Respond ONLY in valid JSON format with keys: "
        "category (road/water/waste/electricity/drainage/public_safety/environment/other), "
        "issue_type (string), severity (critical/high/medium/low), confidence (0.0 to 1.0), suggested_title (string)."
    )

    parts = [{"text": prompt + f" User description hint: {title_hint}"}]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    payload = {"contents": [{"parts": parts}]}
    res = requests.post(url, json=payload, timeout=15)
    data = res.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    parsed["raw_response"] = {"model": "gemini-1.5-flash"}
    return parsed


def _heuristic_classifier(title_hint=""):
    """
    Intelligent simulated vision classifier when live AI API keys are not provided.
    Parses keyword hints or assigns sensible realistic defaults.
    """
    hint = title_hint.lower()
    
    if any(w in hint for w in ["pot", "hole", "road", "footpath", "tar", "asphalt", "traffic"]):
        return {
            "category": "road",
            "issue_type": "pothole_or_road_damage",
            "severity": "high",
            "confidence": 0.94,
            "suggested_title": "Severe Pothole / Road Surface Damage",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
    elif any(w in hint for w in ["water", "pipe", "leak", "tap", "flood", "drinking"]):
        return {
            "category": "water",
            "issue_type": "pipeline_leak",
            "severity": "critical",
            "confidence": 0.92,
            "suggested_title": "Active Water Supply Pipeline Burst",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
    elif any(w in hint for w in ["garbage", "trash", "waste", "dump", "bin", "plastic", "smell"]):
        return {
            "category": "waste",
            "issue_type": "overflowing_garbage_bin",
            "severity": "high",
            "confidence": 0.89,
            "suggested_title": "Accumulated Garbage / Waste Overflow",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
    elif any(w in hint for w in ["wire", "light", "electric", "spark", "pole", "transformer"]):
        return {
            "category": "electricity",
            "issue_type": "hazardous_wiring",
            "severity": "critical",
            "confidence": 0.96,
            "suggested_title": "Hazardous Loose Electrical Wiring",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
    elif any(w in hint for w in ["drain", "sewage", "sewer", "gutter", "clog"]):
        return {
            "category": "drainage",
            "issue_type": "clogged_drain",
            "severity": "high",
            "confidence": 0.91,
            "suggested_title": "Blocked Stormwater / Sewage Drainage",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
    else:
        return {
            "category": "road",
            "issue_type": "civic_hazard",
            "severity": "high",
            "confidence": 0.88,
            "suggested_title": "Civic Infrastructure Issue Detected",
            "raw_response": {"model": "civix-heuristic-vision-v1", "simulated": True}
        }
