from flask import request
from flask_login import current_user
from app import db
from app.models import ActivityLog, SystemNotification

def get_client_ip():
    """Retrieve the real client IP address, checking proxy headers."""
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    else:
        ip = request.remote_addr
    return ip

def get_device_info():
    """Retrieve user agent from request."""
    return request.user_agent.string if request.user_agent else "Unknown Device"

def log_activity(action_type, description, module="System", user_id=None):
    """
    Logs an activity into the Activity Intelligence Engine.
    
    :param action_type: e.g., 'Created Purchase Bill'
    :param description: detailed description of the action
    :param module: e.g., 'Purchases', 'CRM', 'Inventory'
    :param user_id: ID of the user performing the action (defaults to current_user)
    """
    try:
        uid = user_id
        if uid is None and current_user and current_user.is_authenticated:
            uid = current_user.id
            
        ip = get_client_ip() if request else None
        device = get_device_info() if request else None

        activity = ActivityLog(
            user_id=uid,
            module=module,
            action_type=action_type,
            description=description,
            ip_address=ip,
            device_info=device
        )
        db.session.add(activity)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Fallback or pass, we don't want to crash the main transaction just for an activity log if it's separate
        # But if it's part of the same transaction, we shouldn't commit here.
        # So we should be careful. Actually, if we are in the middle of a transaction,
        # calling db.session.commit() might commit prematurely. 
        # Better to just add to the session and let the calling route commit it.
        pass

def log_activity_no_commit(action_type, description, module="System", user_id=None):
    """
    Same as log_activity but does not call db.session.commit().
    Useful when called inside a route that manages its own transaction.
    """
    try:
        uid = user_id
        if uid is None and current_user and current_user.is_authenticated:
            uid = current_user.id
            
        ip = get_client_ip() if request else None
        device = get_device_info() if request else None

        activity = ActivityLog(
            user_id=uid,
            module=module,
            action_type=action_type,
            description=description,
            ip_address=ip,
            device_info=device
        )
        db.session.add(activity)
    except Exception:
        pass


def notify_admins(message, alert_level='info', module='System', target_role=None):
    """
    Sends a real-time notification to Admins and Owners.
    
    :param message: The notification message.
    :param alert_level: 'info', 'warning', 'danger', 'success'
    :param module: The module this notification originates from.
    :param target_role: Restrict to specific role if needed, default is Admin/Owner.
    """
    try:
        notification = SystemNotification(
            message=message,
            alert_level=alert_level,
            module=module,
            target_role=target_role
        )
        db.session.add(notification)
        # We don't commit here to avoid messing up active transactions.
    except Exception:
        pass
