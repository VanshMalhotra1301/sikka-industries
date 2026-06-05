from flask import Blueprint

settings_bp = Blueprint('settings', __name__, template_folder='templates')

from app.modules.settings import routes
