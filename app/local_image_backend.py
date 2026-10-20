"""SD WebUI txt2img settings and protocol, without app initialization."""

import base64
import math
from urllib.parse import urlsplit


DEFAULT_LOCAL_IMAGE_SETTINGS = {
    "url": "http://127.0.0.1:7861/sdapi/v1/txt2img",
    "sampler": "Euler a", "steps": 25, "cfg_scale": 7.0,
    "positive_prefix": "", "positive_append": "", "negative_prompt": "",
}


def normalize_local_image_settings(settings=None):
    source = settings or {}
    result = {**DEFAULT_LOCAL_IMAGE_SETTINGS, **source}
    for key in ("url", "sampler", "negative_prompt"):
        result[key] = str(result[key] or "").strip()
    for key in ("positive_prefix", "positive_append"):
        result[key] = str(source.get(key, source.get(key.replace("positive_", "positive_prompt_"), "")) or "").strip()
    parsed = urlsplit(result["url"])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ローカル画像生成のAPI URLを http:// または https:// で指定してください。")
    if not result["sampler"]:
        raise ValueError("サンプラーを指定してください。")
    steps = float(result["steps"])
    cfg = float(result["cfg_scale"])
    if not math.isfinite(steps) or not steps.is_integer() or not 1 <= steps <= 150:
        raise ValueError("Stepsは1～150の整数で指定してください。")
    if not math.isfinite(cfg) or not 0 <= cfg <= 30:
        raise ValueError("CFGは0～30で指定してください。")
    result["steps"], result["cfg_scale"] = int(steps), cfg
    return {key: result[key] for key in DEFAULT_LOCAL_IMAGE_SETTINGS}


def build_local_image_request(prompt, settings=None, *, aspect_ratio="square", sampler=None, steps=None, cfg=None):
    source = dict(settings or {})
    for key, value in (("sampler", sampler), ("steps", steps), ("cfg_scale", cfg)):
        if value is not None:
            source[key] = value
    normalized = normalize_local_image_settings(source)
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("画像生成プロンプトを入力してください。")
    sizes = {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832)}
    ratio = str(aspect_ratio or "square").lower()
    if ratio not in sizes:
        raise ValueError("アスペクト比はsquare、portrait、landscapeから選択してください。")
    width, height = sizes[ratio]
    full_prompt = ", ".join(part for part in (normalized["positive_prefix"], prompt, normalized["positive_append"]) if part)
    return normalized["url"], {
        "prompt": full_prompt, "negative_prompt": normalized["negative_prompt"],
        "sampler_name": normalized["sampler"], "steps": normalized["steps"],
        "cfg_scale": normalized["cfg_scale"], "width": width, "height": height,
        "batch_size": 1, "n_iter": 1,
    }


def request_local_image(prompt, settings=None, *, post, **overrides):
    url, payload = build_local_image_request(prompt, settings, **overrides)
    # Connecting to an unavailable server should fail promptly, but generation
    # may take several minutes. Do not time out while waiting for its result.
    response = post(url, json=payload, timeout=(10, None))
    response.raise_for_status()
    data = response.json()
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, list) or not images or not isinstance(images[0], str):
        raise ValueError("SD WebUIから画像データが返されませんでした。")
    encoded = images[0]
    if encoded.startswith("data:"):
        encoded = encoded.split(";base64,", 1)[-1]
    image = base64.b64decode(encoded, validate=True)
    if not image:
        raise ValueError("SD WebUIから空の画像データが返されました。")
    return image
