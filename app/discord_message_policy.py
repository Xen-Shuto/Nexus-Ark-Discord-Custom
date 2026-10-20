"""Discord addressing rules, independent of the Discord SDK and LLM clients."""

import re
import os


def extract_discord_media(text, image_paths=()):
    """One detector for replies, group chat and autonomous sends; no downloads."""
    paths = []
    seen = set()
    extension = r"(?:png|jpe?g|webp|gif|bmp|avif|mp4|webm)"

    def add(path):
        path = str(path).strip().strip("\"'")
        if path.startswith(("http://", "https://")):
            return False
        if not re.search(r"\." + extension + r"$", path, re.I) or not os.path.isfile(path):
            return False
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            paths.append(path)
        return True

    for path in image_paths or ():
        add(path)

    def replace(match):
        path = match.group(1)
        if path.startswith(("http://", "https://")):
            return match.group(0)
        return " 📸 " if add(path) else " [画像ファイルが見つかりません] "

    text = re.sub(r"\[(?:VIEW_IMAGE|GENERATED_IMAGE|Generated Image|ファイル添付):\s*(.*?)\]", replace, text or "", flags=re.I)
    text = re.sub(r"!\[[^\]]*\]\((.*?)\)", replace, text)
    text = re.sub(r"[\"']([^\"'\r\n]+\." + extension + r")[\"']", replace, text, flags=re.I)
    pattern = r"(?<![\w/])((?:[A-Za-z]:[\\/])?[^\s<>\"'\[\]()]+?\." + extension + r")(?=$|[\s)\]。、,!?])"
    text = re.sub(pattern, replace, text, flags=re.I)
    return text.strip(), paths


def response_directives(text):
    """Only a standalone SILENCE marker suppresses a response."""
    force_reply = "<action:reply/>" in text
    text = text.replace("<action:reply/>", "").strip()
    return text, force_reply, text == "[SILENCE]"


def reply_author_id(message):
    """Use an already resolved reference; deleted/uncached references stay unknown."""
    reference = getattr(message, "reference", None)
    for attr in ("resolved", "cached_message"):
        parent = getattr(reference, attr, None)
        author = getattr(parent, "author", None)
        if author is not None:
            return getattr(author, "id", None)
    return None


def is_directly_addressed(message, own_id, own_name="", other_names=()):
    content = getattr(message, "content", "") or ""
    if own_id is not None:
        if re.search(rf"<@!?{re.escape(str(own_id))}>", content):
            return True
        if any(getattr(user, "id", None) == own_id for user in getattr(message, "mentions", ())):
            return True
    if getattr(message, "mention_everyone", False):
        return True
    me = getattr(getattr(message, "guild", None), "me", None)
    own_roles = getattr(me, "roles", ())
    if any(role in own_roles for role in getattr(message, "role_mentions", ())):
        return True
    if own_name:
        # A shorter persona name inside another persona's name is not a call.
        for name in other_names:
            if name and name != own_name and own_name in name:
                content = content.replace(name, "")
        if own_name in content:
            return True
    return False


def should_respond(message, own_id, own_name="", other_names=(), mode="always"):
    """Explicit user mentions win; other-bot addressing overrides ambient chat."""
    if mode == "ignore":
        return False
    content = getattr(message, "content", "") or ""
    mentions = getattr(message, "mentions", ())
    own_mention = own_id is not None and (
        any(getattr(user, "id", None) == own_id for user in mentions)
        or bool(re.search(rf"<@!?{re.escape(str(own_id))}>", content))
    )
    if own_mention:
        return True
    if any(getattr(user, "bot", False) and getattr(user, "id", None) != own_id for user in mentions):
        return False
    if is_directly_addressed(message, own_id, own_name, other_names):
        return True
    parent_id = reply_author_id(message)
    if own_id is not None and parent_id == own_id:
        return True
    # Suppress replies to another bot when the referenced message is available.
    reference = getattr(message, "reference", None)
    for attr in ("resolved", "cached_message"):
        author = getattr(getattr(reference, attr, None), "author", None)
        if author is not None and getattr(author, "bot", False) and parent_id != own_id:
            return False
    if any(name and name in content for name in other_names):
        return False
    me = getattr(getattr(message, "guild", None), "me", None)
    roles = getattr(message, "role_mentions", ())
    if me is not None and roles and not any(role in getattr(me, "roles", ()) for role in roles):
        return False
    return mode == "always"
