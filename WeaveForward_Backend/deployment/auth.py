"""Admin session factory — logs in once and returns a cookie-authed requests.Session."""
import os
import requests


def get_admin_session() -> requests.Session:
    base   = os.environ["API_BASE_URL"].rstrip("/")
    email  = os.environ["ADMIN_EMAIL"]
    passwd = os.environ["ADMIN_PASSWORD"]

    session = requests.Session()
    resp = session.post(
        f"{base}/auth/token",
        json={"email": email, "password": passwd},
        timeout=30,
    )
    resp.raise_for_status()
    return session
