# tools/image_tools.py

import os
import io
import base64
import uuid
import time
import datetime
import traceback
from urllib.parse import quote
import requests as http_requests
from PIL import Image
import google.genai as genai
import httpx
from langchain_core.tools import tool
from google.genai import types
import config_manager 


def _generate_with_gemini(prompt: str, model_name: str, api_key: str, save_dir: str, room_name: str, api_key_name: str = "Unknown") -> str:
    """Gemini (google.genai) で画像を生成する"""
    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "Resource Exhausted" in error_str:
            print(f"  - [{room_name}] 画像生成で429エラーが発生しました。キー: {api_key_name}, モデル: {model_name}")
            # 枯渇状態を記録（有料キーの場合は内部でスキップされる）
            config_manager.mark_key_as_exhausted(api_key_name, model_name)
            return "【エラー】画像生成の制限（無料枠またはRPM制限）に達しました。しばらく待ってから再度お試しください。"
        # その他のエラーは呼び出し元で処理（または再送出）
        raise

    image_data = None
    image_text_response = ""
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.text:
                image_text_response = part.text
                print(f"  - [{room_name}] APIからのテキスト応答: {part.text}")
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                image_data = io.BytesIO(part.inline_data.data)

    if not image_data:
        return "【エラー】APIから画像データが返されませんでした。プロンプトが不適切か、安全フィルターにブロックされた可能性があります。"

    image = Image.open(image_data)
    # 日時の文字列はAIが修正したがるので…
    #timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #filename = f"{room_name.lower()}_{timestamp}.png"

    # --- 画像の保存ファイル名 ---
    # uuid4の最初の8文字だけ使うなど、短くしてもユニーク性は保てます
    unique_id = uuid.uuid4().hex[:8] 
    # 保存用ファイル名をUNIXタイムスタンプにする
    # これにより「時系列順」に並び、かつAIが「時刻」として認識しにくくなります。
    # 例: 1729999999.png (2024-10-27 15:00:00相当)
    timestamp_id = int(time.time())
    # --- 画像の保存ファイル名 ---
    filename = f"Gemini_{room_name.lower()}_{timestamp_id}_{unique_id}.png"

    save_path = os.path.join(save_dir, filename)

    image.save(save_path, "PNG")
    print(f"  - [{room_name}] 画像を保存しました: {save_path}")

    # --- 相対パスを絶対パスに変換 ---
    fullpath = os.path.abspath(save_path)

    # 【重要】バックスラッシュをスラッシュに置換
    # これにより AI が \ をエスケープしようとする挙動を物理的に防ぎます
    fullpath_fixed = fullpath.replace("\\", "/")

    model_comment = f"\nAI Model Comment: {image_text_response}" if image_text_response else ""
    return f"[Generated Image: {fullpath_fixed}]{model_comment}\n📝 Prompt: {prompt}\n画像生成完了。この画像についてコメントを添えてください。\n[VIEW_IMAGE: {fullpath_fixed}]"


#def _generate_with_openai(prompt: str, model_name: str, base_url: str, api_key: str, save_dir: str, room_name: str) -> str:
def _generate_with_openai(prompt: str, model_name: str, base_url: str, api_key: str, save_dir: str, room_name: str, aspect_ratio: str = "square") -> str:
    """OpenAI互換API (Images API) で画像を生成する"""
    from openai import OpenAI
    import requests
    
    print(f"  [{room_name}] [OpenAI Image] base_url={base_url}, model={model_name}")
    print(f"  [{room_name}] [OpenAI Image] api_key set: {bool(api_key and len(api_key) > 5)}")
    
    client = OpenAI(base_url=base_url, api_key=api_key)
    
    # モデルによってサイズを調整
    #size = "1024x1024"
    #if "dall-e-3" in model_name:
    #    size = "1024x1024"  # DALL-E 3は1024x1024, 1792x1024, 1024x1792
    if "dall-e-3" in model_name.lower():
        size_map = {
            "square": "1024x1024",
            "portrait": "1024x1792",
            "landscape": "1792x1024"
        }
        size = size_map.get(aspect_ratio.lower(), "1024x1024")
    else:
        # DALL-E 3以外のモデル以外は固定
        size = "1024x1024"
    
    # gpt-image-1系モデルはresponse_formatをサポートしない（URLベースのみ）
    is_gpt_image = "gpt-image" in model_name.lower() or "gptimage" in model_name.lower()
    is_grok = "grok" in model_name.lower()
    print(f"  [{room_name}] [OpenAI Image] is_gpt_image={is_gpt_image}, is_grok={is_grok}, size={size}")
    
    if is_gpt_image:
        # GPT Image モデル用（response_formatパラメータを渡さないが、b64_jsonで返る）
        print(f"  [{room_name}] [OpenAI Image] Calling images.generate (gpt-image mode, no response_format param)...")
        
        gen_params = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
        }
        if is_grok:
            # Grok は size をサポートせず aspect_ratio を使用する
            gen_params["extra_body"] = {"aspect_ratio": "1:1", "resolution": "1k"}
        else:
            gen_params["size"] = size
            
        response = client.images.generate(**gen_params)
        print(f"  [{room_name}] [OpenAI Image] Response received")
        
        # gpt-image-1は実際にはb64_jsonで返す（urlはNone）
        if response.data and response.data[0].b64_json:
            print(f"  [{room_name}] [OpenAI Image] Found b64_json data, decoding...")
            image_data = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(image_data))
        elif response.data and response.data[0].url:
            # フォールバック: URLがある場合
            image_url = response.data[0].url
            print(f"  [{room_name}] [OpenAI Image] Downloading from URL: {image_url[:100]}...")
            img_response = requests.get(image_url, timeout=60)
            img_response.raise_for_status()
            image = Image.open(io.BytesIO(img_response.content))
        else:
            print(f"  [{room_name}] [OpenAI Image] ERROR: No image data in response")
            return "【エラー】APIから画像データが返されませんでした。"
        
        print(f"  [{room_name}] [OpenAI Image] Image processed successfully")
    else:
        # DALL-E等（b64_json対応）
        print(f"  [{room_name}] [OpenAI Image] Calling images.generate (b64_json mode)...")
        
        gen_params = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json"
        }
        if is_grok:
            # Grok は size をサポートせず aspect_ratio を使用する
            gen_params["extra_body"] = {"aspect_ratio": "1:1", "resolution": "1k"}
        else:
            gen_params["size"] = size
            
        response = client.images.generate(**gen_params)
        print(f"  [{room_name}] [OpenAI Image] Response received")
        
        if not response.data or not response.data[0].b64_json:
            print(f"  [{room_name}] [OpenAI Image] ERROR: No b64_json in response.data")
            return "【エラー】APIから画像データが返されませんでした。"
        
        image_data = base64.b64decode(response.data[0].b64_json)
        image = Image.open(io.BytesIO(image_data))
    
    # 日時の文字列はAIが修正したがるので…
    #timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #filename = f"{room_name.lower()}_{timestamp}.png"

    # --- 画像の保存ファイル名 ---
    # uuid4の最初の8文字だけ使うなど、短くしてもユニーク性は保てます
    unique_id = uuid.uuid4().hex[:8] 
    # 保存用ファイル名をUNIXタイムスタンプにする
    # これにより「時系列順」に並び、かつAIが「時刻」として認識しにくくなります。
    # 例: 1729999999.png (2024-10-27 15:00:00相当)
    timestamp_id = int(time.time())
    # --- 画像の保存ファイル名 ---
    if "dall-e-3" in model_name.lower():
        filename = f"DALL-E-3_{room_name.lower()}_{timestamp_id}_{unique_id}.png"
    else:
        # DALL-E 3以外のモデル
        filename = f"OpenAI_{room_name.lower()}_{timestamp_id}_{unique_id}.png"

    save_path = os.path.join(save_dir, filename)
    
    image.save(save_path, "PNG")
    print(f"  - [{room_name}] 画像を保存しました: {save_path}")

    # --- 相対パスを絶対パスに変換 ---
    fullpath = os.path.abspath(save_path)

    # 【重要】バックスラッシュをスラッシュに置換
    # これにより AI が \ をエスケープしようとする挙動を物理的に防ぎます
    fullpath_fixed = fullpath.replace("\\", "/")

    revised_prompt = getattr(response.data[0], 'revised_prompt', None)
    model_comment = f"\nRevised Prompt: {revised_prompt}" if revised_prompt else ""
    return f"[Generated Image: {fullpath_fixed}]{model_comment}\n📝 Prompt: {prompt}\n画像生成完了。この画像についてコメントを添えてください。\n[VIEW_IMAGE: {fullpath_fixed}]"


def _save_generated_image(image: Image.Image, prompt: str, save_dir: str, room_name: str, model_comment: str = "") -> str:
    """Pollinations.ai で生成した画像を保存する。"""
    # 日時の文字列はAIが修正したがるので…
    #timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #filename = f"{room_name.lower()}_{timestamp}.png"

    # --- 画像の保存ファイル名 ---
    # uuid4の最初の8文字だけ使うなど、短くしてもユニーク性は保てます
    unique_id = uuid.uuid4().hex[:8] 
    # 保存用ファイル名をUNIXタイムスタンプにする
    # これにより「時系列順」に並び、かつAIが「時刻」として認識しにくくなります。
    # 例: 1729999999.png (2024-10-27 15:00:00相当)
    timestamp_id = int(time.time())
    # --- 画像の保存ファイル名 ---
    filename = f"PollinationsAI_{room_name.lower()}_{timestamp_id}_{unique_id}.png"

    save_path = os.path.join(save_dir, filename)

    image.save(save_path, "PNG")
    print(f"  - [{room_name}] 画像を保存しました: {save_path}")

    # --- 相対パスを絶対パスに変換 ---
    fullpath = os.path.abspath(save_path)

    # 【重要】バックスラッシュをスラッシュに置換
    # これにより AI が \ をエスケープしようとする挙動を物理的に防ぎます
    fullpath_fixed = fullpath.replace("\\", "/")

    return f"[Generated Image: {fullpath_fixed}]{model_comment}\n📝 Prompt: {prompt}\n画像生成完了。この画像についてコメントを添えてください。\n[VIEW_IMAGE: {fullpath_fixed}]"


def _generate_with_pollinations(prompt: str, model_name: str, api_key: str, save_dir: str, room_name: str) -> str:
    """Pollinations.ai へ OpenAI SDK を使わず直接リクエストして画像を生成する。"""
    if not api_key:
        return "【エラー】Pollinations.ai のAPIキーが設定されていません。"

    endpoint = "https://gen.pollinations.ai/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "NexusArk/0.2.7 PollinationsDirect",
    }
    payload = {
        "model": model_name or "flux",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }

    print(f"  [{room_name}] [Pollinations Image] POST {endpoint}, model={payload['model']}")
    response = http_requests.post(endpoint, headers=headers, json=payload, timeout=180)

    if response.status_code in (401, 403) and "blocked" in (response.text or "").lower():
        print("  [{room_name}] [Pollinations Image] POSTがブロックされたため、GET /image 経路へフォールバックします。")
        image_url = f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}"
        get_response = http_requests.get(
            image_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "image/png,image/jpeg",
                "User-Agent": "NexusArk/0.2.7 PollinationsDirect",
            },
            params={"model": payload["model"], "width": 1024, "height": 1024, "key": api_key},
            timeout=180,
        )
        if get_response.status_code != 200:
            detail = (get_response.text or "")[:300]
            return f"【エラー】Pollinations.ai APIエラー (HTTP {get_response.status_code}): {detail}"
        content_type = get_response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return f"【エラー】Pollinations.ai から画像以外のデータが返されました (Content-Type: {content_type})。"
        image = Image.open(io.BytesIO(get_response.content))
        return _save_generated_image(image, prompt, save_dir, room_name)

    if response.status_code != 200:
        detail = (response.text or "")[:300]
        return f"【エラー】Pollinations.ai APIエラー (HTTP {response.status_code}): {detail}"

    try:
        data = response.json()
    except ValueError:
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("image/"):
            image = Image.open(io.BytesIO(response.content))
            return _save_generated_image(image, prompt, save_dir, room_name)
        return "【エラー】Pollinations.ai APIからJSONでも画像でもない応答が返されました。"

    image_items = data.get("data") or []
    if not image_items:
        return "【エラー】Pollinations.ai APIから画像データが返されませんでした。"

    first_image = image_items[0]
    if first_image.get("b64_json"):
        image_data = base64.b64decode(first_image["b64_json"])
        image = Image.open(io.BytesIO(image_data))
    elif first_image.get("url"):
        image_response = http_requests.get(first_image["url"], timeout=120)
        image_response.raise_for_status()
        image = Image.open(io.BytesIO(image_response.content))
    else:
        return "【エラー】Pollinations.ai APIから画像URLまたはbase64データが返されませんでした。"

    revised_prompt = first_image.get("revised_prompt")
    model_comment = f"\nRevised Prompt: {revised_prompt}" if revised_prompt else ""
    return _save_generated_image(image, prompt, save_dir, room_name, model_comment=model_comment)


def _generate_with_huggingface(prompt: str, model_id: str, hf_token: str, save_dir: str, room_name: str) -> str:
    """Hugging Face Inference API で画像を生成する"""
    api_url = f"https://router.huggingface.co/hf-inference/models/{model_id}"
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": prompt}

    print(f"  [{room_name}] [HuggingFace Image] model={model_id}, prompt='{prompt[:80]}...'")

    response = http_requests.post(api_url, headers=headers, json=payload, timeout=120)

    if response.status_code == 503:
        # モデルがロード中の場合
        return "【エラー】Hugging Face のモデルが現在読み込み中です。数分後に再度お試しください。"
    if response.status_code == 401:
        return "【エラー】Hugging Face のAPIトークンが無効です。設定を確認してください。"
    if response.status_code == 429:
        return "【エラー】Hugging Face のレート制限に達しました。しばらく待ってから再度お試しください。"
    if response.status_code != 200:
        error_detail = response.text[:200] if response.text else "不明"
        return f"【エラー】Hugging Face APIエラー (HTTP {response.status_code}): {error_detail}"

    # レスポンスは画像バイナリ
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        return f"【エラー】Hugging Face APIから画像以外のデータが返されました (Content-Type: {content_type})。モデルがtext-to-imageタスクに対応しているか確認してください。"

    image = Image.open(io.BytesIO(response.content))

    # 日時の文字列はAIが修正したがるので…
    #timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #filename = f"{room_name.lower()}_{timestamp}.png"

    # --- 画像の保存ファイル名 ---
    # uuid4の最初の8文字だけ使うなど、短くしてもユニーク性は保てます
    unique_id = uuid.uuid4().hex[:8] 
    # 保存用ファイル名をUNIXタイムスタンプにする
    # これにより「時系列順」に並び、かつAIが「時刻」として認識しにくくなります。
    # 例: 1729999999.png (2024-10-27 15:00:00相当)
    timestamp_id = int(time.time())
    # --- 画像の保存ファイル名 ---
    filename = f"HuggingFace_{room_name.lower()}_{timestamp_id}_{unique_id}.png"

    save_path = os.path.join(save_dir, filename)

    image.save(save_path, "PNG")
    print(f"  - [{room_name}] 画像を保存しました: {save_path}")

    # --- 相対パスを絶対パスに変換 ---
    fullpath = os.path.abspath(save_path)

    # 【重要】バックスラッシュをスラッシュに置換
    # これにより AI が \ をエスケープしようとする挙動を物理的に防ぎます
    fullpath_fixed = fullpath.replace("\\", "/")

    return f"[Generated Image: {fullpath_fixed}]\n📝 Prompt: {prompt}\n画像生成完了。この画像についてコメントを添えてください。\n[VIEW_IMAGE: {fullpath_fixed}]"

# --- ローカルでの画像生成 ---
def _generate_with_local(prompt: str, save_dir: str, room_name: str, aspect_ratio: str = "square", local_sampler: str = None, local_steps: str = None, local_cfg: float = None) -> str:
    """Stable Diffusion WebUI (A1111/Forge) API で画像を生成する"""
    import uuid
    
    # 最新の設定を読み込む
    latest_config = config_manager.load_config_file()
    ls = latest_config.get("image_generation_local_settings", {})
    
    # API-URLの抽出
    url = ls.get("url", "http://127.0.0.1:7861/sdapi/v1/txt2img")
    
    if not url:
        print(f"  [{room_name}] [Local Image] API URLが未設定のため起動しません")
        return "【エラー】ローカル画像生成のURLが設定されていません。"
    
    # パラメータの抽出
    positive_prompt_prefix = ls.get("positive_prompt_prefix", "")
    positive_prompt_append = ls.get("positive_prompt_append", "")
    negative_prompt = ls.get("negative_prompt", "")
    # 値がある場合はそれを使い、ない場合は設定ファイルから取得
    sampler_name = local_sampler if local_sampler else ls.get("sampler", "Euler a")
    steps = local_steps if local_steps else ls.get("steps", 25)
    cfg_scale = local_cfg if local_cfg else ls.get("cfg_scale", 7.0)
    
    # --- ポジティブプロンプトの結合ロジック ---
    # [Prefix] + [AIのプロンプト] + [Append] をカンマで綺麗に繋ぐ
    prompt_parts = []
    if positive_prompt_prefix.strip():
        prompt_parts.append(positive_prompt_prefix.strip())
    
    prompt_parts.append(prompt.strip())
    
    if positive_prompt_append.strip():
        prompt_parts.append(positive_prompt_append.strip())
    
    full_positive_prompt = ", ".join(prompt_parts)
    
    # 解像度設定（デフォルトは1024x1024）
    size_map = {
        "square": (1024, 1024),
        "portrait": (832, 1216),
        "landscape": (1216, 832)
    }
    width, height = size_map.get(aspect_ratio.lower(), (1024, 1024))

    payload = {
        "prompt": full_positive_prompt,
        "negative_prompt": negative_prompt.strip() if negative_prompt else "",
        "steps": int(steps),
        "cfg_scale": float(cfg_scale),
        "width": width, 
        "height": height,
        "sampler_name": sampler_name
    }

    print(f"  [{room_name}] [Local Image] Requesting: {url} | Sampler: {sampler_name}, Steps: {steps}")
    print(f"  [{room_name}] [Local Image] Final Prompt: {full_positive_prompt[:100]}...")

    try:
        response = http_requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        
        data = response.json()
        img_base64 = data["images"][0]
        img_bytes = base64.b64decode(img_base64)

        # --- 画像の保存ファイル名 ---
        # uuid4の最初の8文字だけ使うなど、短くしてもユニーク性は保てます
        unique_id = uuid.uuid4().hex[:8] 
        # 保存用ファイル名をUNIXタイムスタンプにする
        # これにより「時系列順」に並び、かつAIが「時刻」として認識しにくくなります。
        # 例: 1729999999.png (2024-10-27 15:00:00相当)
        timestamp_id = int(time.time())
        # --- 画像の保存ファイル名 ---
        filename = f"Local_{room_name.lower()}_{timestamp_id}_{unique_id}.png"

        save_path = os.path.join(save_dir, filename)

        # --- 相対パスを絶対パスに変換 ---
        fullpath = os.path.abspath(save_path)

        with open(fullpath, "wb") as f:
            f.write(img_bytes)
        print(f"  - [{room_name}] 画像を保存しました: {fullpath}")

        # 【重要】バックスラッシュをスラッシュに置換
        # これにより AI が \ をエスケープしようとする挙動を物理的に防ぎます
        fullpath_fixed = fullpath.replace("\\", "/")

        return f"[Generated Image: {fullpath_fixed}]\n📝 Prompt: {prompt}\n画像生成完了。この画像についてコメントを添えてください。\n[VIEW_IMAGE: {fullpath_fixed}]"

    except Exception as e:
        print(f"  - [{room_name}] 画像生成中にエラーが発生しました: {e}")
        return f"【エラー】画像生成に失敗しました。SD WebUIが '--api' を付けて起動しているか確認してください。詳細: {str(e)}"


@tool
#def generate_image(prompt: str, room_name: str, api_key: str, api_key_name: str = None) -> str:
#    """
#    ユーザーの要望や会話の文脈に応じて、情景、キャラクター、アイテムなどのイラストを生成する。
#    成功した場合は、UIに表示するための特別な画像タグを返す。
#    prompt: 画像生成のための詳細な指示（英語が望ましい）。
#    """
#    return _generate_image_impl(prompt, room_name, api_key, api_key_name)
def generate_image(prompt: str, room_name: str, api_key: str, api_key_name: str = None, aspect_ratio: str = "square") -> str:
    """
    ユーザーの要望や会話の文脈に応じて、情景、キャラクター、アイテムなどのイラストを生成する。
    成功した場合は、UIに表示するための特別な画像タグを返す。
    prompt: 画像生成のための詳細な英語指示。
    aspect_ratio: 画像の形状。"square" (正方形 1:1), "portrait" (縦長 2:3), "landscape" (横長 3:2) から選択してください。
    """
    return _generate_image_impl(prompt, room_name, api_key, api_key_name, aspect_ratio=aspect_ratio)

def _generate_image_impl(
    prompt: str, 
    room_name: str, 
    api_key: str, 
    api_key_name: str = None,
    provider: str = None,
    model_name: str = None,
    openai_profile_name: str = None,
    save_subdir: str = "generated_images",
    aspect_ratio: str = "square", # 追加
    local_sampler_override: str = None,
    local_steps_override: str = None,
    local_cfg_override: float = None
) -> str:
    """generate_image の実体ロジック（他のツールからも呼び出し可能）"""
    # --- 最新の設定を読み込む ---
    latest_config = config_manager.load_config_file()

    # 引数で指定されていない場合は設定ファイルから取得
    if provider is None:
        provider = latest_config.get("image_generation_provider", "gemini")
    
    if model_name is None:
        model_name = latest_config.get("image_generation_model", "gemini-2.5-flash-image")

    # [2026-04-29] 画像生成設定で専用のAPIキーが指定されている場合、それを最優先する
    # (Google無料キーでは不可能なため、有料キーが設定されていればそちらを強制的に使う)
    image_gen_key_name = latest_config.get("image_generation_api_key_name")
    if provider == "gemini" and image_gen_key_name:
        configured_key = config_manager.GEMINI_API_KEYS.get(image_gen_key_name)
        if configured_key and not configured_key.startswith("YOUR_API_KEY"):
            api_key = configured_key
            api_key_name = image_gen_key_name
            print(f"  - [{room_name}] 画像生成設定の専用キーを優先使用します: {api_key_name}")
    
    # api_key_name が未指定の場合は逆引きで特定
    if not api_key_name:
        api_key_name = config_manager.get_api_key_name_by_value(api_key)

    openai_settings = latest_config.get("image_generation_openai_settings", {})
    if openai_profile_name:
        # 明示的な指定がある場合はプロファイルを上書き
        openai_settings = openai_settings.copy()
        openai_settings["profile_name"] = openai_profile_name
        openai_settings["model"] = model_name

    # プロバイダが無効の場合（ツール経由のみチェック）
    if provider == "disabled":
        return "【エラー】画像生成機能は現在、設定で無効化されています。"

    if not room_name:
        return "【エラー】画像生成にはルーム名が必須です。"

    # ログ表示用の実際のモデル名を特定
    actual_model_name = model_name
    if provider == "openai":
        actual_model_name = openai_settings.get("model", model_name)
    elif provider == "pollinations":
        # 明示的な指定がない場合は設定値を使用
        if not model_name or model_name == latest_config.get("image_generation_model"):
            actual_model_name = latest_config.get("image_generation_pollinations_model", "flux")
    elif provider == "huggingface":
        if not model_name or model_name == latest_config.get("image_generation_model"):
            actual_model_name = latest_config.get("image_generation_huggingface_model", "black-forest-labs/FLUX.1-schnell")

    print(f"--- [{room_name}] 画像生成ツール実行 (Provider: {provider}, Model: {actual_model_name}, Key: {api_key_name}, Prompt: '{prompt[:100]}...') ---")

    try:
        #save_dir = os.path.join("characters", room_name, save_subdir)
        save_subsubdir = datetime.datetime.now().strftime('%Y-%m') 
        save_dir = os.path.join("characters", room_name, save_subdir, save_subsubdir)
        os.makedirs(save_dir, exist_ok=True)

        if provider == "gemini":
            # Gemini用のAPIキーを使用
            if not api_key:
                return "【エラー】Gemini画像生成にはAPIキーが必須です。"
            return _generate_with_gemini(prompt, actual_model_name, api_key, save_dir, room_name, api_key_name=api_key_name)
        
        elif provider == "openai":
            # OpenAI互換設定を取得（プロファイル名から設定を参照）
            profile_name = openai_settings.get("profile_name", "")
            openai_model = openai_settings.get("model", model_name)
            
            # プロファイルからBase URLとAPIキーを取得
            openai_provider_settings = latest_config.get("openai_provider_settings", [])
            target_profile = None
            for profile in openai_provider_settings:
                if profile.get("name") == profile_name:
                    target_profile = profile
                    break
            
            if not target_profile:
                return f"【エラー】画像生成用のOpenAI互換プロファイル '{profile_name}' が見つかりません。「共通設定」→「画像生成設定」でプロファイルを設定してください。"
            
            openai_base_url = target_profile.get("base_url", "https://api.openai.com/v1")
            openai_api_key = target_profile.get("api_key", "")
            
            # Pollinations.ai の場合、プロファイルにキーがなければグローバル設定のキーをフォールバックとして試す
            if "pollinations.ai" in openai_base_url.lower() and (not openai_api_key or "YOUR_API_KEY" in openai_api_key):
                poll_api_key = latest_config.get("pollinations_api_key", "")
                if poll_api_key and "YOUR_API_KEY" not in poll_api_key:
                    openai_api_key = poll_api_key
                    print(f"  - [{room_name}] OpenAIプロファイルのキーが未設定のため、共通設定のPollinationsキーを使用します。")

            if not openai_api_key or "YOUR_API_KEY" in openai_api_key:
                return f"【エラー】プロファイル '{profile_name}' にAPIキーが設定されていません。「APIキー / Webhook管理」でAPIキーを設定してください。"

            if "pollinations.ai" in openai_base_url.lower():
                return "【エラー】Pollinations.ai は画像生成の専用プロバイダとして利用してください。プロバイダを「Pollinations.ai」に切り替えてください。"
            
            #return _generate_with_openai(prompt, openai_model, openai_base_url, openai_api_key, save_dir, room_name)
            return _generate_with_openai(prompt, openai_model, openai_base_url, openai_api_key, save_dir, room_name, aspect_ratio=aspect_ratio)
        
        elif provider == "pollinations":
            # Pollinations.ai は OpenAI 互換 API
            poll_api_key = latest_config.get("pollinations_api_key", "")
            poll_model = latest_config.get("image_generation_pollinations_model", "flux")
            if not poll_api_key:
                return "【エラー】Pollinations.ai のAPIキーが設定されていません。「共通設定」→「画像生成設定」でAPIキーを入力してください。\nAPIキーは https://enter.pollinations.ai で取得できます。"
            return _generate_with_pollinations(prompt, poll_model, poll_api_key, save_dir, room_name)
        
        elif provider == "huggingface":
            # Hugging Face Inference API
            hf_token = latest_config.get("huggingface_api_token", "")
            hf_model = latest_config.get("image_generation_huggingface_model", "black-forest-labs/FLUX.1-schnell")
            if not hf_token:
                return "【エラー】Hugging Face のAPIトークンが設定されていません。「共通設定」→「画像生成設定」でトークンを入力してください。\nトークンは https://huggingface.co/settings/tokens で取得できます。"
            return _generate_with_huggingface(prompt, hf_model, hf_token, save_dir, room_name)
        
        # --- ローカル画像生成
        elif provider == "local":
            # ローカルSD用の処理
            return _generate_with_local(
                prompt, 
                save_dir, 
                room_name, 
                aspect_ratio=aspect_ratio, 
                local_sampler=local_sampler_override, 
                local_steps=local_steps_override, 
                local_cfg=local_cfg_override
            )
        
        else:
            return f"【エラー】不明な画像生成プロバイダ: {provider}"

    except httpx.RemoteProtocolError as e:
        print(f"  - [{room_name}] 画像生成ツールでサーバー切断エラー: {e}")
        return "【エラー】サーバーが応答せずに接続を切断しました。プロンプトを簡潔にして、もう一度試してみてください。"
    except genai.errors.ServerError as e:
        print(f"  - [{room_name}] 画像生成ツールでサーバーエラー(500番台): {e}")
        return "【エラー】サーバー側で内部エラー(500)が発生しました。プロンプトをよりシンプルにして、もう一度試してみてください。"
    except genai.errors.ClientError as e:
        print(f"  - [{room_name}] 画像生成ツールでクライアントエラー(400番台): {e}")
        return f"【エラー】APIリクエストが無効です(400番台)。詳細: {e}"
    except Exception as e:
        print(f"  - [{room_name}] 画像生成ツールで予期せぬエラー: {e}")
        traceback.print_exc()
        return f"【エラー】画像生成中に予期せぬ問題が発生しました。詳細: {e}"

def generate_image_caption(image_path: str, api_key_name: str = None) -> str:
    """画像のキャプション（テキスト説明）を生成する"""
    import google.genai as genai
    from PIL import Image
    import config_manager
    
    try:
        # Load config to get API key if not provided
        if not api_key_name:
            latest_config = config_manager.load_config_file()
            # fallback to global setting if no key provided
            api_key_name = latest_config.get("global_google_api_key_name")
            
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return "（キャプション生成エラー: 有効なAPIキーがありません）"
            
        client = genai.Client(api_key=api_key)
        
        # Use a fast multimodal model for captioning
        model_name = "gemini-2.5-flash"
        
        image = Image.open(image_path)
        
        prompt = "この画像の内容を、要点に絞って事実ベースで簡潔に説明してください。各項目は1〜2文程度で記述してください：\n1. 被写体と状態（何が、どのような様子で写っているか）\n2. 背景・シチュエーション（場所や状況、ブランド等）\n3. 主要な特徴（色、形、目立つディテール）"
        
        response = client.models.generate_content(
            model=model_name,
            contents=[image, prompt],
        )
        
        if response.text:
            return response.text.strip()
        else:
            return "（画像のキャプションを生成できませんでした）"
            
    except Exception as e:
        print(f"--- [{room_name}] [画像キャプション生成エラー] {e} ---")
        return f"（画像キャプション生成エラー: {str(e)}）"

@tool
def view_past_image(image_path: str, room_name: str = "") -> str:
    """
    過去の画像（イラストや写真）の詳細な内容を思い出すために、指定されたパスの画像を視覚メモリにロードします。
    引数 image_path には、過去の記憶などにある [VIEW_IMAGE: path/to/image.png] などのタグから抽出したファイルパスを指定します。
    ファイルパスが不明な場合は、ファイル名のみ（例: roblox_screen_...）を指定しても構いません。
    【重要】画像パスを read_project_file や read_url_tool で読み込んではいけません（文字化けします）。必ずこの view_past_image ツールを使用してください。
    """
    import os
    
    # パスが直接存在する場合
    if os.path.exists(image_path):
        target_path = image_path
    else:
        # 見つからない場合、ルーム固有のディレクトリを検索する
        found_path = None
        if room_name:
            search_dirs = [
                os.path.join("characters", room_name, "images", "roblox_screenshots"),
                os.path.join("characters", room_name, "generated_images"),
                os.path.join("characters", room_name, "images")
            ]
            filename = os.path.basename(image_path)
            # AIが拡張子を忘れたり、末尾に「...」をつけたりする場合のサニタイズ
            filename = filename.split("...")[0].strip()
            if not filename.endswith(".png") and not filename.endswith(".jpg"):
                filename += ".png" # デフォルト

            for d in search_dirs:
                potential_path = os.path.join(d, filename)
                if os.path.exists(potential_path):
                    found_path = potential_path
                    break
        
        if found_path:
            target_path = found_path
        else:
            return f"【エラー】指定された画像パスが見つかりません: {image_path} (検索したディレクトリ: characters/{room_name}/...)"

    # この特別なタグを返すことで、メインのトークルーチン（gemini_api.py）が検知し
    # 次のAPIコールの際に実際の画像をマルチモーダル入力として付与する仕組み
    return f"[VIEW_IMAGE: {target_path}]\n※システムメッセージ: 画像が視覚野にロードされました。"
