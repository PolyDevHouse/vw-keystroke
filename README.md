# 🔑 VW Keystroke

**Paste a secret once — it lands in your [Vaultwarden](https://github.com/dani-garcia/vaultwarden)/Bitwarden vault *and* a local `600` env file, in one move.**

Built for the "hot potato" moment: you just generated an API key and you want it
*off your clipboard and safely stored* without a five-step ritual — so it doesn't
end up lingering in a scratch file. Name it, paste it, done.

- 🗄️ Saves to your vault as a **Login** item (username = the env var, password = the value, with the env-file path recorded as a custom field).
- 📄 Writes `~/.config/<project>.env` (`chmod 600`, updated in place — never duplicated).
- 🔒 **Zero-knowledge**: your master password never leaves your machine; all vault crypto is done by the official `bw` CLI.
- ⚡ Caches the unlocked session in your **OS keyring** (Windows Credential Locker / macOS Keychain / Linux libsecret) so daily use needs no password.
- 🖥️ **GUI** and **CLI**, on **Windows / Linux / macOS**.

> The secret value is never passed on the command line and never echoed — only
> the `600` env file and your vault ever see it.

---

## Requirements

1. **[Bitwarden CLI](https://bitwarden.com/help/cli/)** — `npm install -g @bitwarden/cli` (provides `bw`).
2. **Python 3.9+** (Tkinter ships with the standard python.org installers).

## Install

```bash
pipx install vw-keystroke        # recommended
# or
pip install --user vw-keystroke
```

This gives you three commands: `vwks` (CLI), `keydrop` (alias), and `vwks-gui` (GUI).

### First-time setup

```bash
# point bw at your server (self-hosted Vaultwarden, or Bitwarden cloud)
bw config server https://vault.example.com
bw login                          # email + master password + 2FA (once)

# optional config
mkdir -p ~/.config
cp vw-keystroke.conf.example ~/.config/vw-keystroke.conf && chmod 600 ~/.config/vw-keystroke.conf
```

## Use

**GUI:** launch **VW Keystroke** from your app menu (Linux `.desktop` in
[`packaging/`](packaging/)), or run `vwks-gui`.

**CLI:**
```bash
vwks OPENAI_API_KEY                 # prompts (hidden) for the value
vwks OPENAI_API_KEY --project openai   # -> ~/.config/openai.env
echo -n "$SECRET" | vwks --var FOO --project bar   # piped / non-interactive
vwks --lock                         # forget the cached session + lock now
```

## Configuration

`~/.config/vw-keystroke.conf` (all optional — see [`vw-keystroke.conf.example`](vw-keystroke.conf.example)):

| Key | Meaning | Default |
|-----|---------|---------|
| `BW_SERVER` | Vault server URL | current `bw` config |
| `DEFAULT_PROJECT` | env-file basename | `keys` |
| `VAULT_FOLDER` | folder for new items | `API Keys` |
| `KEYRING_TTL_DAYS` | cached-session lifetime (`0` = never cache) | `30` |
| `ENV_DIR` | where env files go | `~/.config` |
| `BW_CLIENTID` / `BW_CLIENTSECRET` | optional API-key login | — |

## How it works

`bw` handles login and all encryption. On a drop, VW Keystroke unlocks (or reuses a
cached session), then creates/updates the vault item and the env file. If the vault
is locked it asks for your master password once; the resulting session key is stored
in your OS keyring with a TTL and refreshed on use.

## Security notes

- Nothing sensitive is stored by this tool except the `600` env file you asked for and the keyring session (same protection as your desktop login).
- A cached session means anyone at your already-unlocked machine can drop/read keys — the same exposure as a logged-in browser vault extension. Set `KEYRING_TTL_DAYS=0` to disable caching.
- This project ships **no** credentials, servers, or keys of its own.

## License

MIT © PolyDevHouse LLC
