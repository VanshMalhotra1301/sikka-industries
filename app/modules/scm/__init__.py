from flask import Blueprint

scm_bp = Blueprint('scm', __name__, url_prefix='/scm')

from app.modules.scm import routes