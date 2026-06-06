from flask import Blueprint

security_bp = Blueprint('security', __name__, template_folder='../../templates/modules/security')

from app.modules.security import routes
