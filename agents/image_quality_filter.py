"""Image Quality & Logo Filter Agent for News-Agent-Backend.

Detects and filters out channel logos, publication icons, generic placeholders,
and tiny thumbnails, ensuring only genuine journalistic photographs are used
in broadcast video generation.
"""
from __future__ import annotations

import re
import urllib.request
from typing import Optional, Tuple
import cv2
import numpy as np

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# Explicit logo / placeholder indicators in image URLs
SUSPICIOUS_URL_KEYWORDS = [
    "/logo/", "_logo", "-logo", "logo.", "logo_", "logothumb",
    "/icons/", "icon.", "favicon", "avatar", "/brand/",
    "placeholder", "generic_india", "generic-news", "default_image",
    "site_logo", "channel_logo", "badge.", "/watermark/",
]


def is_valid_article_photo(
    img_bgr: np.ndarray,
    url: str = "",
    min_width: int = 400,
    min_height: int = 225,
) -> Tuple[bool, str]:
    """Analyze an image to determine whether it is a genuine news photo or a logo/icon.

    Returns:
        (is_valid_photo: bool, reason: str)
    """
    if img_bgr is None or not isinstance(img_bgr, np.ndarray) or img_bgr.size == 0:
        return False, "corrupted_or_empty"

    url_lower = url.lower()

    # 1. URL pattern check
    if any(k in url_lower for k in SUSPICIOUS_URL_KEYWORDS):
        return False, "url_contains_logo_keyword"

    h, w = img_bgr.shape[:2]
    aspect = w / float(h)

    # 2. Dimensions check (Reject tiny thumbnails)
    if w < min_width or h < min_height:
        return False, f"too_small_{w}x{h}"

    # 3. Square Avatar / Badge check (News photos are virtually always landscape)
    if 0.88 <= aspect <= 1.12 and w <= 500:
        return False, f"square_badge_{w}x{h}"

    # 4. Solid Flat Background Check (Sign of a logo or vector graphic on flat backdrop)
    corners = [img_bgr[0, 0], img_bgr[0, -1], img_bgr[-1, 0], img_bgr[-1, -1]]
    corner_mean = np.mean(corners, axis=0)

    # Compute Euclidean distance of every pixel to the corner color
    diff = np.linalg.norm(img_bgr.astype(np.float32) - corner_mean, axis=2)
    flat_bg_ratio = np.sum(diff < 22.0) / float(w * h)

    # If over 48% of the image has the exact same flat color as the corners, it's a logo/graphic
    if flat_bg_ratio > 0.48:
        return False, f"flat_background_logo_ratio_{flat_bg_ratio:.2f}"

    # 5. Color Palette Diversity (Photographs have rich color depth)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    unique_levels = len(np.unique(gray))
    if unique_levels < 38:
        return False, f"low_color_palette_{unique_levels}"

    # 6. Edge Texture Variance (Photos have distributed texture; logos have empty space)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < 5.0 and flat_bg_ratio > 0.35:
        return False, f"low_texture_logo_{laplacian_var:.1f}"

    return True, "valid_photo"


def fetch_and_validate_image(
    url: str,
    timeout: float = 6.0,
    min_width: int = 400,
    min_height: int = 225,
) -> Tuple[bool, Optional[np.ndarray], str]:
    """Download image, verify accessibility, and validate that it is a real photo (not a logo).

    Returns:
        (is_valid: bool, image_array: Optional[np.ndarray], reason: str)
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, None, "invalid_url"

    url_lower = url.lower()
    if any(k in url_lower for k in SUSPICIOUS_URL_KEYWORDS):
        return False, None, "url_contains_logo_keyword"

    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()

        arr = np.asarray(bytearray(data), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return False, None, "decode_failed"

        is_photo, reason = is_valid_article_photo(
            img, url=url, min_width=min_width, min_height=min_height
        )
        if not is_photo:
            return False, None, reason

        return True, img, "valid_photo"

    except Exception as exc:
        return False, None, f"download_error_{type(exc).__name__}"


if __name__ == "__main__":
    test_urls = [
        "https://www.hindustantimes.com/ht-img/img/2025/06/30/1600x900/logo/ht-generic_india3_1751287297962_1751287304722.jpg",
        "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/5163/live/6a7c75a0-ac87-11ef-93a8-a3f1aaec9f54.jpg",
        "https://ss-i.thgim.com/public/football/uhg12s/article71749658.ece/alternates/LANDSCAPE_1200/2026-11-25T215904Z_12345_RTRMADP_3_SOCCER-CHAMPIONS-LIV-RMA-REPORT.JPG",
    ]
    for u in test_urls:
        valid, _, r = fetch_and_validate_image(u)
        status = "✅ PHOTO" if valid else "❌ LOGO/REJECTED"
        print(f"{status:<16} [{r:<28}] {u[:65]}...")
