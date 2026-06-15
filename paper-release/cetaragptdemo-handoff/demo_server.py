"""CetaraGPT chatbot demo - Flask server.

Serves demo.html and exposes the agentic-RAG rung via a small async-ish API
so the front-end can show tool calls glowing in real time:

    GET  /                       -> demo.html
    GET  /api/tools              -> static catalog of the 5 agentic tools
    POST /api/chat_start         -> kicks off a job, returns {job_id}
    GET  /api/chat_status?job_id -> live snapshot: {tool_calls, done, response, ...}
    POST /api/chat               -> legacy synchronous endpoint (kept for back-compat)

Run from the project root:
    python demo_server.py
Then open http://localhost:5000/
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

# Force UTF-8 stdout so Windows cp1252 doesn't choke on superscript-minus
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address

# Make `cetara/` importable when run from the project root
if "." not in sys.path:
    sys.path.insert(0, ".")

from cetara import rungs, tools as tools_mod

# Config
NB_PATH = Path("01_run_experiments.ipynb")
DB_PATH = "pfas_membrane.db"
MODEL   = "gemini-3.1-flash-lite"

JOB_TTL_SECONDS = 600     # purge finished jobs after 10 min
POLL_INTERVAL    = 0.20   # how often the background thread copies CALL_LOG

def _extract_api_key() -> str:
    """Read GEMINI_API_KEY from the experiment notebook."""
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))
    for c in nb["cells"]:
        src = "".join(c.get("source", []))
        m = re.search(r'GEMINI_API_KEY\s*=\s*"(AIzaSy[^"]+)"', src)
        if m:
            return m.group(1)
    raise RuntimeError(
        f"GEMINI_API_KEY not found in {NB_PATH}. Set it in the notebook "
        f"or in the GOOGLE_API_KEY env var."
    )

API_KEY = os.environ.get("GOOGLE_API_KEY") or _extract_api_key()
os.environ["GOOGLE_API_KEY"] = API_KEY
tools_mod.set_db_path(DB_PATH)

# Tool surface - uses ALL_TOOLS_DEMO so the chip strip in the UI matches
# the actual tool kit the demo agent (run_agentic_demo) has, including
# the sandboxed `run_sql` escape hatch.  Paper-benchmark code (run_agentic)
# stays on the smaller ALL_TOOLS kit; that's why this is _DEMO.
def _tool_catalog() -> list[dict[str, Any]]:
    out = []
    for t in tools_mod.ALL_TOOLS_DEMO:
        try:
            args = list(t.args.keys()) if hasattr(t, "args") else []
        except Exception:
            args = []
        name = getattr(t, "name", None) or repr(t)
        desc = (getattr(t, "description", "") or "").strip()
        out.append({"name": name, "description": desc, "args": args})
    return out

# Job tracking (single-user demo)
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_RUN_LOCK  = threading.Lock()   # serialize agent runs since CALL_LOG is global

def _purge_old_jobs() -> None:
    now = time.time()
    with _JOBS_LOCK:
        stale = [jid for jid, j in _JOBS.items()
                 if j.get("done") and now - j.get("finished_at", now) > JOB_TTL_SECONDS]
        for jid in stale:
            del _JOBS[jid]

# Format the demo accepts for a user-supplied Gemini API key.
# Google keys are typically 39 chars total (6-char "AIzaSy" prefix + 33 base).
# We accept a generous range to tolerate length changes without lockout.
BYOK_RE = re.compile(r"^AIzaSy[A-Za-z0-9_-]{30,40}$")

_JSON_BLOCK_RE_AT_END = re.compile(
    r"\s*```(?:json)?\s*(\{[\s\S]*?\})\s*```\s*$", re.IGNORECASE
)
_BARE_JSON_AT_END_RE = re.compile(
    r"\n\s*(\{[^{}]*\"(?:rejection_range_pct|recommended_membrane|"
    r"citations_doi|refused)\"[\s\S]*?\})\s*$",
)

# Friendly error mapping. Gemini returns raw API exception strings which
# leak into the UI; translate the most common categories into something
# a non-technical user can act on.
def _humanize_error(raw: str | None) -> str | None:
    if not raw:
        return raw
    msg = str(raw)
    low = msg.lower()
    # Rate / quota
    if any(t in low for t in (
        "429", "resourceexhausted", "resource_exhausted",
        "quota", "rate limit", "rate-limit", "too many requests",
    )):
        return ("This demo's Gemini API key just hit its rate limit. "
                "The free tier is ~15 requests/minute. "
                "Please wait a minute and try again.")
    # Auth
    if any(t in low for t in (
        "permissiondenied", "permission_denied",
        "unauthenticated", "401", "403",
        "invalid api key", "api key not valid",
    )):
        return ("The Gemini API key is invalid or revoked. "
                "If you're hosting this demo, rotate the key in /etc/cetaragpt.env "
                "and restart the service.")
    # Timeout / network
    if any(t in low for t in (
        "deadline_exceeded", "deadlineexceeded", "timed out", "timeout",
    )):
        return "The model didn't respond in time. Try a shorter or simpler question."
    # Model availability
    if any(t in low for t in ("not found", "404", "model not found")):
        return ("The configured Gemini model isn't reachable. The demo owner "
                "may need to update the MODEL constant in demo_server.py.")
    # Server-side
    if any(t in low for t in ("500", "internal", "unavailable", "503")):
        return ("The Gemini API returned a temporary server error. "
                "Please try again in a few seconds.")
    # Fallback: trim to keep the UI tidy
    if len(msg) > 220:
        msg = msg[:200].rstrip() + "…"
    return f"Something went wrong: {msg}"

def _normalize_dois(citations: list) -> list[str]:
    """Strip https://doi.org/ prefixes and de-dupe (case-insensitive)."""
    seen: set[str] = set()
    out: list[str] = []
    for d in citations or []:
        d_norm = re.sub(r"^https?://(?:dx\.)?doi\.org/", "",
                        str(d).strip(), flags=re.IGNORECASE)
        if d_norm and d_norm.lower() not in seen:
            seen.add(d_norm.lower())
            out.append(d_norm)
    return out

def _parse_trailing_json(text: str) -> tuple[dict | None, str]:
    """Return (parsed_json_dict_or_None, text_with_json_stripped)."""
    if not text:
        return None, ""
    cleaned = text
    obj: dict | None = None
    m = _JSON_BLOCK_RE_AT_END.search(cleaned)
    if m:
        try:
            o = json.loads(m.group(1))
            if isinstance(o, dict):
                obj = o
        except (json.JSONDecodeError, TypeError):
            pass
        cleaned = cleaned[: m.start()].rstrip()
    else:
        m2 = _BARE_JSON_AT_END_RE.search(cleaned)
        if m2:
            try:
                o = json.loads(m2.group(1))
                if isinstance(o, dict):
                    obj = o
            except (json.JSONDecodeError, TypeError):
                pass
            cleaned = cleaned[: m2.start()].rstrip()
    return obj, cleaned

def _synthesize_empty_fallback(obj: dict | None,
                               tool_calls: list,
                               citations: list[str]) -> str:
    """When the agent's prose is empty, build a helpful response from the
    JSON fields (if any) and the observed tool-call trace. Never leave the
    user staring at '(no response)'.
    """
    parts: list[str] = []

    # 1. Use the structured JSON fields if the model emitted them
    if isinstance(obj, dict):
        if obj.get("refused") is True:
            parts.append(
                "This query falls outside the scope of the curated dataset, "
                "so the agent declined to answer rather than fabricate."
            )
        else:
            facts = []
            rec = obj.get("recommended_membrane")
            if isinstance(rec, str) and rec.strip():
                facts.append(f"Recommended membrane: **{rec.strip()}**.")
            rng = obj.get("rejection_range_pct")
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                try:
                    lo, hi = float(rng[0]), float(rng[1])
                    facts.append(f"Reported rejection range: **{lo:g}% to {hi:g}%**.")
                except (TypeError, ValueError):
                    pass
            if facts:
                parts.append(" ".join(facts))

    # 2. If still nothing, narrate what the agent did
    if not parts:
        if tool_calls:
            tools_used = list({c.get("tool", "?") for c in tool_calls})
            n = len(tool_calls)
            parts.append(
                f"*The agent inspected the dataset but didn't synthesize a final "
                f"text answer for this question. It made {n} tool call"
                f"{'s' if n != 1 else ''} "
                f"({', '.join(sorted(tools_used))}) - see the trace below.*\n\n"
                f"*This usually means the question requires an aggregation the "
                f"current tools don't expose directly. Try rephrasing toward a "
                f"specific membrane or PFAS species.*"
            )
        else:
            parts.append(
                "*The agent didn't produce a response. Try rephrasing your "
                "question or asking about a specific PFAS / membrane pair.*"
            )

    # 3. Append sources if any
    if citations:
        parts.append("**Sources:**\n" + "\n".join(f"- {d}" for d in citations))

    return "\n\n".join(parts)

def _extract_and_strip(text: str, tool_calls: list | None = None) -> str:
    """Build the user-visible response text from a raw agent output.

    1. Pull citations from the trailing ```json block (per the rung system
       prompt) and append them as a Markdown **Sources:** list.
    2. Strip the JSON block from the prose.
    3. If the prose is now empty (model emitted only JSON, or only a
       thinking block with no text part), synthesize a helpful fallback
       from the JSON fields and the tool-call trace.
    """
    tool_calls = tool_calls or []
    obj, cleaned = _parse_trailing_json(text or "")
    citations = _normalize_dois((obj or {}).get("citations_doi") or [])

    if not cleaned.strip():
        return _synthesize_empty_fallback(obj, tool_calls, citations)

    if citations:
        cleaned = cleaned.rstrip() + "\n\n**Sources:**\n" + "\n".join(
            f"- {d}" for d in citations
        )
    return cleaned

# Backwards-compat alias (legacy code paths that didn't pass tool_calls)
_strip_json_block = _extract_and_strip

def _redact_key(s: str) -> str:
    """Make sure no API key ever appears in an error string we send back."""
    if not s:
        return s
    return re.sub(r"AIzaSy[A-Za-z0-9_-]{20,}", "AIzaSy***REDACTED***", s)

def _run_agent_job(job_id: str, query: str, rung: str,
                   api_key_override: str | None = None) -> None:
    """Background worker: runs the selected rung and stuffs its result into
    the per-job dict.

    - rung="agentic": uses tools_mod.CALL_LOG so the client can poll tool
      calls as they happen. Serialised via _RUN_LOCK because CALL_LOG is
      module-global.
    - rung="vanilla": no tools, no CALL_LOG, no lock - runs free.

    If `api_key_override` is supplied (user BYOK), use it instead of the
    server's API_KEY for this single request. The key only lives in this
    function's local scope; it is NEVER stored in the job dict.
    """
    effective_key = api_key_override or API_KEY
    try:
        if rung == "vanilla":
            result = rungs.run_vanilla(
                query, model_name=MODEL, api_key=effective_key,
            )
        else:  # "agentic" (default)
            # Use the demo variant - same agent, plus a sandboxed read-only
            # `run_sql` escape hatch for aggregation questions the typed
            # tools can't express. Paper benchmark uses run_agentic, not this.
            with _RUN_LOCK:
                tools_mod.reset_call_log()
                result = rungs.run_agentic_demo(
                    query, model_name=MODEL, api_key=effective_key, db_path=DB_PATH,
                )
        with _JOBS_LOCK:
            _JOBS[job_id].update({
                "response_raw":  result.response_text,
                "response":      _extract_and_strip(
                                    result.response_text or "",
                                    tool_calls=result.tool_calls,
                                 ),
                "tool_calls":    result.tool_calls,
                "n_llm_calls":   result.n_llm_calls,
                "error":         _humanize_error(_redact_key(result.error or "")) or None,
                "done":          True,
                "finished_at":   time.time(),
            })
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[job_id].update({
                "error":       _humanize_error(_redact_key(str(e))),
                "done":        True,
                "finished_at": time.time(),
            })
    finally:
        # Defensive: scrub the local reference even though Python will GC it
        effective_key = None
        del effective_key

# Flask app
# Note: static_url_path="" would catch /api/* and shadow our POST routes,
# so we disable Flask's static handler and explicitly route demo.html below.
app = Flask(__name__, static_folder=None)

# Per-IP rate limiting.
#
# The Gemini free tier is ~15 requests/minute and each compare-mode query
# triggers ~5-8 API calls (vanilla=1 + agentic=3-7), so a single user can
# easily exhaust the budget. We cap each IP at 3 queries/minute / 20/hour /
# 50/day, plus a global ceiling of 10/minute to stay under the Gemini cap.
#
# When BYOK ships, requests carrying a valid user-supplied key should
# bypass these limits via @limiter.exempt_when(...).
def _client_ip() -> str:
    """Prefer the X-Forwarded-For first hop when running behind Nginx,
    fall back to the direct remote address otherwise."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address()

def _byok_present() -> bool:
    """Truthy when the incoming POST carries a valid-looking user key.
    Used by flask-limiter.exempt_when so BYOK requests skip the per-IP cap.
    """
    try:
        if request.method != "POST":
            return False
        data = request.get_json(silent=True) or {}
        key = (data.get("api_key") or "").strip()
        return bool(BYOK_RE.match(key))
    except Exception:
        return False

# Note: each compare-mode question becomes TWO /api/chat_start calls (one
# per rung), so a per-IP cap of "6/minute" feels to the user like "3 queries
# per minute". We size the headline limits in HTTP-request units accordingly.
limiter = Limiter(
    app=app,
    key_func=_client_ip,
    default_limits=["20 per minute"],          # global cap (sums all IPs)
    storage_uri="memory://",
    strategy="fixed-window",
    headers_enabled=True,
)

@app.errorhandler(RateLimitExceeded)
def _ratelimit_handler(err):
    """Return a JSON shape the front-end already knows how to render."""
    # err.description is a string like "3 per 1 minute"
    return jsonify({
        "error": "rate_limited",
        "message": ("This demo is rate-limited to keep its Gemini key alive. "
                    "Please wait a moment and try again."),
        "limit":   str(err.description),
    }), 429

# CORS - allow the demo UI to be hosted on a different origin (e.g. the
# static page at https://data-here.com/gptdemo.html) while this backend
# stays on https://cetara.jinyue-jiang.com. Only an explicit allow-list of
# origins is honored; everything else gets no CORS headers (same-origin
# use is unaffected). Manual implementation to avoid adding flask-cors.
_ALLOWED_ORIGINS = {
    "https://data-here.com",
    "https://www.data-here.com",
    "https://cetara.jinyue-jiang.com",
}

def _apply_cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"]  = origin
        resp.headers["Vary"]                         = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"]       = "86400"
    return resp

@app.before_request
def _cors_preflight():
    """Short-circuit CORS preflight (OPTIONS) before route dispatch / limiter."""
    if request.method == "OPTIONS":
        return _apply_cors(app.make_default_options_response())

@app.after_request
def _cors_after(resp):
    return _apply_cors(resp)

@app.route("/")
def index():
    return send_from_directory(".", "demo.html")

@app.route("/api/tools")
@limiter.exempt
def api_tools():
    return jsonify({"tools": _tool_catalog()})

@app.route("/api/chat_start", methods=["POST"])
@limiter.limit("6 per minute; 40 per hour; 100 per day",
                exempt_when=_byok_present)
def api_chat_start():
    data = request.get_json(silent=True) or {}
    query   = (data.get("message")  or "").strip()
    rung    = (data.get("rung")     or "agentic").strip().lower()
    user_key = (data.get("api_key") or "").strip()
    if rung not in ("agentic", "vanilla"):
        return jsonify({"error": f"Unknown rung: {rung!r}"}), 400
    if not query:
        return jsonify({"error": "Empty message"}), 400

    # BYOK: validate format strictly. If a key is supplied but malformed,
    # tell the user; don't silently fall back to the demo key.
    api_key_override: str | None = None
    if user_key:
        if not BYOK_RE.match(user_key):
            return jsonify({
                "error": "invalid_api_key",
                "message": "That doesn't look like a Google AI Studio key. "
                           "It should start with 'AIzaSy' and be ~39 characters."
            }), 400
        api_key_override = user_key

    _purge_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        # api_key_override stays out of the job dict on purpose; it only
        # lives as an argument to the background thread.
        _JOBS[job_id] = {
            "query":       query,
            "rung":        rung,
            "byok":        bool(api_key_override),
            "started_at":  time.time(),
            "done":        False,
            "response":    None,
            "tool_calls":  [],
            "n_llm_calls": 0,
            "error":       None,
        }
    threading.Thread(
        target=_run_agent_job,
        args=(job_id, query, rung, api_key_override),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id, "rung": rung, "byok": bool(api_key_override)})

@app.route("/api/chat_status")
@limiter.exempt    # polled many times per query; the heavy work is gated on chat_start
def api_chat_status():
    job_id = request.args.get("job_id", "")
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        snap = deepcopy(job) if job else None
    if snap is None:
        return jsonify({"error": "Unknown job_id"}), 404

    # While the job is running, the live tool-call list is the global CALL_LOG.
    # Vanilla runs never touch CALL_LOG, so leave tool_calls empty for them.
    # Once `done`, the worker has captured the final list in the job dict.
    if not snap["done"] and snap.get("rung") == "agentic":
        snap["tool_calls"] = list(tools_mod.get_call_log())
    snap.pop("response_raw", None)   # never leak the un-stripped text
    return jsonify(snap)

# ---------- Legacy synchronous endpoint (kept for back-compat) ----------
@app.route("/api/chat", methods=["POST"])
@limiter.limit("6 per minute; 40 per hour; 100 per day",
                exempt_when=_byok_present)
def api_chat():
    data = request.get_json(silent=True) or {}
    query = (data.get("message") or "").strip()
    if not query:
        return jsonify({"error": "Empty message"}), 400
    with _RUN_LOCK:
        try:
            result = rungs.run_agentic_demo(
                query, model_name=MODEL, api_key=API_KEY, db_path=DB_PATH,
            )
        except Exception as e:
            return jsonify({"error": f"agent_failed: {e}"}), 500
    return jsonify({
        "response":    _strip_json_block(result.response_text or ""),
        "tool_calls":  result.tool_calls,
        "n_llm_calls": result.n_llm_calls,
        "error":       result.error,
    })

if __name__ == "__main__":
    print("=" * 60)
    print("  CetaraGPT chatbot demo")
    print(f"  Model:    {MODEL}")
    print(f"  DB:       {DB_PATH}")
    print(f"  Tools:    {', '.join(t['name'] for t in _tool_catalog())}")
    print(f"  Open:     http://localhost:5000/")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
