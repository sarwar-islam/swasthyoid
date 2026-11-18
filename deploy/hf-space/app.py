"""SwasthyoID demo backend on a Hugging Face Gradio Space. SYNTHETIC DATA ONLY, never real patients.

`python app.py` (what the Space runs):
1. PostgreSQL in /tmp (packages.txt installs it), unless DATABASE_URL is a Space secret.
2. The synthetic seed (devtools/seed.py), which also applies the schema.
3. The workers as child processes, restarted after a failure (not after exit 2, a configuration error): extract with
   PaddleOCR (English, test mode: adapter contract version 0 is test-only, D18), safety, deliver (in-app).
4. The FastAPI app on port 7860, with a small Gradio status page at /ui. The web app (Vercel) proxies /api here.

The PaddleOCR weights are downloaded on first start (paddleocr_prepare.py) and pinned by their SHA-256 manifest in an
approved list built from exactly those files. Sign-in codes go to the Space log (no SMS gateway until S2). Without
DATABASE_URL every restart starts from an empty database with fresh throwaway keys.

Local smoke run: set DATABASE_URL (an empty database), SPACE_DATA (a writable folder) and PADDLEOCR_PYTHON (an interpreter
with paddleocr), then `python deploy/hf-space/app.py` from the repository root.
"""
try:  # ZeroGPU hardware expects the spaces package and at least one GPU function; OCR here runs on the CPU
    import spaces

    @spaces.GPU
    def _gpu_unused():
        return None
except ImportError:
    pass

import glob
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import threading
import time

from starlette.requests import Request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE if (HERE / "swasthyoid").is_dir() else HERE.parents[1]  # the Space root, or the repository when run locally
DATA = pathlib.Path(os.environ.get("SPACE_DATA", "/tmp/swasthyoid"))
MODELS = DATA / "models" / "paddleocr-en"
APPROVED = DATA / "models" / "approved.json"
PADDLE_PYTHON = os.environ.get("PADDLEOCR_PYTHON", sys.executable)
sys.path.insert(0, str(ROOT))


def say(text):
    print(f"space: {text}", flush=True)


def keys():
    if os.environ.get("DATABASE_URL") and not os.environ.get("PII_KEY"):
        sys.exit("space: DATABASE_URL is set, so PII_KEY, DOCUMENT_KEY, EXTRACTION_KEY, HMAC_KEY and JWT_SECRET must be secrets")
    from cryptography.fernet import Fernet
    for name in ("PII_KEY", "DOCUMENT_KEY", "EXTRACTION_KEY"):
        os.environ.setdefault(name, Fernet.generate_key().decode())
    for name in ("HMAC_KEY", "JWT_SECRET"):
        os.environ.setdefault(name, secrets.token_hex(32))
    os.environ.setdefault("DOCUMENT_STORE", str(DATA / "documents"))
    pathlib.Path(os.environ["DOCUMENT_STORE"]).mkdir(parents=True, exist_ok=True)


def postgres():
    if os.environ.get("DATABASE_URL"):
        return
    bin_dir = sorted(glob.glob("/usr/lib/postgresql/*/bin"))[-1]
    pgdata = DATA / "pg"
    # PostgreSQL refuses to run as root, and Spaces may run this as root: then use the package's postgres user
    as_pg = ["runuser", "-u", "postgres", "--"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
    if not pgdata.exists():
        pgdata.mkdir(parents=True)
        if as_pg:
            shutil.chown(pgdata, "postgres", "postgres")
        subprocess.run([*as_pg, f"{bin_dir}/initdb", "-D", str(pgdata), "-U", "swasthyoid", "--auth=trust"], check=True,
                       stdout=subprocess.DEVNULL)
    subprocess.run([*as_pg, f"{bin_dir}/pg_ctl", "-D", str(pgdata), "-o", "-c listen_addresses=127.0.0.1 -k /tmp",
                    "-l", str(pgdata / "server.log"), "start"], check=True, stdout=subprocess.DEVNULL)
    while subprocess.run([f"{bin_dir}/pg_isready", "-h", "127.0.0.1", "-q"]).returncode:
        time.sleep(0.5)
    subprocess.run([f"{bin_dir}/createdb", "-h", "127.0.0.1", "-U", "swasthyoid", "swasthyoid"],
                   stderr=subprocess.DEVNULL)  # already there after a soft restart
    os.environ["DATABASE_URL"] = "postgresql://swasthyoid@127.0.0.1:5432/swasthyoid"


def run(*args, **extra):
    return subprocess.run([sys.executable, *args], cwd=ROOT, env={**os.environ, **extra})


def prepare_models():
    """Download the weights once and build the approved list from exactly those files."""
    if not (MODELS / "recognizer").is_dir():
        MODELS.mkdir(parents=True, exist_ok=True)
        with open(DATA / "models" / "prepared.json", "w", encoding="utf-8") as out:
            subprocess.run([PADDLE_PYTHON, "-I", str(ROOT / "swasthyoid/capture/adapters/paddleocr_prepare.py"),
                            "--out", str(MODELS)], stdout=out, check=True)
    with open(APPROVED, "w", encoding="utf-8") as out:
        subprocess.run([sys.executable, "-m", "swasthyoid.capture.adapters.paddleocr_adapter", "--root", str(MODELS),
                        "--recognizer", str(MODELS / "recognizer"), "--detector", str(MODELS / "detector")],
                       cwd=ROOT, stdout=out, check=True)


def keep(name, module, **extra):
    """Run a worker, restart it after a failure; a configuration error (exit 2) fails the same way every time."""
    def loop():
        while True:
            code = run("-m", module, **extra).returncode
            if code == 2:
                say(f"{name} stopped: configuration error (exit 2)")
                return
            say(f"{name} exited {code}; restarting in 5 s")
            time.sleep(5)
    threading.Thread(target=loop, name=name, daemon=True).start()


def extract_worker():
    try:
        prepare_models()
    except Exception as e:  # fail closed: no OCR, documents go to manual entry
        say(f"OCR models unavailable ({type(e).__name__}); extraction stays off")
        return
    keep("extract", "swasthyoid.workers.extract", APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM="1",
         EXTRACTION_POLL_SECONDS="5", OCR_ADAPTER="swasthyoid.capture.adapters.paddleocr_adapter:paddleocr_en",
         OCR_ADAPTERS_APPROVED=str(APPROVED), PADDLEOCR_PYTHON=PADDLE_PYTHON,
         PADDLEOCR_MODEL_DIR=str(MODELS / "recognizer"), PADDLEOCR_DETECTOR_DIR=str(MODELS / "detector"),
         PADDLEOCR_MODEL_REVISION="space-download", PADDLEOCR_DETECTOR_REVISION="space-download")


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    keys()
    postgres()
    # the API process: development mode writes sign-in codes to this log (demo only; no SMS gateway)
    os.environ.update(APP_ENV="development", DEV_LOG_CODES="1")
    os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "300")
    if run("-m", "swasthyoid.devtools.seed").returncode:
        say("seed skipped (the database is not empty)")
    keep("safety", "swasthyoid.workers.safety", SAFETY_POLL_SECONDS="10")
    keep("deliver", "swasthyoid.workers.deliver", NOTIFY_POLL_SECONDS="5", NOTIFY_CHANNEL="in_app")
    threading.Thread(target=extract_worker, name="extract-setup", daemon=True).start()

    import uvicorn
    from swasthyoid.api.main import app
    try:
        import gradio as gr
    except ImportError:  # local smoke run: the API serves the port itself
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")), proxy_headers=True,
                    forwarded_allow_ips="*")
        return
    # On the Space, Gradio's own launch() must own port 7860 (ZeroGPU requires it). The API runs inside on INNER_PORT and
    # Gradio's server forwards /api and /health to it unchanged, cookies and client address included.
    threading.Thread(target=uvicorn.run, args=(app,), daemon=True,
                     kwargs={"host": "127.0.0.1", "port": INNER_PORT, "proxy_headers": True}).start()
    with gr.Blocks(title="SwasthyoID demo API") as ui:
        gr.Markdown("## SwasthyoID demo API\nSynthetic data only, not for real patients. The web app calls `/api/v1`; "
                    "health: `/health`. Sign-in codes are in this Space's logs.")
    ui.launch(server_name="0.0.0.0", server_port=7860, prevent_thread_lock=True, ssr_mode=False)  # SSR would route every path to Gradio
    server = getattr(ui, "app", None) or ui.server_app
    for path in ("/api/{rest:path}", "/health"):
        server.add_api_route(path, forward, methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
        server.router.routes.insert(0, server.router.routes.pop())  # ahead of Gradio's own routes
    ui.block_thread()


INNER_PORT = 7870  # Gradio uses 7861 itself on ZeroGPU
_HOP = {"host", "content-length", "connection", "transfer-encoding", "content-encoding", "keep-alive"}


async def forward(request: "Request"):
    """Pass one request to the API on INNER_PORT and its answer back, unchanged (the API does every check itself)."""
    import httpx
    from starlette.responses import Response
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _HOP and k.lower() != "x-forwarded-for"]
    client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    headers.append(("x-forwarded-for", client))
    async with httpx.AsyncClient(timeout=120) as http:
        got = await http.request(request.method, f"http://127.0.0.1:{INNER_PORT}{request.url.path}",
                                 params=request.url.query, headers=headers, content=await request.body())
    out = Response(content=got.content, status_code=got.status_code)
    for k, v in got.headers.multi_items():  # several Set-Cookie headers stay several
        if k.lower() not in _HOP:
            out.headers.append(k, v)
    return out


if __name__ == "__main__":
    main()
