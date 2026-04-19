#!/usr/bin/env python3
"""One-time login to Garmin Connect. Saves OAuth tokens to ~/.garmy/ for reuse."""
from garmy import AuthClient

auth = AuthClient()
if auth.is_authenticated:
    print("Already authenticated!")
else:
    email = input("Garmin email: ").strip()
    import getpass
    password = getpass.getpass("Garmin password: ")
    auth.login(email, password)
    print("Login successful! Tokens saved to ~/.garmy/")
