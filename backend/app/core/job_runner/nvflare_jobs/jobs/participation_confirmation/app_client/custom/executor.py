import json
import os
import time
import socket
import threading
import webbrowser
import secrets
import hashlib
import platform
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler

from nvflare.apis.executor import Executor
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable
from nvflare.apis.dxo import DXO, DataKind, MetaKey


class CustomExecutor(Executor):
    def __init__(
        self,
        filters_path: str = "custom/filters.json",
        confirm_timeout_sec: int = 900,
        headless_default: str = "reject",
        dialog_title: str = "Participation Confirmation",
        consent_version: str = "2025-10-30",
    ):
        self.filters_path_arg = filters_path
        self.confirm_timeout_sec = confirm_timeout_sec
        self.headless_default = headless_default
        self.dialog_title = dialog_title
        self.consent_version = consent_version

        self.consent_mode = "service"

        try:
            print(
                "[Exec] __init__: "
                f"consent_mode={self.consent_mode} "
                f"filters_path={self.filters_path_arg} "
                f"confirm_timeout_sec={self.confirm_timeout_sec} "
                f"headless_default={self.headless_default} "
                f"dialog_title={self.dialog_title} "
                f"consent_version={self.consent_version}",
                flush=True,
            )
            print(
                "[Exec] __init__: pid="
                f"{os.getpid()} user={os.getenv('USER') or os.getenv('USERNAME') or 'unknown'} "
                f"cwd={os.getcwd()} platform={platform.platform()} "
                f"python={platform.python_version()}",
                flush=True,
            )
            interesting_env = [
                "DUALITY_BACKEND_URL",
                "CONSENT_MODE",
                "PYTHONPATH",
                "NVFLARE_API_PACKAGE",
            ]
            for k in interesting_env:
                if k in os.environ:
                    print(f"[Exec] __init__: ENV {k}={os.environ.get(k)}", flush=True)
        except Exception as e:
            print(f"[Exec] __init__: env/OS dump error: {e}", flush=True)

    @staticmethod
    def _exists(p: Optional[Path]) -> bool:
        return bool(p and p.exists())

    def _resolve_filters_path(self, fl_ctx: FLContext) -> Tuple[Optional[Path], Iterable[Path]]:
        rel = Path(self.filters_path_arg)
        if rel.is_absolute() and rel.exists():
            print(f"[Exec] _resolve_filters_path: absolute path found -> {rel}", flush=True)
            return rel, []
        app_root_ctx = fl_ctx.get_prop("app_root", None)
        job_id = fl_ctx.get_prop("job_id", None)
        site_name = fl_ctx.get_prop("site_name", None)
        bases: list[Path] = []
        if app_root_ctx:
            bases.append(Path(app_root_ctx))
        if job_id and site_name:
            bases.append(Path.cwd() / str(job_id) / f"app_{site_name}")
        bases.append(Path.cwd())
        module_dir = Path(__file__).resolve().parent
        bases.append(module_dir)
        bases.append(module_dir.parent)
        for b in bases:
            candidate = (b / rel).resolve()
            if candidate.exists():
                try:
                    st = candidate.stat()
                    print(
                        f"[Exec] _resolve_filters_path: found -> {candidate} "
                        f"(size={st.st_size} mode={oct(st.st_mode)})",
                        flush=True,
                    )
                except Exception:
                    print(f"[Exec] _resolve_filters_path: found -> {candidate}", flush=True)
                return candidate, bases
        print(f"[Exec] _resolve_filters_path: NOT FOUND; searched bases: {[str(b) for b in bases]}", flush=True)
        return None, bases

    def _share(self, weights: Dict[str, float], steps: float, agg: float, meta: Dict[str, Any]) -> Shareable:
        dxo = DXO(data_kind=DataKind.WEIGHTS, data=weights)
        dxo.set_meta_prop(MetaKey.NUM_STEPS_CURRENT_ROUND, steps)
        dxo.set_meta_prop("aggregation_weight", agg)
        for k, v in meta.items():
            dxo.set_meta_prop(k, v)

        conf = meta.get("confirmation")
        task = meta.get("task_name")
        filt_id = meta.get("filter_id")
        print(
            f"[Exec] _share: task={task} confirmation={conf} filter_id={filt_id} steps={steps} agg={agg}",
            flush=True,
        )
        return dxo.to_shareable()

    def _free_port(self) -> int:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        print(f"[Exec] _free_port: allocated {p}", flush=True)
        return p

    def _hash_filters(self, d: Dict[str, Any]) -> str:
        try:
            s = json.dumps(d, sort_keys=True, separators=(",", ":"))
        except Exception:
            s = ""
        base = f"{self.consent_version}|{s}"
        h = hashlib.sha256(base.encode()).hexdigest()
        print(f"[Exec] _hash_filters: len={len(s)} sha256={h}", flush=True)
        return h

    @staticmethod
    def _has_desktop_env() -> bool:
        sys = platform.system()
        if sys in ("Windows", "Darwin"):
            return True
        if sys == "Linux":
            return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        return False

    def _preflight_or_reject(self) -> Optional[str]:
        if self.consent_mode == "service":
            print("[Exec] _preflight_or_reject: service mode -> no preflight reject", flush=True)
            return None
        if not self._has_desktop_env():
            print("[Exec] _preflight_or_reject: NO desktop env -> reject", flush=True)
            return "no_desktop"
        return None

    def _serve_local_confirm(
        self, title: str, consent_text: str, filters: Dict[str, Any], timeout_sec: int, abort_signal
    ) -> Optional[bool]:
        decision = {"val": None}
        token = secrets.token_urlsafe(24)
        done = threading.Event()
        port = self._free_port()

        filt_str = json.dumps(filters, indent=2)

        fn_map: Dict[str, Dict[str, Any]] = {}
        try:
            raw_fm = filters.get("functions_map")
            if isinstance(raw_fm, dict):
                for k, v in raw_fm.items():
                    name = str(k).strip()
                    if not name:
                        continue

                    base: Dict[str, Any] = {}
                    if isinstance(v, dict):
                        base = v
                    elif isinstance(v, list) and v:
                        first = v[0]
                        if isinstance(first, dict):
                            base = first
                        else:
                            base = {}
                    else:
                        base = {}

                    if not isinstance(base, dict):
                        base = {}

                    fn_map[name] = base
        except Exception:
            fn_map = {}

        functions_list: list[str] = sorted(fn_map.keys()) if fn_map else []

        if functions_list:
            fns_html = "<ul>" + "".join(f"<li><code>{name}</code></li>" for name in functions_list) + "</ul>"
        else:
            fns_html = "<p><i>No functions provided.</i></p>"

        if fn_map:
            cfg_sections = []
            for fn_name in sorted(fn_map.keys()):
                kv = fn_map.get(fn_name) or {}
                if kv:
                    rows = "".join(
                        f"<tr><td><code>{prop}</code></td><td><code>{str(val)}</code></td></tr>"
                        for prop, val in sorted(kv.items(), key=lambda x: x[0].lower())
                    )
                    table = (
                        "<table class='kv'>"
                        "<thead><tr><th>Property</th><th>Value</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table>"
                    )
                else:
                    table = "<p><i>No config properties for this function.</i></p>"
                cfg_sections.append(f"<section><h3>{fn_name}</h3>{table}</section>")
            fn_cfg_html = "".join(cfg_sections)
        else:
            fn_cfg_html = "<p><i>No function configs provided.</i></p>"

        css = """<style>
:root {
  --accent: #3F5FFF;
  --accent-2: #3FD28B;
  --bg: #f9f9f9;
  --text: #212121;
  --muted: #666;
  --border: #ddd;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
  background-color: var(--bg);
  color: var(--text);
  margin: 0;
}
.container {
  max-width: 960px;
  margin: 4rem auto 3rem auto;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.06);
  overflow: hidden;
}
.header {
  padding: 1.2rem 1.5rem;
  background: linear-gradient(180deg, #ffffff 0%, #f6f8ff 100%);
  border-bottom: 1px solid var(--border);
}
.header h2 {
  margin: 0 0 .25rem 0;
  font-weight: 600;
  letter-spacing: .2px;
  color: var(--accent);
}
.header p {
  margin: 0;
  color: var(--muted);
}
.content {
  padding: 1.25rem 1.5rem 0 1.5rem;
}
.section { margin-bottom: 1.25rem; }
.section h3 {
  margin: 0 0 .5rem 0;
  font-weight: 600;
  color: var(--text);
}
.section p { margin: 0.25rem 0; color: var(--muted); }
pre.json {
  margin: .5rem 0 0 0;
  background: #f6f6f6;
  border: 1px solid #eee;
  border-radius: 6px;
  padding: .75rem;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: .9rem;
  line-height: 1.35;
}
ul { margin: .5rem 0 0 1.25rem; }
code { background: #f4f4ff; padding: 2px 4px; border-radius: 4px; }
table.kv {
  width: 100%;
  border-collapse: collapse;
  margin: .25rem 0 0 0;
  font-size: .95rem;
}
table.kv thead th {
  text-align: left;
  border-bottom: 1px solid var(--border);
  padding: .5rem .4rem;
  color: #333;
}
table.kv tbody td {
  border-bottom: 1px solid #f0f0f0;
  padding: .45rem .4rem;
  vertical-align: top;
}
.footer {
  padding: 1rem 1.5rem 1.25rem 1.5rem;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
  gap: .8rem;
  background: #fff;
}
button {
  background-color: var(--accent);
  color: white;
  border: none;
  padding: 0.65rem 0.9rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.95rem;
  min-width: 140px;
  transition: background-color 0.2s ease, transform 0.15s ease, box-shadow 0.2s;
  box-shadow: 0 2px 6px rgba(63,95,255,0.15);
}
button:hover { background-color: #2F4FCC; }
button:active { transform: translateY(1px); }
button.secondary {
  background-color: var(--accent-2);
  color: #123;
  box-shadow: 0 2px 6px rgba(63,210,139,0.15);
}
.small {
  font-size: .85rem;
  color: var(--muted);
  margin-top: .25rem;
}
.badge {
  display: inline-block;
  background: #eef2ff;
  color: #2b3a9c;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: .8rem;
  border: 1px solid #e0e5ff;
}
hr.sep {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 1rem 0;
}
</style>"""

        def app(environ, start_response):
            if abort_signal.triggered:
                start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
                return [b"aborted"]

            path = environ.get("PATH_INFO", "/")
            method = environ.get("REQUEST_METHOD", "GET")
            query = environ.get("QUERY_STRING", "")

            if path == "/" and method == "GET":
                qs = parse_qs(query)
                if qs.get("t", [""])[0] != token:
                    start_response("403 Forbidden", [("Content-Type", "text/plain")])
                    return [b"forbidden"]

                functions_html = fns_html
                function_configs_html = fn_cfg_html

                body = f"""<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title>
{css}
<div class="container">
  <div class="header">
    <h2>{title}</h2>
    <p>Review the analysis request details below and choose whether to participate.</p>
  </div>
  <div class="content">

    <div class="section">
      <h3>Overview</h3>
      <p class="small">
        <span class="badge">Consent Version: {self.consent_version}</span>
      </p>
    </div>

    <div class="section">
      <h3>Selected Functions</h3>
      {functions_html}
    </div>

    <div class="section">
      <h3>Function Configs</h3>
      {function_configs_html}
    </div>

    <div class="section">
      <h3>Raw Filters Payload</h3>
      <p class="small">For traceability and reproducibility, the raw <code>filters.json</code> is shown below.</p>
      <pre class="json">{filt_str}</pre>
    </div>

  </div>
  <div class="footer">
    <form method="POST" action="/decide?t={token}">
      <button name="d" value="reject" type="submit" class="secondary">Reject</button>
      <button name="d" value="accept" type="submit">Accept</button>
    </form>
  </div>
</div>""".encode("utf-8")
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")])
                return [body]

            if path == "/decide" and method == "POST":
                qs = parse_qs(query)
                if qs.get("t", [""])[0] != token:
                    start_response("403 Forbidden", [("Content-Type", "text/plain")])
                    return [b"forbidden"]
                try:
                    size = int(environ.get("CONTENT_LENGTH", "0") or "0")
                except Exception:
                    size = 0
                data = environ["wsgi.input"].read(size).decode("utf-8", "ignore")
                d = parse_qs(data).get("d", [""])[0]
                decision["val"] = True if d == "accept" else False
                print(f"[Exec] _serve_local_confirm: user_decision={decision['val']}", flush=True)
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
                done.set()
                return [b"<h3>Thanks. You can close this window.</h3>"]

            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found"]

        httpd = make_server("127.0.0.1", port, app, server_class=WSGIServer, handler_class=WSGIRequestHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            url = f"http://127.0.0.1:{port}/?t={token}"
            print(f"[Exec] _serve_local_confirm: open URL {url}", flush=True)
            try:
                webbrowser.open(url, new=1, autoraise=True)
            except Exception as e:
                print(f"[Exec] _serve_local_confirm: browser open failed: {e}", flush=True)
            deadline = time.time() + timeout_sec
            while time.time() < deadline and not abort_signal.triggered:
                if done.wait(timeout=0.25):
                    break
            if not done.is_set():
                print("[Exec] _serve_local_confirm: timeout waiting for user", flush=True)
                decision["val"] = None
            return decision["val"]
        finally:
            try:
                httpd.shutdown()
            except Exception:
                pass
            print("[Exec] _serve_local_confirm: server stopped", flush=True)

    def execute(self, task_name: str, shareable: Shareable, fl_ctx: FLContext, abort_signal) -> Shareable:
        print(f"[Exec] execute: task_name={task_name}", flush=True)

        try:
            site = fl_ctx.get_prop("site_name", None)
            job_id = fl_ctx.get_prop("job_id", None)
            app_root = fl_ctx.get_prop("app_root", None)
            pp = shareable.get_peer_props() or {}
            print(
                "[Exec] execute: "
                f"site_name={site} job_id={job_id} app_root={app_root} "
                f"peer_identity={pp.get('__identity_name__')} fqsn={pp.get('__fqsn__')} "
                f"props_keys={list(pp.keys())}",
                flush=True,
            )
        except Exception as e:
            print(f"[Exec] execute: failed to read fl_ctx/peer_props: {e}", flush=True)

        if abort_signal.triggered:
            print("[Exec] execute: abort_signal triggered -> returning aborted shareable", flush=True)
            return self._share({"dummy_weight": 0.0}, 0.0, 0.0, {"aborted": True, "task_name": task_name})

        pf = self._preflight_or_reject()
        if pf is not None:
            print(f"[Exec] execute: preflight reject -> reason={pf}", flush=True)
            return self._share(
                {"dummy_weight": 0.0},
                0.0,
                0.0,
                {"task_name": task_name, "confirmation": "rejected", "reason": pf},
            )

        resolved, bases = self._resolve_filters_path(fl_ctx)
        filters_data: Dict[str, Any] = {}
        if resolved and resolved.exists():
            try:
                txt = Path(resolved).read_text(encoding="utf-8", errors="ignore")
                filters_data = json.loads(txt)
                preview = txt[:300].replace("\n", " ")
                print(
                    f"[Exec] execute: loaded filters from {resolved} "
                    f"(len={len(txt)} preview={preview!r})",
                    flush=True,
                )
            except Exception as e:
                print(f"[Exec] execute: failed to load filters from {resolved}: {e}", flush=True)
                filters_data = {}
        else:
            print("[Exec] execute: no filters.json found", flush=True)
            print(f"[Exec] execute: searched bases={bases}", flush=True)

        filters_hash = self._hash_filters(filters_data)

        filter_props: Dict[str, Any] = {}
        for key in ["filter_id", "name", "conditions", "threshold_config"]:
            if key in filters_data:
                filter_props[key] = filters_data[key]

        print(f"[Exec] execute: filter_props keys={list(filter_props.keys())}", flush=True)

        def make_meta(base: Dict[str, Any]) -> Dict[str, Any]:
            return {
                **base,
                **filter_props,
                "filters_hash": filters_hash,
                "consent_version": self.consent_version,
            }

        if self.consent_mode == "service":
            print("[Exec] execute: service mode -> AUTO ACCEPT", flush=True)
            return self._share(
                {"dummy_weight": 1.0},
                1.0,
                1.0,
                make_meta({"task_name": task_name, "confirmation": "ACCEPT"}),
            )

        consent_text = "An analysis is being run on this device with the filters shown below. Do you consent to participate?"
        ans = self._serve_local_confirm(self.dialog_title, consent_text, filters_data, self.confirm_timeout_sec, abort_signal)
        print(f"[Exec] execute: user answer -> {ans}", flush=True)

        if ans is True:
            return self._share(
                {"dummy_weight": 1.0},
                1.0,
                1.0,
                make_meta({"task_name": task_name, "confirmation": "ACCEPT"}),
            )

        if ans is False:
            return self._share(
                {"dummy_weight": 0.0},
                0.0,
                0.0,
                make_meta({"task_name": task_name, "confirmation": "REJECT"}),
            )

        print(f"[Exec] execute: no response -> headless_default={self.headless_default}", flush=True)
        return self._share(
            {"dummy_weight": 0.0},
            0.0,
            0.0,
            make_meta({"task_name": task_name, "confirmation": self.headless_default}),
        )
