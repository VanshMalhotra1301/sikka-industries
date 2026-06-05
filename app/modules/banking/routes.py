from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Ledger, AccountGroup, VoucherEntry
from app.modules.banking import banking_bp
from app.utils.decorators import roles_required

@banking_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Accountant'])
def dashboard():
    """Lists all configured bank accounts and cash ledgers."""
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    cash_group = AccountGroup.query.filter_by(name='Cash-in-hand').first()
    
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    cash_ledgers = Ledger.query.filter_by(group_id=cash_group.id).all() if cash_group else []
    
    # Calculate current balances dynamically
    def get_balance(ledger):
        dr = sum(e.amount for e in ledger.voucher_entries if e.entry_type == 'Dr')
        cr = sum(e.amount for e in ledger.voucher_entries if e.entry_type == 'Cr')
        return dr - cr # Asset accounts have Debit balances

    for l in bank_ledgers:
        l.current_balance = get_balance(l)
        
    for l in cash_ledgers:
        l.current_balance = get_balance(l)
        
    return render_template('modules/banking/dashboard.html', bank_ledgers=bank_ledgers, cash_ledgers=cash_ledgers)

@banking_bp.route('/add', methods=['POST'])
@login_required
@roles_required(['Admin', 'Accountant'])
def add_bank():
    name = request.form.get('name')
    if not name:
        flash('Bank name is required.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    if not bank_group:
        flash('Bank Accounts group not found. Run init_db.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    existing = Ledger.query.filter_by(name=name).first()
    if existing:
        flash(f'Ledger {name} already exists.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    new_bank = Ledger(name=name, group_id=bank_group.id)
    db.session.add(new_bank)
    db.session.commit()
    
    flash(f'Bank Account "{name}" added successfully.', 'success')
    return redirect(url_for('banking.dashboard'))
