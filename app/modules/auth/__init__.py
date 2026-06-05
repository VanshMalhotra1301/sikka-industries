from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

# Import routes at the bottom to prevent circular dependency structures
from app.modules.auth import routes
