"""Saves keys and passwords from the Settings page in Windows Credential Manager
(macOS: Keychain), never in a text file. Values are never read back to the screen."""
import hashlib
import hmac
import os
import re
import time

import keyring
from keyring.errors import PasswordDeleteError

import config

API_KEY_NAME = "anthropic_api_key"
ADMIN_HASH_NAME = "admin_password_hash"


# ---------------------------------------------------------------- Claude API key --

def api_key_status() -> str:
    """'saved' (credential store), 'env' (plain text in .env) or 'missing'."""
    if config.stored_secret(API_KEY_NAME):
        return "saved"
    return "env" if config.ANTHROPIC_API_KEY else "missing"


def save_api_key(key: str) -> None:
    keyring.set_password(config.APP_KEYRING_SERVICE, API_KEY_NAME, key)
    set_env_value("ANTHROPIC_API_KEY", "")  # remove any plain-text copy
    os.environ.pop("ANTHROPIC_API_KEY", None)
    config.ANTHROPIC_API_KEY = key


# ---------------------------------------------------------------- server login --

def server_password_saved() -> bool:
    if not config.SSAS_USERNAME:
        return False
    try:
        return bool(keyring.get_password(config.KEYRING_SERVICE, config.SSAS_USERNAME))
    except Exception:
        return False


def save_server_address(server: str, database: str) -> None:
    """Not secret, so these go in .env."""
    for key, value in (("SSAS_SERVER", server), ("SSAS_DATABASE", database)):
        set_env_value(key, value)
        setattr(config, key, value)


def save_server_login(username: str, password: str) -> None:
    """Blank username = use this computer's Windows login. Blank password = keep the saved one."""
    if username != config.SSAS_USERNAME:
        set_env_value("SSAS_USERNAME", username)
        config.SSAS_USERNAME = username
    if username and password:
        keyring.set_password(config.KEYRING_SERVICE, username, password)


# ---------------------------------------------------------------- admin password --

def has_admin_password() -> bool:
    return bool(config.stored_secret(ADMIN_HASH_NAME))


def set_admin_password(password: str) -> None:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    keyring.set_password(config.APP_KEYRING_SERVICE, ADMIN_HASH_NAME, f"{salt.hex()}${digest.hex()}")


def check_admin_password(password: str) -> bool:
    stored = config.stored_secret(ADMIN_HASH_NAME)
    if "$" not in stored:
        return False
    salt_hex, digest_hex = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _login_key() -> bytes:
    """Signs "keep me signed in" tokens. It comes from the admin password's hash, so changing the
    admin password (or resetting it) signs every computer out."""
    stored = config.stored_secret(ADMIN_HASH_NAME)
    return hashlib.sha256(f"keep-signed-in:{stored}".encode()).digest() if stored else b""


def make_login_token(days: int) -> str:
    """A token a browser keeps to stay signed in as admin for some days."""
    expires = str(int(time.time()) + days * 86400)
    return f"{expires}.{hmac.new(_login_key(), expires.encode(), hashlib.sha256).hexdigest()}"


def check_login_token(token: str) -> bool:
    expires, _, signature = str(token or "").partition(".")
    key = _login_key()
    if not key or not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(hmac.new(key, expires.encode(), hashlib.sha256).hexdigest(), signature)


def clear_admin_password() -> None:
    try:
        keyring.delete_password(config.APP_KEYRING_SERVICE, ADMIN_HASH_NAME)
    except PasswordDeleteError:
        pass


# ---------------------------------------------------------------- .env --

def set_env_value(key: str, value: str) -> None:
    """Set KEY=value in .env, keeping everything else in the file as it is."""
    env = config.ENV_FILE
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.MULTILINE):
        text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.MULTILINE)
    else:
        text += f"\n{line}\n"
    env.write_text(text, encoding="utf-8")
