from flask import Blueprint

purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')

from app.modules.purchases import routes
