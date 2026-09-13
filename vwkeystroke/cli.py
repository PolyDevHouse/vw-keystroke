#!/usr/bin/env python3
"""VW Keystroke CLI — `vwks` (alias `keydrop`).

  vwks OPENAI_API_KEY                 # positional var, prompts for value
  vwks --var FOO --project bar
  echo -n "$SECRET" | vwks --var FOO --project bar   # non-interactive
  vwks --lock                         # forget cached session + lock
"""
import argparse, sys
from getpass import getpass
from . import core


def _read_value():
    if not sys.stdin.isatty():
        v = sys.stdin.readline().rstrip("\n")
    else:
        v = getpass("Paste value (hidden): ")
    if not v:
        sys.exit("vwks: empty value — nothing to store")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vwks",
                                 description="Store a secret in a 600 env file + Vaultwarden/Bitwarden.")
    ap.add_argument("var_pos", nargs="?", help="ENV var name (positional shortcut)")
    ap.add_argument("--var")
    ap.add_argument("--project")
    ap.add_argument("--name", help="vault item name (default: the ENV var name)")
    ap.add_argument("--folder")
    ap.add_argument("--env-dir")
    ap.add_argument("--no-vault", action="store_true", help="write env file only")
    ap.add_argument("--lock", action="store_true", help="forget cached session + lock, then exit")
    a = ap.parse_args(argv)

    if a.lock:
        core.lock()
        print("→ cached session cleared; vault locked")
        return 0

    conf = core.load_conf()
    interactive = sys.stdin.isatty()
    var = a.var or a.var_pos or (input("Env var name: ").strip() if interactive else "")
    if not core.valid_var(var):
        sys.exit(f"vwks: invalid/empty env var name: {var!r}")
    proj_default = core.default_project(conf)
    project = a.project or (input(f"Project [{proj_default}]: ").strip() if interactive else "") or proj_default

    value = _read_value()

    mp = None
    while True:
        try:
            res = core.drop(var, value, project=project, name=a.name, folder=a.folder,
                            env_dir_=a.env_dir, no_vault=a.no_vault, master_password=mp, conf=conf)
            break
        except core.NeedUnlock:
            if not interactive:
                sys.exit("vwks: vault locked and no TTY to prompt for master password")
            mp = getpass("Vault master password (hidden): ")
        except core.NeedLogin as e:
            sys.exit(f"vwks: {e}")
        except core.VwksError as e:
            sys.exit(f"vwks: {e}")

    print(f"→ {res['env_action']} {var} in {res['env_path']} (600)")
    if res["vault"]:
        print(f'→ Vaultwarden: {res["vault"]} login "{a.name or var}" in folder "{res["folder"]}" ✓')
    else:
        print("→ vault skipped (--no-vault)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
