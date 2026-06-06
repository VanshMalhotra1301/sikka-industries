from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from app import db, bcrypt
from app.models import User, UserSession
from app.modules.auth import auth_bp
from app.utils.decorators import roles_required
from app.utils.security import get_client_ip, get_device_info, log_activity_no_commit

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handles secure user session authorization."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and bcrypt.check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('This account has been deactivated. Contact Admin.', 'danger')
                return render_template('modules/auth/login.html')
                
            login_user(user, remember=True)
            
            # Create User Session Record
            ip_addr = get_client_ip()
            device = get_device_info()
            user_session = UserSession(user_id=user.id, ip_address=ip_addr, device_info=device, status='Active')
            db.session.add(user_session)
            db.session.commit()
            
            session['user_session_id'] = user_session.id
            
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard.index'))
        else:
            flash('Invalid username or password configuration.', 'danger')
            
    return render_template('modules/auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """Clears user session storage matrix."""
    session_id = session.get('user_session_id')
    if session_id:
        user_session = UserSession.query.get(session_id)
        if user_session and user_session.status == 'Active':
            user_session.logout_time = datetime.utcnow()
            user_session.status = 'Logged Out'
            db.session.commit()
        session.pop('user_session_id', None)

    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/timeout', methods=['POST'])
@login_required
def timeout():
    """Triggered via AJAX when inactivity timeout occurs."""
    session_id = session.get('user_session_id')
    if session_id:
        user_session = UserSession.query.get(session_id)
        if user_session and user_session.status == 'Active':
            user_session.logout_time = datetime.utcnow()
            user_session.status = 'Session Timeout'
            db.session.commit()
        session.pop('user_session_id', None)

    logout_user()
    return {'status': 'success', 'redirect': url_for('auth.login')}, 200

@auth_bp.route('/init-admin')
def init_admin():
    """
    Emergency setup route to seed initial system profiles.
    Can be disabled or deleted after first run.
    """
    existing_user = User.query.filter_by(username='admin').first()
    if existing_user:
        return "Admin user baseline already configured.", 200
        
    hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
    admin_user = User(
        username='admin',
        password_hash=hashed_password,
        role='Admin',
        is_active=True
    )
    db.session.add(admin_user)
    db.session.commit()
    return "Demo Admin initialized! Username: admin | Password: admin123", 201

@auth_bp.route('/users', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin'])
def manage_users():
    """Enables the main Administrator profile to provision internal staff access roles."""
    if request.method == 'POST':
        username = request.form.get('username').strip().lower()
        password = request.form.get('password')
        role = request.form.get('role') # Admin, Accountant, Store Manager, Owner

        if not username or not password or not role:
            flash('All user provisioning details are strictly required.', 'danger')
            return redirect(url_for('auth.manage_users'))

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash(f'The security identifier profile "{username}" is already taken.', 'danger')
            return redirect(url_for('auth.manage_users'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(
            username=username,
            password_hash=hashed_password,
            role=role,
            is_active=True
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f'Access credentials for staff account "{username}" [{role}] successfully established.', 'success')
        return redirect(url_for('auth.manage_users'))

    staff_profiles = User.query.order_by(User.role.asc(), User.username.asc()).all()
    return render_template('modules/auth/users.html', staff=staff_profiles)


@auth_bp.route('/users/toggle/<int:user_id>', methods=['POST'])
@login_required
@roles_required(['Admin'])
def toggle_user_status(user_id):
    """Safely toggles active profiles to lock out terminated or compromised accounts."""
    if current_user.id == user_id:
        flash('Security Guardrail: An administrator cannot revoke their own active system access permissions.', 'danger')
        return redirect(url_for('auth.manage_users'))

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status_msg = "activated" if user.is_active else "revoked / suspended"
    flash(f'Access permissions for user "{user.username}" have been {status_msg}.', 'info')
    return redirect(url_for('auth.manage_users'))

@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Allows a user to securely change their own password."""
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    
    if not current_password or not new_password:
        flash('Both current and new passwords are required.', 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))
        
    if not bcrypt.check_password_hash(current_user.password_hash, current_password):
        flash('Incorrect current password.', 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))
        
    current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
    db.session.commit()
    flash('Your password has been changed successfully.', 'success')
    return redirect(request.referrer or url_for('dashboard.index'))

@auth_bp.route('/admin-reset-password/<int:user_id>', methods=['POST'])
@login_required
@roles_required(['Admin'])
def admin_reset_password(user_id):
    """Allows Admin to forcefully reset another user's password."""
    new_password = request.form.get('new_password')
    if not new_password:
        flash('New password is required.', 'danger')
        return redirect(url_for('auth.manage_users'))
        
    user = User.query.get_or_404(user_id)
    user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
    db.session.commit()
    flash(f'Password for user "{user.username}" has been successfully reset.', 'success')
    return redirect(url_for('auth.manage_users'))

