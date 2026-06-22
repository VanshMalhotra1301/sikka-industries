from flask import Blueprint

hrms_bp = Blueprint('hrms', __name__)

from app.modules.hrms import routes
