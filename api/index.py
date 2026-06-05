import os

# We don't need to load_dotenv in production, Vercel provides env vars.
# If we're local, we can try to load it.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import create_app

app = create_app('production')
