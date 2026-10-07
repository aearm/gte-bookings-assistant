"""Tries the common connection settings for Analysis Services and tells you which one works.

Run:  python test_connection.py
      python test_connection.py "Some Setting=Value;"   (also try your own extra settings)
If one works, it offers to save that setting to .env for you.
"""
import re
import socket
import ssl
import sys

import config
import ssas

TEST_QUERY = "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
PLAIN = "Protocol Format=XML;Transport Compression=None;"

# (description, extra connection-string settings)
VARIANTS = [
    ("Default settings", ""),
    ("No compression, plain XML", PLAIN),
    ("No compression", "Transport Compression=None;"),
    ("Plain XML", "Protocol Format=XML;"),
    ("NTLM login", "SSPI=NTLM;"),
    ("NTLM + no compression, plain XML", "SSPI=NTLM;" + PLAIN),
    ("NTLM + basic protection level + plain", "SSPI=NTLM;Protection Level=Connect;" + PLAIN),
    ("Encrypted data", "Use Encryption for Data=True;"),
    ("Encrypted data + plain", "Use Encryption for Data=True;" + PLAIN),
    ("Packet privacy", "Protection Level=Pkt Privacy;"),
]


def short_error(exc: Exception) -> str:
    text = str(exc).strip() or repr(exc)
    return text.splitlines()[0][:110]


def probe_port() -> None:
    """Find out what the port speaks: plain TCP, TLS (encrypted), or a web server."""
    host, _, port = config.SSAS_SERVER.partition(":")
    port = int(port or 2383)
    print(f"Checking port {port} on {host} ...")
    try:
        with socket.create_connection((host, port), timeout=8):
            print("  Port is open.")
    except Exception as exc:
        print(f"  Cannot open the port: {exc}")
        return
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                print(f"  Port expects an ENCRYPTED (TLS) connection: {tls.version()}")
                try:
                    tls.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                    first = tls.recv(200).decode(errors="replace").splitlines()
                    if first and first[0].startswith("HTTP/"):
                        print(f"  It is an HTTPS web endpoint (answered '{first[0]}').")
                except Exception:
                    pass
                return
    except Exception:
        print("  Port does not use TLS encryption (normal for Analysis Services).")
    try:
        with socket.create_connection((host, port), timeout=8) as raw:
            raw.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            raw.settimeout(5)
            first = raw.recv(200).decode(errors="replace").splitlines()
            if first and first[0].startswith("HTTP/"):
                print(f"  Port is a plain HTTP web endpoint (answered '{first[0]}').")
    except Exception:
        pass


def try_variant(extra: str, use_login: bool) -> str | None:
    """Returns None on success, or a short error message."""
    saved_user, saved_extra = config.SSAS_USERNAME, config.SSAS_CONNECTION_EXTRA
    try:
        if not use_login:
            config.SSAS_USERNAME = ""
        config.SSAS_CONNECTION_EXTRA = extra
        ssas.run_query(TEST_QUERY, max_rows=5, conn_str=ssas.connection_string())
        return None
    except Exception as exc:
        return short_error(exc)
    finally:
        config.SSAS_USERNAME, config.SSAS_CONNECTION_EXTRA = saved_user, saved_extra


def save_to_env(extra: str, clear_username: bool) -> None:
    env = config.BASE_DIR / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    updates = [("SSAS_CONNECTION_EXTRA", extra)] + ([("SSAS_USERNAME", "")] if clear_username else [])
    for key, value in updates:
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, flags=re.MULTILINE):
            text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.MULTILINE)
        else:
            text += f"\n{line}\n"
    env.write_text(text, encoding="utf-8")


def main() -> int:
    print(f"Server:   {config.SSAS_SERVER}\nDatabase: {config.SSAS_DATABASE}")
    print(f"Username: {config.SSAS_USERNAME or '(none - Windows login)'}\n")
    probe_port()
    print()

    variants = list(VARIANTS)
    if len(sys.argv) > 1:
        custom = sys.argv[1].strip()
        variants.insert(0, ("Your custom settings", custom if custom.endswith(";") else custom + ";"))

    plans = []
    if config.SSAS_USERNAME:
        plans += [(f"{name} [username + password]", extra, True) for name, extra in variants]
    plans += [(f"{name} [your Windows login]", extra, False) for name, extra in variants[:2]]

    for name, extra, use_login in plans:
        print(f"Trying: {name} ... ", end="", flush=True)
        error = try_variant(extra, use_login)
        if error is None:
            print("WORKS")
            print(f"\nUse these settings in .env:\n  SSAS_CONNECTION_EXTRA={extra}")
            if config.SSAS_USERNAME and not use_login:
                print("  SSAS_USERNAME=   (leave blank: your Windows login works)")
            if input("\nSave this to .env now? (y/n): ").strip().lower() == "y":
                save_to_env(extra, clear_username=bool(config.SSAS_USERNAME) and not use_login)
                print("Saved. Next: python build_schema.py")
            return 0
        print(f"failed: {error}")

    print("\nNone worked. Send the output above (it contains no password) to get help.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
