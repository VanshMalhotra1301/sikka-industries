from flask import Blueprint

manufacturing_bp = Blueprint('manufacturing', __name__, url_prefix='/manufacturing')

from app.modules.manufacturing import routes
