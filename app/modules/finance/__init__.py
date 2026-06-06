from flask import Blueprint

finance_bp = Blueprint('finance', __name__)

from app.modules.finance import routes
