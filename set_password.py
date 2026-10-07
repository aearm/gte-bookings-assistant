"""Saves the model password in Windows Credential Manager (not in a text file).

Run:  python set_password.py
Run it again whenever your password changes.
"""
import getpass
import sys

import keyring

import config


def main() -> int:
    user = config.SSAS_USERNAME
    if not user:
        print("Set SSAS_USERNAME in .env first (e.g. GTE\\jsmith or jsmith@company.com), then run this again.")
        return 1
    print(f"Saving password for {user} on {config.SSAS_SERVER}")
    password = getpass.getpass("Password (nothing shows as you type): ")
    if not password:
        print("No password entered, nothing saved.")
        return 1
    keyring.set_password(config.KEYRING_SERVICE, user, password)
    print("Saved in Windows Credential Manager. Next: python build_schema.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
