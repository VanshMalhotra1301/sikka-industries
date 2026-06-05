from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user, logout_user
from app import db, bcrypt
from app.models import User, AccountGroup, Ledger
from app.modules.settings import settings_bp
from app.utils.decorators import roles_required

@settings_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin'])
def index():
    """System Settings & Developer Tools Dashboard"""
    return render_template('modules/settings/index.html')

@settings_bp.route('/factory-reset', methods=['POST'])
@login_required
@roles_required(['Admin'])
def factory_reset():
    """Wipes the database and recreates the baseline structure."""
    password = request.form.get('password')
    
    if not password:
        flash('Password is required to confirm a factory reset.', 'danger')
        return redirect(url_for('settings.index'))
        
    if not bcrypt.check_password_hash(current_user.password_hash, password):
        flash('Authentication failed. Incorrect password.', 'danger')
        return redirect(url_for('settings.index'))
        
    try:
        # Save current user info to recreate them
        admin_username = current_user.username
        admin_password_hash = current_user.password_hash
        admin_role = current_user.role
        
        # 1. Drop and Recreate All Tables
        db.drop_all()
        db.create_all()
        
        # 2. Seed Baseline Account Groups (from init_db.py)
        groups = [
            {'name': 'Capital Account', 'nature': 'Equity', 'is_system': True},
            {'name': 'Current Assets', 'nature': 'Asset', 'is_system': True},
            {'name': 'Current Liabilities', 'nature': 'Liability', 'is_system': True},
            {'name': 'Fixed Assets', 'nature': 'Asset', 'is_system': True},
            {'name': 'Direct Expenses', 'nature': 'Expense', 'is_system': True},
            {'name': 'Indirect Expenses', 'nature': 'Expense', 'is_system': True},
            {'name': 'Direct Incomes', 'nature': 'Revenue', 'is_system': True},
            {'name': 'Indirect Incomes', 'nature': 'Revenue', 'is_system': True},
            {'name': 'Sundry Debtors', 'parent': 'Current Assets', 'is_system': True},
            {'name': 'Sundry Creditors', 'parent': 'Current Liabilities', 'is_system': True},
            {'name': 'Cash-in-hand', 'parent': 'Current Assets', 'is_system': True},
            {'name': 'Bank Accounts', 'parent': 'Current Assets', 'is_system': True},
            {'name': 'Duties & Taxes', 'parent': 'Current Liabilities', 'is_system': True},
            {'name': 'Sales Accounts', 'nature': 'Revenue', 'is_system': True},
            {'name': 'Purchase Accounts', 'nature': 'Expense', 'is_system': True},
        ]
        
        group_objs = {}
        for g in groups:
            parent_id = None
            if 'parent' in g:
                parent_id = group_objs[g['parent']].id
            ag = AccountGroup(
                name=g['name'],
                nature=g.get('nature'),
                is_system=g['is_system'],
                parent_id=parent_id
            )
            db.session.add(ag)
            db.session.flush()
            group_objs[g['name']] = ag
            
        # 3. Seed Baseline Ledgers
        ledgers = [
            {'name': 'Cash', 'group': 'Cash-in-hand', 'is_system': True},
            {'name': 'Sales', 'group': 'Sales Accounts', 'is_system': True},
            {'name': 'Purchases', 'group': 'Purchase Accounts', 'is_system': True},
            {'name': 'CGST', 'group': 'Duties & Taxes', 'is_system': True},
            {'name': 'SGST', 'group': 'Duties & Taxes', 'is_system': True},
            {'name': 'IGST', 'group': 'Duties & Taxes', 'is_system': True},
        ]
        
        for l in ledgers:
            ledger = Ledger(
                name=l['name'],
                group_id=group_objs[l['group']].id,
                is_system=l['is_system']
            )
            db.session.add(ledger)
            
        # 4. Recreate the Admin User
        admin_user = User(
            username=admin_username,
            password_hash=admin_password_hash,
            role=admin_role,
            is_active=True
        )
        db.session.add(admin_user)
        
        db.session.commit()
        
        # Log them out so they have to re-authenticate with the new DB state
        logout_user()
        flash('Database factory reset successful. All data has been wiped. Please log in again.', 'success')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Critical error during factory reset: {str(e)}', 'danger')
        return redirect(url_for('settings.index'))
