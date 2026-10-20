"""Opt-in browser freeze diagnostics; no model, form values, or credentials."""
import datetime
import hashlib
import json
from pathlib import Path
import threading

ENDPOINT = "/__nexus_ui_freeze"
CORE = "index-B5CnGmTK.js"
CORE_HASH = "c469e6f8fd8c2d12d23d0e9077f6bb1db2f37e49d410e2b12b7cff9a053e0018"
BINDING = "i18n-BlwlR3g4.js"
BINDING_HASH = "9cc272feeadf20dfee8374f4cca2aef484b2d9b797c6348beac5cc0385f643f9"
HEAD = """<script>
(() => {
  const events = []; let reports = 0;
  const report = (kind, detail) => {
    if (reports++ >= 16) return;
    navigator.sendBeacon('/__nexus_ui_freeze', JSON.stringify({
      kind, detail, events: events.slice(-12), browser: navigator.userAgent,
      elapsed: Math.round(performance.now())
    }));
  };
  document.addEventListener('click', e => {
    const el = e.target.closest('button,[role="tab"],summary');
    if (!el) return;
    events.push({tag:el.tagName,id:el.id,role:el.getAttribute('role'),
      parent:el.closest('[id]:not([id=""])')?.id,time:Math.round(performance.now())});
    if (events.length > 12) events.shift();
    if(el.closest('.overflow-menu'))setTimeout(()=>{
      const menu=document.querySelector('#top_level_tabs > .tab-wrapper .overflow-dropdown:not(.hide)');
      if(!menu)return;
      const rect=menu.getBoundingClientRect(),x=rect.left+rect.width/2,y=rect.top+15;
      const describe=node=>({tag:node.tagName,id:node.id,classes:String(node.className).slice(0,150),
        z:getComputedStyle(node).zIndex,position:getComputedStyle(node).position});
      report('menu-layer',{hits:document.elementsFromPoint(x,y).slice(0,5).map(describe),
        wrapper:describe(menu.closest('.tab-wrapper')),menu:describe(menu)});
    },0);
  }, true);
  window.addEventListener('error', e => report('error', {
    message:e.message, file:e.filename.split('?')[0], line:e.lineno,
    column:e.colno, stack:String(e.error?.stack||'').slice(0,8000),
    compatibility:{tabs:globalThis.__nexusTabsCompat||null,dataframe:globalThis.__nexusDataframeCompat||null}
  }));
  window.addEventListener('unhandledrejection', e => report('rejection', {
    message:String(e.reason).slice(0,2000),stack:String(e.reason?.stack||'').slice(0,8000)
  }));
  const writeCounts=new WeakMap(), writeIds=new WeakMap(), writes=[];let nextWriteId=0;
  const shape=value=>{
    if(Array.isArray(value))return {type:'array',length:value.length,
      tabs:value.slice(0,4).map(x=>x && typeof x==='object'?{id:x.id,component_id:x.component_id}:typeof x)};
    if(value && typeof value==='object')return {type:'object',keys:Object.keys(value).slice(0,8),node:value.tagName};
    return {type:typeof value};
  };
  globalThis.__nexusFreezeWrite=(source,value,effect)=>{
    const count=(writeCounts.get(source)||0)+1;writeCounts.set(source,count);
    if(count<20)return;
    if(!writeIds.has(source))writeIds.set(source,++nextWriteId);
    writes.push({source:writeIds.get(source),count,previous:shape(source.v),next:shape(value),
      effect:String(effect?.fn||'').slice(0,1200),stack:String(new Error().stack||'').slice(0,1800)});
    if(writes.length>6)writes.shift();
  };
  globalThis.__nexusFreezeEffect = effect => {
    report('write-trace',{writes:writes.slice()});
    const chain=[];
    while(effect && chain.length<6){chain.push(String(effect.fn).slice(0,1800));effect=effect.parent;}
    report('effect-depth', {chain});
  };
  const bindingCounts = new WeakMap();
  globalThis.__nexusFreezeBinding = (element,setter,getter,parts,rawEqual) => {
    if (!element || !['object','function'].includes(typeof element)) return;
    const count=(bindingCounts.get(element)||0)+1; bindingCounts.set(element,count);
    if(count!==20) return;
    report('binding-repeat',{count,rawEqual,strictEqual:element===getter(...parts),
      setter:String(setter).slice(0,2000),getter:String(getter).slice(0,2000),
      node:element.nodeType?{tag:element.tagName,id:element.id}:null,
      keys:Object.keys(element).slice(0,12),parts:parts.map(p=>
        p && typeof p==='object'?{id:p.id,component_id:p.component_id}:typeof p)});
  };
  globalThis.__nexusFreezeBindingMode = mode => report('binding-mode',{mode});
  document.documentElement.setAttribute('data-nexus-ui-diagnostics','v1');
  report('loaded',{});
  let compatibilityCount=0;
  const compatibilityTimer=setInterval(()=>{
    report('compatibility',{tabs:globalThis.__nexusTabsCompat||null,
      dataframe:globalThis.__nexusDataframeCompat||null});
    if(++compatibilityCount>=3)clearInterval(compatibilityTimer);
  },2000);
})();
</script>"""


class FreezeDiagnosticsMiddleware:
    def __init__(self, app, log_path, core_asset, binding_asset=None):
        self.app = app
        self.log_path = Path(log_path)
        self.core_asset = core_asset
        self.binding_asset = binding_asset
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == ENDPOINT and scope["method"] == "POST":
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"")
            expected = scope.get("scheme", "http").encode() + b"://" + headers.get(b"host", b"")
            if origin != expected:
                return await self.respond(send, 403, b"")
            body = bytearray()
            while True:
                part = await receive()
                if part["type"] == "http.disconnect":
                    return
                body.extend(part.get("body", b""))
                if len(body) > 24000:
                    return await self.respond(send, 413, b"")
                if not part.get("more_body"):
                    break
            try:
                record = json.loads(body)
                if not isinstance(record, dict) or record.get("kind") not in {"loaded", "error", "rejection", "effect-depth", "binding-repeat", "binding-mode", "compatibility", "write-trace", "menu-layer"}:
                    raise ValueError("Invalid diagnostic record")
            except (ValueError, UnicodeDecodeError):
                return await self.respond(send, 400, b"")
            record["received"] = datetime.datetime.now().astimezone().isoformat()
            with self.lock:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                # Cap diagnostics instead of allowing an update loop to fill disk.
                if not self.log_path.exists() or self.log_path.stat().st_size < 2_000_000:
                    with self.log_path.open("a", encoding="utf-8") as output:
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
            return await self.respond(send, 204, b"")
        if self.core_asset and path.endswith("/assets/" + CORE) and scope["method"] in {"GET", "HEAD"}:
            return await self.respond(send, 200, self.core_asset, scope["method"] == "HEAD")
        if self.binding_asset and path.endswith("/assets/" + BINDING) and scope["method"] in {"GET", "HEAD"}:
            asset = self.binding_asset
            mode = b"diagnostics-only"
            asset = b'globalThis.__nexusFreezeBindingMode?.("' + mode + b'");\n' + asset
            return await self.respond(send, 200, asset, scope["method"] == "HEAD")
        return await self.app(scope, receive, send)

    @staticmethod
    async def respond(send, status, body, head=False):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/javascript; charset=utf-8"),
                                (b"cache-control", b"no-store"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": b"" if head else body})


def launch_diagnostics(gradio_module, log_path):
    from starlette.middleware import Middleware
    asset = None
    path = Path(gradio_module.__file__).parent / "templates/frontend/assets" / CORE
    old = b"function uo(){try{Di()}"
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == CORE_HASH and raw.count(old) == 1:
            # Observe the fatal update-depth condition; do not change its behavior.
            asset = raw.replace(old, b"function uo(){globalThis.__nexusFreezeEffect?.(Wt);try{Di()}", 1)
            write_old = b"function bt(e,t){if(!e.equals(t)){"
            if raw.count(write_old) == 1:
                asset = asset.replace(write_old,
                    write_old + b"at(()=>globalThis.__nexusFreezeWrite?.(e,t,g));", 1)
    except OSError:
        pass
    binding_asset = None
    try:
        raw = (path.parent / BINDING).read_bytes()
        old_binding = b"W(()=>{e!==r(...o)&&"
        if hashlib.sha256(raw).hexdigest() == BINDING_HASH and raw.count(old_binding) == 1:
            binding_asset = raw.replace(old_binding,
                b"W(()=>{globalThis.__nexusFreezeBinding?.(e,t,r,o,cr(r(...o),e));e!==r(...o)&&", 1)
    except OSError:
        pass
    print(f"--- [UI Diagnostics] enabled; effect trace={asset is not None}; log={log_path} ---")
    return {"head": HEAD, "app_kwargs": {"middleware": [Middleware(
        FreezeDiagnosticsMiddleware, log_path=str(log_path), core_asset=asset,
        binding_asset=binding_asset)]}}
