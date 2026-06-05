import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

# Create app for production
app = create_app('production')

# Vercel uses this as the WSGI handler
