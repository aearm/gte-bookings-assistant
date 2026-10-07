"""Forgot the admin password for the Settings page? Run this, then open Settings in the app
and create a new one. Saved keys and passwords are kept.

Run:  python reset_admin_password.py
"""
import secrets_store

secrets_store.clear_admin_password()
print("Admin password removed. Open the Settings page in the app to create a new one.")
