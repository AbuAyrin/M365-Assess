"""
M365-Assess Consultant GUI - backend.

A thin Flask layer over the real engine: everything here does is (a) show a
form instead of a PowerShell prompt, (b) spawn Run-Assessment.ps1 (which
calls the real Invoke-M365Assessment - no logic is reimplemented here), and
(c) poll its structured log file for progress instead of parsing console
text.

Known risk, not yet resolved: launching -UseDeviceCode through a spawned
subprocess (as this does) is exactly the scenario that produced "error
occurred when writing to a listener" during the M365-Assessment-Toolkit
work in this same project - a different tool, but the same underlying
"PowerShell device-code flow needs a console the spawning process didn't
give it" class of problem. App-registration auth doesn't touch that code
path at all (no interactive/device console involved), so it's the
recommended auth method through this GUI until device code is confirmed
working here specifically.
"""
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import subprocess, threading, json, os, re, uuid, shutil, datetime, glob

app = Flask(__name__)
CORS(app)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR      = os.path.join(BASE_DIR, "runs")
BRANDING_PATH = os.path.join(BASE_DIR, "branding.json")
WRAPPER_PATH  = os.path.join(BASE_DIR, "Run-Assessment.ps1")
os.makedirs(RUNS_DIR, exist_ok=True)

DEFAULT_SECTIONS = ["Tenant", "Identity", "Licensing", "Email", "Intune",
                     "Security", "Collaboration", "PowerBI", "Hybrid"]
OPTIONAL_SECTIONS = ["Inventory", "ActiveDirectory", "SOC2", "ValueOpportunity"]

DEFAULT_BRANDING = {
    "CompanyName": "Your Company Name",
    "LogoPath": "",
    "AccentColor": "#2563eb",
    "PrimaryColor": "",
    "Disclaimer": "",
}


def load_branding():
    try:
        with open(BRANDING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT_BRANDING, **data}
    except Exception:
        return dict(DEFAULT_BRANDING)


# ── In-memory run state (single-user local tool - one run at a time,
#    same simplifying assumption the other M365 tool in this project
#    makes for the same reason: this runs on the consultant's own
#    machine for their own use, not a shared multi-tenant service) ──
_runs = {}
_runs_lock = threading.Lock()

LOG_LINE_RE = re.compile(
    r"^\[(?P<ts>[\d\-: .]+)\]\s*\[(?P<level>\w+)\]\s*(?:\[(?P<section>[^\]]+)\])?\s*(?:\[(?P<collector>[^\]]+)\])?\s*(?P<msg>.*)$"
)


def _run_assessment(run_id, params):
    """Background thread: spawn the PowerShell wrapper, stream its stdout
    into the run's state, and once it's finished, resolve the output
    folder (from the GUI_BRIDGE: RESULT_FOLDER= marker Run-Assessment.ps1
    prints) and locate the report/log files inside it."""
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Fail fast with a plain-language message instead of a cryptic
    # "file not found" from Popen: this is the actual root cause seen in
    # testing - the tool needs PowerShell 7 ("pwsh"), and a machine that
    # only has the older Windows PowerShell ("powershell.exe") fails the
    # exact same way no matter which auth method is picked, because the
    # failure happens before auth is even reached.
    if shutil.which("pwsh") is None:
        with _runs_lock:
            _runs[run_id]["status"] = "error"
            _runs[run_id]["error"] = (
                "PowerShell 7 is not installed on this computer. This tool needs it - "
                "the 'Windows PowerShell' that already comes with Windows is not enough. "
                "Close this window, open Windows PowerShell, and run: "
                "winget install Microsoft.PowerShell "
                "Then restart the console and try again."
            )
        return

    cmd = [
        "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", WRAPPER_PATH,
        "-OutputFolder", run_dir,
        "-AuthMethod", params["authMethod"],
        "-ReportTheme", params.get("reportTheme", "Neon"),
    ]
    if params.get("tenantId"):
        cmd += ["-TenantId", params["tenantId"]]
    if params.get("connectionProfile"):
        cmd += ["-ProfileName", params["connectionProfile"]]
    if params.get("clientId"):
        cmd += ["-ClientId", params["clientId"]]
    if params.get("certificateThumbprint"):
        cmd += ["-CertificateThumbprint", params["certificateThumbprint"]]
    if params.get("userPrincipalName"):
        cmd += ["-UserPrincipalName", params["userPrincipalName"]]
    if params.get("sections"):
        cmd += ["-Section"] + params["sections"]
    if params.get("whiteLabel"):
        cmd += ["-WhiteLabel"]
    if os.path.exists(BRANDING_PATH):
        cmd += ["-BrandingJsonPath", BRANDING_PATH]

    with _runs_lock:
        _runs[run_id].update({"status": "running", "cmd": " ".join(cmd)})

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        with _runs_lock:
            _runs[run_id]["pid"] = proc.pid

        result_folder = None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            with _runs_lock:
                _runs[run_id]["rawLog"].append(line)
                if len(_runs[run_id]["rawLog"]) > 500:
                    _runs[run_id]["rawLog"] = _runs[run_id]["rawLog"][-500:]

            # Device-code (or any other) sign-in prompt text - relayed
            # verbatim to the UI, not reformatted (same reasoning as the
            # other M365 tool's device-code work: don't guess at exact
            # wording, just don't lose it).
            if "devicelogin" in line.lower() or "enter the code" in line.lower():
                with _runs_lock:
                    _runs[run_id]["signInPrompt"] = line.strip()

            m = re.search(r"GUI_BRIDGE: RESULT_FOLDER=(.+)$", line)
            if m:
                result_folder = m.group(1).strip()

        returncode = proc.wait()

        with _runs_lock:
            _runs[run_id]["status"] = "complete" if returncode == 0 else "error"
            _runs[run_id]["returncode"] = returncode
            _runs[run_id]["resultFolder"] = result_folder

        if result_folder and os.path.isdir(result_folder):
            report_candidates = glob.glob(os.path.join(result_folder, "*.html"))
            with _runs_lock:
                _runs[run_id]["reportPath"] = report_candidates[0] if report_candidates else None

    except Exception as e:
        with _runs_lock:
            _runs[run_id]["status"] = "error"
            _runs[run_id]["error"] = str(e)


@app.route("/", methods=["GET"])
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"))


@app.route("/branding", methods=["GET"])
def get_branding():
    return jsonify(load_branding())


@app.route("/branding", methods=["POST"])
def save_branding():
    body = request.get_json() or {}
    data = {**DEFAULT_BRANDING, **{k: v for k, v in body.items() if k in DEFAULT_BRANDING}}
    with open(BRANDING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify(data)


def _module_import_snippet():
    """Same 'prefer the local copy next to this project, fall back to a
    by-name lookup' logic as Run-Assessment.ps1 - kept in sync so /profiles
    finds the same module Run-Assessment.ps1 will actually use."""
    local_manifest = os.path.join(BASE_DIR, "..", "src", "M365-Assess", "M365-Assess.psd1")
    escaped = local_manifest.replace("'", "''")
    return (
        f"if (Test-Path -LiteralPath '{escaped}') {{ Import-Module '{escaped}' -Force }} "
        f"else {{ Import-Module M365-Assess -Force }}"
    )


@app.route("/profiles", methods=["GET"])
def list_profiles():
    """Saved M365-Assess connection profiles (the tool's own multi-client
    mechanism - this just surfaces it, doesn't reimplement it)."""
    try:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             f"{_module_import_snippet()}; Get-M365ConnectionProfile | ConvertTo-Json -Depth 5 -AsArray"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"profiles": [], "error": result.stderr.strip()[:500]})
        data = json.loads(result.stdout.strip() or "[]")
        return jsonify({"profiles": data if isinstance(data, list) else [data]})
    except Exception as e:
        return jsonify({"profiles": [], "error": str(e)})


@app.route("/sections", methods=["GET"])
def get_sections():
    return jsonify({"default": DEFAULT_SECTIONS, "optional": OPTIONAL_SECTIONS})


@app.route("/run", methods=["POST"])
def start_run():
    with _runs_lock:
        for r in _runs.values():
            if r["status"] == "running":
                return jsonify({"error": "An assessment is already running."}), 409

    params = request.get_json() or {}
    run_id = str(uuid.uuid4())[:8]
    with _runs_lock:
        _runs[run_id] = {
            "status": "starting", "rawLog": [], "signInPrompt": None,
            "resultFolder": None, "reportPath": None,
            "startedAt": datetime.datetime.now().isoformat(),
        }

    thread = threading.Thread(target=_run_assessment, args=(run_id, params), daemon=True)
    thread.start()
    return jsonify({"runId": run_id})


@app.route("/run/<run_id>/status", methods=["GET"])
def run_status(run_id):
    with _runs_lock:
        run = _runs.get(run_id)
        if not run:
            return jsonify({"error": "Unknown run"}), 404
        return jsonify({
            "status": run["status"],
            "signInPrompt": run.get("signInPrompt"),
            "recentLog": run["rawLog"][-15:],
            "reportReady": bool(run.get("reportPath")),
            "error": run.get("error"),
        })


@app.route("/run/<run_id>/report", methods=["GET"])
def get_report(run_id):
    with _runs_lock:
        run = _runs.get(run_id)
    if not run or not run.get("reportPath") or not os.path.exists(run["reportPath"]):
        return jsonify({"error": "Report not ready"}), 404
    return send_file(run["reportPath"], mimetype="text/html")


@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "online"})


if __name__ == "__main__":
    import webbrowser, threading as _t, time

    def open_browser():
        time.sleep(1.2)
        webbrowser.open("http://localhost:5050")

    _t.Thread(target=open_browser, daemon=True).start()
    # threaded=True: same reason as the other M365 tool's backend - the UI
    # polls /run/<id>/status on a separate connection while a run is in
    # flight, which the single-threaded dev-server default can't service
    # concurrently with the request that kicked the run off.
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
