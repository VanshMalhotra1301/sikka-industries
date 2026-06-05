import os

# Try to load dotenv for local development, ignore in production (Vercel)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import create_app

# Vercel will look for this 'app' variable
app = create_app('production')
