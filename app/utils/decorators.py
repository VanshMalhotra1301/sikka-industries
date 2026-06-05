from functools import wraps
from flask import abort
from flask_login import current_user

def roles_required(allowed_roles):
    """
    Route decorator to restrict access to specific organizational roles.
    Usage: @roles_required(['Admin', 'Accountant'])
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)  # Unauthorized
            if current_user.role not in allowed_roles:
                abort(403)  # Forbidden / Access Denied
            return f(*args, **kwargs)
        return decorated_function
    return decorator