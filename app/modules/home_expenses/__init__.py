from flask import Blueprint

home_expenses_bp = Blueprint('home_expenses', __name__)

from app.modules.home_expenses import routes
