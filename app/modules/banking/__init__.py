from flask import Blueprint

banking_bp = Blueprint('banking', __name__, template_folder='templates')

from app.modules.banking import routes
