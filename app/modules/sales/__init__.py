from flask import Blueprint

sales_bp = Blueprint('sales', __name__, url_prefix='/sales')

from app.modules.sales import routes
