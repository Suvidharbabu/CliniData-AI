"""Vercel serverless entry point. Vercel detects the ASGI `app` object."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.main import app  # noqa: E402,F401
