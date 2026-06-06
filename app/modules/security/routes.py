from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from datetime import datetime, timedelta

from app import db
from app.models import User, ActivityLog, AuditLog, SystemNotification, UserSession
from app.modules.security import security_bp
from app.utils.decorators import roles_required

@security_bp.before_request
@login_required
@roles_required(['Admin', 'Owner'])
def restrict_security_module():
    """Ensure entire blueprint is strictly restricted to Admin and Owner."""
    pass

@security_bp.route('/dashboard')
def dashboard():
    """Security & Monitoring Analytics Dashboard."""
    today = datetime.utcnow().date()
    start_of_day = datetime(today.year, today.month, today.day)
    
    # Quick Stats
    total_actions_today = ActivityLog.query.filter(ActivityLog.date >= start_of_day).count()
    total_logins_today = UserSession.query.filter(UserSession.login_time >= start_of_day).count()
    failed_logins = ActivityLog.query.filter(ActivityLog.date >= start_of_day, ActivityLog.action_type == 'Failed Login').count()
    record_mods = AuditLog.query.filter(AuditLog.date >= start_of_day).count()
    deletions = ActivityLog.query.filter(ActivityLog.date >= start_of_day, ActivityLog.action_type.like('%Deleted%')).count()
    reports_exported = ActivityLog.query.filter(ActivityLog.date >= start_of_day, ActivityLog.action_type.like('%Export%')).count()

    # Most Active User Today
    most_active = db.session.query(
        User.username, func.count(ActivityLog.id).label('total')
    ).join(ActivityLog, User.id == ActivityLog.user_id)\
     .filter(ActivityLog.date >= start_of_day)\
     .group_by(User.username).order_by(desc('total')).first()
     
    # Most Used Module Today
    most_used_module = db.session.query(
        ActivityLog.module, func.count(ActivityLog.id).label('total')
    ).filter(ActivityLog.date >= start_of_day)\
     .group_by(ActivityLog.module).order_by(desc('total')).first()

    # Data for charts
    # 1. Activity Trend (Last 7 Days)
    seven_days_ago = start_of_day - timedelta(days=6)
    activity_trend_query = db.session.query(
        func.date(ActivityLog.date).label('d'), func.count(ActivityLog.id)
    ).filter(ActivityLog.date >= seven_days_ago).group_by('d').all()
    
    # Pad missing days
    trend_dict = {str(d): c for d, c in activity_trend_query}
    activity_trend_labels = []
    activity_trend_data = []
    for i in range(7):
        day = (seven_days_ago + timedelta(days=i)).date()
        activity_trend_labels.append(day.strftime('%d %b'))
        activity_trend_data.append(trend_dict.get(str(day), 0))

    return render_template('modules/security/dashboard.html',
                           total_actions=total_actions_today,
                           total_logins=total_logins_today,
                           failed_logins=failed_logins,
                           record_mods=record_mods,
                           deletions=deletions,
                           reports_exported=reports_exported,
                           most_active=most_active,
                           most_used_module=most_used_module,
                           trend_labels=activity_trend_labels,
                           trend_data=activity_trend_data)


@security_bp.route('/notifications', methods=['GET'])
def notifications():
    """Admin Notification Center."""
    module_filter = request.args.get('module')
    
    query = SystemNotification.query
    if module_filter:
        query = query.filter_by(module=module_filter)
        
    notifications_list = query.order_by(SystemNotification.date.desc()).limit(100).all()
    
    return render_template('modules/security/notifications.html', notifications=notifications_list)

@security_bp.route('/notifications/mark_read', methods=['POST'])
def mark_read():
    """Mark all notifications as read."""
    SystemNotification.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'success')
    return redirect(url_for('security.notifications'))


@security_bp.route('/activity-logs')
def activity_logs():
    """Global Activity Logs View."""
    logs = ActivityLog.query.order_by(ActivityLog.date.desc()).limit(200).all()
    return render_template('modules/security/activity_logs.html', logs=logs)


@security_bp.route('/audit-trail')
def audit_trail():
    """Complete Field-Level Audit Trail."""
    audits = AuditLog.query.order_by(AuditLog.date.desc()).limit(200).all()
    return render_template('modules/security/audit_trail.html', audits=audits)


@security_bp.route('/sessions')
def sessions():
    """User Sessions and Security Center."""
    active_sessions = UserSession.query.filter_by(status='Active').order_by(UserSession.login_time.desc()).all()
    historical_sessions = UserSession.query.filter(UserSession.status != 'Active').order_by(UserSession.login_time.desc()).limit(50).all()
    
    return render_template('modules/security/sessions.html', 
                           active_sessions=active_sessions,
                           historical_sessions=historical_sessions)
