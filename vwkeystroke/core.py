"""VW Keystroke — shared core for the CLI and GUI.

Paste a secret once; it lands in a 600 env file AND in your Vaultwarden (or
Bitwarden) vault. Wraps the `bw` CLI (which handles all the vault crypto). The
unlocked session is cached in the OS keyring (Windows Credential Locker / macOS
Keychain / libsecret) so day-to-day use is just: name it, paste it.

No secret value is ever passed on argv or written anywhere but the env file
(600) and the vault.
"""
from __future__ import annotations
import base64, json, os, re, shutil, subprocess, tempfile, time

try:
    import keyring as _keyring  # cross-platform session cache
except Exception:  # pragma: no cover - optional
    _keyring = None

APP = "vw-keystroke"
KR_SERVICE = "vw-keystroke"
KR_ACCOUNT = "bw-session"

# Config search order: explicit env var, XDG-ish path, then the legacy keydrop name.
CONFIG_PATHS = [
    os.environ.get("VWKS_CONFIG"),
    os.path.expanduser("~/.config/vw-keystroke.conf"),
    os.path.expanduser("~/.config/keydrop.conf"),
]


def _dbg(msg: str):
    if not os.environ.get("VWKS_DEBUG"):
        return
    try:
        with open("/tmp/vwks-debug.log", "a", encoding="utf-8") as f:
            f.write(f"{time.time():.0f}  {msg}\n")
    except Exception:
        pass


class VwksError(Exception):
    pass


class NeedUnlock(VwksError):
    """Vault is logged in but locked — a master password is required."""


class NeedLogin(VwksError):
    """Not logged in and no API key configured — run `bw login` once."""


# ---------- config ----------
def config_path() -> str:
    for p in CONFIG_PATHS:
        if p and os.path.exists(p):
            return p
    return os.path.expanduser("~/.config/vw-keystroke.conf")


def load_conf() -> dict:
    conf = {}
    p = config_path()
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                conf[k.strip()] = v.strip().strip('"').strip("'")
    return conf


def env_dir(conf: dict | None = None) -> str:
    conf = conf or {}
    return os.path.expanduser(conf.get("ENV_DIR") or "~/.config")


def default_project(conf: dict) -> str:
    return conf.get("DEFAULT_PROJECT", "keys")


def list_projects(edir: str) -> list[str]:
    try:
        return sorted(f[:-4] for f in os.listdir(edir) if f.endswith(".env"))
    except FileNotFoundError:
        return []


# ---------- env file ----------
def valid_var(var: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var or ""))


def write_env(edir: str, project: str, var: str, value: str) -> tuple[str, str]:
    path = os.path.join(os.path.expanduser(edir), f"{project}.env")
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    out, found = [], False
    pat = re.compile(rf"^\s*{re.escape(var)}\s*=")
    for ln in lines:
        if pat.match(ln):
            out.append(f"{var}={value}"); found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{var}={value}")
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows: perms are a no-op
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path, ("updated" if found else "added")


# ---------- bw plumbing ----------
def find_bw() -> str:
    b = shutil.which("bw")
    if b:
        return b
    for cand in [
        os.path.expanduser("~/.npm-global/bin/bw"),
        "/usr/local/bin/bw",
        os.path.expandvars(r"%APPDATA%\npm\bw.cmd"),
    ]:
        if cand and os.path.exists(cand):
            return cand
    raise VwksError("bw CLI not found. Install it: npm install -g @bitwarden/cli")


def _run(bw, args, env, check=True):
    r = subprocess.run([bw] + args, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise VwksError(f"bw {args[0]} failed: {r.stderr.strip()[:200]}")
    return r


def bw_status(bw, env) -> str:
    r = _run(bw, ["status"], env, check=False)
    try:
        return json.loads(r.stdout).get("status", "unknown")
    except Exception:
        return "unknown"


def _base_env(conf) -> dict:
    return dict(os.environ)


def _ensure_server(bw, conf, env):
    url = conf.get("BW_SERVER")
    if url:
        _run(bw, ["config", "server", url], env, check=False)


# ---------- keyring session cache ----------
def _ttl_days(conf) -> int:
    try:
        return int(conf.get("KEYRING_TTL_DAYS", "30") or 0)
    except ValueError:
        return 30


def kr_get() -> str | None:
    if not _keyring:
        return None
    try:
        raw = _keyring.get_password(KR_SERVICE, KR_ACCOUNT)
    except Exception:
        return None
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if d.get("exp", 0) < time.time():
        kr_clear()
        return None
    return d.get("session")


def kr_store(session: str, ttl_days: int):
    if not _keyring or ttl_days <= 0 or not session:
        return
    try:
        _keyring.set_password(KR_SERVICE, KR_ACCOUNT,
                              json.dumps({"session": session, "exp": time.time() + ttl_days * 86400}))
    except Exception:
        pass


def kr_clear():
    if not _keyring:
        return
    try:
        _keyring.delete_password(KR_SERVICE, KR_ACCOUNT)
    except Exception:
        pass


def _session_ok(bw, base_env, sess) -> bool:
    """Validate a session by running a real op that requires an unlocked vault.
    `bw status` is unreliable here — recent bw versions report the on-disk lock
    state and return "locked" even with a valid session in the environment, so we
    probe with `bw list folders` instead. stdin is closed so an invalid session
    fails fast (returns non-zero) rather than dropping into an interactive prompt."""
    if not sess:
        return False
    try:
        r = subprocess.run([bw, "list", "folders", "--session", sess],
                           env=dict(base_env, BW_SESSION=sess),
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
    except Exception:
        return False
    return r.returncode == 0 and r.stdout.strip().startswith("[")


def session_state(conf: dict | None = None) -> str:
    """'ready' (cached session), 'locked' (need master pw), 'apikey' (can auto-login),
    'login' (need one-time `bw login`)."""
    conf = conf or load_conf()
    try:
        bw = find_bw()
    except VwksError:
        return "login"
    base = _base_env(conf)
    if _session_ok(bw, base, kr_get()):
        return "ready"
    if bw_status(bw, base) == "unauthenticated":
        cid, csec = conf.get("BW_CLIENTID"), conf.get("BW_CLIENTSECRET")
        return "apikey" if (cid and csec and "xxxx" not in (cid + csec)) else "login"
    return "locked"


def _ensure_session(bw, base_env, conf, master_password=None) -> str:
    sess = kr_get()
    _dbg(f"ensure: kr_get -> {'HIT' if sess else 'miss'}; keyring={bool(_keyring)}")
    if _session_ok(bw, base_env, sess):
        _dbg("ensure: cached session VALID -> reuse")
        kr_store(sess, _ttl_days(conf))  # idle-refresh
        return sess
    st = bw_status(bw, base_env)
    _dbg(f"ensure: cache miss/invalid; bw status(no-session)={st}")
    if st == "unauthenticated":
        _ensure_server(bw, conf, base_env)
        cid, csec = conf.get("BW_CLIENTID"), conf.get("BW_CLIENTSECRET")
        if cid and csec and "xxxx" not in (cid + csec):
            _run(bw, ["login", "--apikey"], dict(base_env, BW_CLIENTID=cid, BW_CLIENTSECRET=csec))
        else:
            raise NeedLogin("Not logged in. Run `bw login` once in a terminal, then retry.")
    if master_password is None:
        _dbg("ensure: NeedUnlock (no master password provided)")
        raise NeedUnlock("Vault is locked — a master password is required.")
    r = _run(bw, ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"],
             dict(base_env, BW_PASSWORD=master_password))
    sess = r.stdout.strip()
    _dbg(f"ensure: unlock done; session_len={len(sess)}")
    if not sess:
        raise VwksError("unlock returned no session (wrong master password?)")
    kr_store(sess, _ttl_days(conf))
    back = kr_get()
    _dbg(f"ensure: kr_store done; readback={'OK' if back == sess else 'MISMATCH/none'}; "
         f"revalidate={_session_ok(bw, base_env, sess)}")
    return sess


# ---------- vault item upsert ----------
def _folder_id(bw, env, name):
    if not name:
        return None
    r = _run(bw, ["list", "folders", "--search", name], env)
    for f in json.loads(r.stdout or "[]"):
        if f.get("name") == name:
            return f["id"]
    enc = base64.b64encode(json.dumps({"name": name}).encode()).decode()
    return json.loads(_run(bw, ["create", "folder", enc], env).stdout)["id"]


def _find_item(bw, env, name, var):
    r = _run(bw, ["list", "items", "--search", name], env)
    for it in json.loads(r.stdout or "[]"):
        if it.get("name") == name and (it.get("login") or {}).get("username") in (var, None, ""):
            return it
    return None


def _vault_upsert(bw, env, name, var, value, env_path, fid):
    field = {"name": "env_file", "value": env_path, "type": 0, "linkedId": None}
    existing = _find_item(bw, env, name, var)
    if existing:
        it = existing
        it["login"] = {**(it.get("login") or {}), "username": var, "password": value}
        it["fields"] = [f for f in (it.get("fields") or []) if f.get("name") != "env_file"] + [field]
        it["folderId"] = it.get("folderId") or fid
        enc = base64.b64encode(json.dumps(it).encode()).decode()
        _run(bw, ["edit", "item", it["id"], enc], env)
        return "updated"
    it = {"organizationId": None, "collectionIds": None, "folderId": fid, "type": 1,
          "name": name, "notes": None, "favorite": False, "fields": [field],
          "login": {"username": var, "password": value, "totp": None, "uris": []}, "reprompt": 0}
    enc = base64.b64encode(json.dumps(it).encode()).decode()
    _run(bw, ["create", "item", enc], env)
    return "created"


# ---------- top-level ----------
def drop(var, value, *, project, name=None, folder=None, env_dir_=None,
         no_vault=False, master_password=None, conf=None) -> dict:
    """Write the secret to the env file and (unless no_vault) upsert it into the vault.
    May raise NeedUnlock / NeedLogin so the caller can prompt and retry."""
    conf = conf if conf is not None else load_conf()
    if not valid_var(var):
        raise VwksError(f"invalid env var name: {var!r}")
    edir = env_dir_ or env_dir(conf)
    path, action = write_env(edir, project, var, value)
    result = {"env_path": path, "env_action": action, "vault": None, "folder": None}
    if no_vault:
        return result
    bw = find_bw()
    base_env = _base_env(conf)
    sess = _ensure_session(bw, base_env, conf, master_password)
    venv = dict(base_env, BW_SESSION=sess)
    _run(bw, ["sync"], venv, check=False)
    folder = folder or conf.get("VAULT_FOLDER", "API Keys")
    fid = _folder_id(bw, venv, folder)
    result["vault"] = _vault_upsert(bw, venv, name or var, var, value, path, fid)
    result["folder"] = folder
    return result


def lock():
    """Forget the cached session and lock the vault."""
    kr_clear()
    try:
        bw = find_bw()
        _run(bw, ["lock"], _base_env(load_conf()), check=False)
    except VwksError:
        pass
