"""Scoped workaround for the verified Gradio 6.14.0 tab-reference loop.

Only the exact known bundle is patched in HTTP responses. Installed packages
are never modified, and unknown bundles pass through unchanged.
"""
from hashlib import sha256
from pathlib import Path

ASSET_NAME = "Walkthrough.svelte_svelte_type_style_lang-rs0AIEfA.js"
ASSET_SHA256 = "5e5a7c87202f63b68dde4c1ad1de9834689afd057aebc07b6714dd3cb71e1442"
OLD = b"a[t]&&!se.has(t)&&K(l,e(l)[t]=a[t])"
NEW = (b"a[t]&&!se.has(t)&&JSON.stringify(e(l)[t])!==JSON.stringify(a[t])"
       b"&&K(l,e(l)[t]=a[t])")
REVISION = "initial-tabs-v3"


def patch_tabs_asset(data):
    if sha256(data).hexdigest() != ASSET_SHA256 or data.count(OLD) != 1:
        raise ValueError("Unrecognized Tabs bundle")
    # Se synchronizes metadata for children not yet mounted. In a legacy
    # reactive effect it must not mutate the tab array when metadata already
    # matches: that mutation reschedules each/bind effects and Se itself.
    # The runtime write trace identified Se repeatedly updating this source.
    # Keep the mounted-child exclusion and apply all actual metadata changes.
    marker = (
        b'globalThis.__nexusTabsCompat="initial-tabs-v3";'
        b'document.documentElement.setAttribute("data-nexus-tabs-compat","initial-tabs-v3");\n'
    )
    return marker + data.replace(OLD, NEW, 1)


class TabsAssetMiddleware:
    def __init__(self, app, asset):
        self.app = app
        self.asset = asset

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] in {"GET", "HEAD"}
                and scope["path"].endswith("/assets/" + ASSET_NAME)):
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/javascript; charset=utf-8"),
                (b"content-length", str(len(self.asset)).encode()),
                (b"cache-control", b"no-store"),
                (b"x-nexus-tabs-compat", REVISION.encode()),
            ]})
            await send({"type": "http.response.body",
                        "body": self.asset if scope["method"] == "GET" else b""})
            return
        await self.app(scope, receive, send)


def launch_ui_compat(gradio_module):
    if gradio_module.__version__ != "6.14.0":
        return {}
    path = Path(gradio_module.__file__).parent / "templates/frontend/assets" / ASSET_NAME
    try:
        asset = patch_tabs_asset(path.read_bytes())
    except (OSError, ValueError) as error:
        print(f"--- [UI Compat] Tabs workaround skipped: {error} ---")
        return {}
    from starlette.middleware import Middleware
    from gradio_dataframe_compat import dataframe_app_kwargs
    print("--- [UI Compat] Gradio 6.14.0 initial tab sync guard enabled ---")
    middlewares = [Middleware(TabsAssetMiddleware, asset=asset)]
    middlewares.extend(dataframe_app_kwargs(gradio_module).get("middleware", []))
    return {"app_kwargs": {"middleware": middlewares}}
