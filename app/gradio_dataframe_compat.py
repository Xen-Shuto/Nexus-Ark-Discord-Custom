"""Scoped workaround for recursive TanStack options in Gradio 6.14.0.

Serve a patched response for the exact affected asset, without modifying the
installed Gradio files. Unknown versions/assets are deliberately left alone.
"""
from hashlib import sha256
from pathlib import Path

ASSET_NAME = "Index-CytOJC_D.js"
ASSET_SHA256 = "e2d33126a35ea0737944c9ef52f23a71241c297714908a17086fcd6cca210436"
VERSIONED_ASSET = "nexus-stable-base-v5-" + ASSET_NAME
LOADER_NAME = "i18n-BlwlR3g4.js"
LOADER_SHA256 = "9cc272feeadf20dfee8374f4cca2aef484b2d9b797c6348beac5cc0385f643f9"
OLD = b"n.setOptions(s=>yt(s,e,{state:"
NEW = b"n.setOptions(s=>yt(t,e,{state:"
RESET_OLD = b"function Xo(e){const t=yt({state:{},onStateChange(){}"
RESET_NEW = b"function Xo(e){const t=yt({autoResetPageIndex:!1,state:{},onStateChange(){}"
EFFECT_OLD = b"return i(),rn(()=>{i()}),{getRowModel:"
EFFECT_NEW = b"return i(),rn(()=>{l(r);e.data;e.columns;Object.values(e.state||{});Gr(()=>{i();p(o,l(o)+1)})}),{getRowModel:"
CALLBACK_OLD = b"onStateChange:a=>{a instanceof Function?p(r,a(l(r)),!0):p(r,yt(l(r),a),!0),p(o,l(o)+1),e.onStateChange?.(a)}"
CALLBACK_NEW = b"onStateChange:a=>Gr(()=>{a instanceof Function?p(r,a(l(r)),!0):p(r,yt(l(r),a),!0),p(o,l(o)+1),e.onStateChange?.(a)})"


def patch_asset(data: bytes) -> bytes:
    if sha256(data).hexdigest() != ASSET_SHA256 or any(data.count(old) != 1 for old in (OLD, RESET_OLD, EFFECT_OLD, CALLBACK_OLD)):
        raise ValueError("Unrecognized Gradio Dataframe asset; compatibility patch refused")
    # Reuse stable initial options, then apply current props and current state.
    # Retaining previous lazy options grows a getter chain on every update.
    # Eagerly spreading them also adds unwanted Svelte effect dependencies.
    # This table uses virtual scrolling, not TanStack pagination. Page resets
    # needlessly update internal state and can feed the reactive effect again.
    # Gr is Svelte's untrack export in this exact bundle. Track internal state
    # explicitly; updating table options/callbacks must not subscribe the caller
    # to values that those same callbacks subsequently write.
    # Also track data, columns and controlled state. Reading only internal state
    # leaves the effect asleep on server updates. Notify row/header consumers
    # after options change, outside tracking, including same-length replacements.
    marker = b'globalThis.__nexusDataframeCompat="stable-base-v5";document.documentElement.setAttribute("data-nexus-dataframe-compat","stable-base-v5");\n'
    return marker + data.replace(OLD, NEW, 1).replace(RESET_OLD, RESET_NEW, 1).replace(EFFECT_OLD, EFFECT_NEW, 1).replace(CALLBACK_OLD, CALLBACK_NEW, 1)


def patch_loader(data: bytes) -> bytes:
    target = ("./" + ASSET_NAME).encode()
    if sha256(data).hexdigest() != LOADER_SHA256 or data.count(target) != 2:
        raise ValueError("Unrecognized Dataframe loader")
    # Rewrite both the module preload and the dynamic import. Relative imports
    # inside the renamed asset still resolve in the same assets directory.
    return data.replace(target, ("./" + VERSIONED_ASSET).encode())


class DataframeAssetMiddleware:
    def __init__(self, app, asset: bytes, loader_asset: bytes | None = None):
        self.app = app
        self.asset = asset
        self.loader_asset = loader_asset

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in {"GET", "HEAD"}:
            path = scope["path"]
            body = None
            if path.endswith(("/assets/" + ASSET_NAME, "/assets/" + VERSIONED_ASSET)):
                body = self.asset
            elif self.loader_asset and path.endswith("/assets/" + LOADER_NAME):
                body = self.loader_asset
            if body is None:
                return await self.app(scope, receive, send)
            headers = [(b"content-type", b"text/javascript; charset=utf-8"),
                       (b"content-length", str(len(body)).encode()),
                       (b"cache-control", b"no-store"),
                       (b"x-nexus-dataframe-compat", b"stable-base-v5")]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": body if scope["method"] == "GET" else b""})
            return
        await self.app(scope, receive, send)


def dataframe_app_kwargs(gradio_module) -> dict:
    if gradio_module.__version__ != "6.14.0":
        return {}
    asset_path = Path(gradio_module.__file__).parent / "templates/frontend/assets" / ASSET_NAME
    try:
        asset = patch_asset(asset_path.read_bytes())
        loader_asset = patch_loader((asset_path.parent / LOADER_NAME).read_bytes())
    except (OSError, ValueError) as error:
        print(f"--- [UI Compat] Dataframe workaround not applied: {error} ---")
        return {}
    from starlette.middleware import Middleware
    print("--- [UI Compat] Gradio 6.14.0 Dataframe stable base options enabled ---")
    return {"middleware": [Middleware(DataframeAssetMiddleware, asset=asset, loader_asset=loader_asset)]}
