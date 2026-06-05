from flask import Blueprint

crm_bp = Blueprint('crm', __name__, url_prefix='/crm')

from app.modules.crm import routes