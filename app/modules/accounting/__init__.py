from flask import Blueprint

accounting_bp = Blueprint('accounting', __name__, url_prefix='/accounting')

from app.modules.accounting import routes
