"""Turn-scoped execution limits from unambiguous, explicit user quantities."""
import hashlib
import re
import unicodedata
import json
import os
from pathlib import Path


def recent_twitter_media_candidates(messages):
    """Offer referenced files from one recent message; never scan image folders."""
    for message in reversed(messages or []):
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        paths = []
        for value in re.findall(r"\[(?:VIEW_IMAGE|GENERATED_IMAGE|Generated Image|ファイル添付):\s*(.*?)\]", content, re.I):
            value = value.strip().strip("\"'")
            path = Path(value)
            if not path.is_file() and not path.is_absolute():
                path = Path(__file__).resolve().parents[1] / value
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                absolute = str(path.resolve())
                if absolute not in paths:
                    paths.append(absolute)
        if paths:
            return paths
    return []


def twitter_draft_media_error(messages, args):
    """Reject image drafts with omitted/missing attachments before saving anything."""
    media = args.get("media_paths")
    if media:
        if not isinstance(media, list) or any(not isinstance(path, str) or not os.path.isfile(path) for path in media):
            return "media_paths に実在する画像ファイルのパスを配列で指定してください。下書きは未作成です。"
        return None
    user_text = ""
    intents = []
    for message in reversed(messages or []):
        content = getattr(message, "content", "")
        if getattr(message, "type", "") == "human" or type(message).__name__ == "HumanMessage":
            if isinstance(content, list):
                content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
            user_text = content if isinstance(content, str) else ""
            break
        if getattr(message, "name", "") == "request_capability" and isinstance(content, str):
            try:
                payload, _ = json.JSONDecoder().raw_decode(content[content.index("{"):])
                if payload.get("category") in {"twitter", "x", "sns", "social", "tweet", "tweets"}:
                    intents.append(str(payload.get("intent", "")) + " " + str(payload.get("details", "")))
            except (ValueError, TypeError):
                pass
    if re.search(r"(?:画像|写真|イラスト)(?:は|を)?(?:なし|無し|不要|付けない|つけない|添付しない)|(?:without|no)\s+(?:an?\s+)?(?:image|photo|picture)", user_text, re.I):
        return None
    attachment_pattern = (
        r"(?:画像|写真|イラスト)(?:付き|つき|を添付|も添付|を付け|をつけ|を載せ|を投稿|も投稿|をツイート|を含む|を入れ)"
        r"|\b(?:with|attach|include|including|post|share|tweet|using|use)\s+"
        r"(?:(?:an?|the|this|that|newly|generated|new|our)\s+){0,4}(?:images?|photos?|pictures?|illustrations?)\b"
    )
    requested = any(re.search(attachment_pattern, text, re.I) for text in [user_text, *intents])
    if not requested:
        return None
    error = (
        "画像付き下書きの要求ですが media_paths が未指定です。画像なしの下書きは作成していません。"
        "対象画像のパスを media_paths=[\"画像パス\"] に指定して draft_tweet を再実行してください。"
        "対象が分からない場合はユーザーに確認し、画像付きで作成できたと報告しないでください。"
    )
    candidates = recent_twitter_media_candidates(messages)
    if candidates:
        error += "\n直近の会話にある画像候補（要求された対象か確認すること）: " + json.dumps(candidates, ensure_ascii=False)
    return error


def explicit_image_count(text: str):
    """Return a single explicit Japanese image quantity; leave ambiguity alone.

    This is deliberately not a general intent/quantity interpreter. For
    example, 各2枚, 2種類を3枚ずつ and 1枚以上 must not become a smaller cap.
    """
    text = unicodedata.normalize("NFKC", text)
    if re.search(r"ずつ|づつ|それぞれ|各|種類|パターン|ごと|毎|[×*]|[0-9]\s*[xX]\s*[0-9]", text):
        return None
    matches = list(re.finditer(r"([0-9]+|[一二三四五六七八九十]+)\s*枚", text))
    if len(matches) != 1:
        return None
    match = matches[0]
    before, after = text[:match.start()].rstrip(), text[match.end():].lstrip()
    image_noun = r"(?:画像|イラスト|絵|写真)"
    if not (re.search(image_noun + r"(?:を|は|が)?\s*(?:ちょうど|合計|全部で|計)?\s*$", before)
            or re.match(r"(?:の)?" + image_noun, after)
            or (not before and re.match(r"(?:描|生成|作成)", after))):
        # e.g. 「シャツを2枚着た少女の画像」 counts clothes, not outputs.
        return None
    if re.match(r"(?:目|以上|以下|程度|ほど|前後|くらい|ぐらい)", after):
        return None
    value = match[1]
    if value.isdecimal():
        try:
            return int(value)
        except ValueError:
            return None
    digits = {char: number for number, char in enumerate("〇一二三四五六七八九")}
    if value in digits:
        return digits[value]
    parts = value.split("十")
    if len(parts) == 2 and all(part == "" or part in digits for part in parts):
        return (digits.get(parts[0], 1) * 10) + digits.get(parts[1], 0)
    return None


def prepare_image_generation_guard(messages, previous=None, autonomous=False):
    """Track admitted attempts across tool batches for the latest human turn.

    Count attempts, including exceptions/timeouts: a failed response does not
    prove the image server had no side effect. A new user turn resets the cap.
    Ambiguous/unspecified quantities and autonomous actions retain old behavior.
    """
    if autonomous:
        return None
    for index in range(len(messages or []) - 1, -1, -1):
        message = messages[index]
        if getattr(message, "type", "") != "human" and type(message).__name__ != "HumanMessage":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str):
            return None
        limit = explicit_image_count(content)
        if limit is None:
            return None
        key = hashlib.sha256(
            f"{index}\0{getattr(message, 'id', '')}\0{content}".encode("utf-8")
        ).hexdigest()
        attempts = 0
        if isinstance(previous, dict) and previous.get("request_key") == key:
            attempts = max(0, int(previous.get("attempts", 0)))
        return {"request_key": key, "limit": limit, "attempts": attempts}
    return None
