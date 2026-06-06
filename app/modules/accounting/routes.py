from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from app import db
from app.models import Voucher, VoucherEntry, Ledger, AccountGroup, Expense
from app.modules.accounting import accounting_bp
from app.utils.decorators import roles_required
from datetime import datetime
import uuid

@accounting_bp.route('/vouchers', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def vouchers():
    """Manage Tally-style Vouchers (Receipt, Payment, Journal, Contra)."""
    if request.method == 'POST':
        voucher_type = request.form.get('voucher_type')
        narration = request.form.get('narration', '').strip()
        reference = request.form.get('reference', '').strip()
        date_str = request.form.get('date')
        
        try:
            v_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
        except:
            v_date = datetime.utcnow()

        dr_ledgers = request.form.getlist('dr_ledger[]')
        dr_amounts = request.form.getlist('dr_amount[]')
        cr_ledgers = request.form.getlist('cr_ledger[]')
        cr_amounts = request.form.getlist('cr_amount[]')

        total_dr = sum(float(a) for a in dr_amounts if a)
        total_cr = sum(float(a) for a in cr_amounts if a)

        if abs(total_dr - total_cr) > 0.01:
            flash(f"Voucher must balance! Total Dr: {total_dr}, Total Cr: {total_cr}", "danger")
            return redirect(url_for('accounting.vouchers'))

        if total_dr <= 0:
            flash("Voucher amount must be greater than zero.", "danger")
            return redirect(url_for('accounting.vouchers'))

        try:
            voucher_number = f"{voucher_type[:3].upper()}-{uuid.uuid4().hex[:6].upper()}"
            new_voucher = Voucher(
                voucher_type=voucher_type,
                voucher_number=voucher_number,
                date=v_date,
                narration=narration,
                reference=reference,
                created_by=current_user.id
            )
            db.session.add(new_voucher)
            db.session.flush()

            # Add Debit Entries
            for l_id, amt in zip(dr_ledgers, dr_amounts):
                if amt and float(amt) > 0:
                    entry = VoucherEntry(voucher_id=new_voucher.id, ledger_id=int(l_id), entry_type='Dr', amount=float(amt))
                    db.session.add(entry)

            # Add Credit Entries
            for l_id, amt in zip(cr_ledgers, cr_amounts):
                if amt and float(amt) > 0:
                    entry = VoucherEntry(voucher_id=new_voucher.id, ledger_id=int(l_id), entry_type='Cr', amount=float(amt))
                    db.session.add(entry)

            db.session.commit()
            flash(f"Voucher {voucher_number} created successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error saving voucher: {str(e)}", "danger")

        return redirect(url_for('accounting.vouchers'))

    vouchers_list = Voucher.query.order_by(Voucher.date.desc()).all()
    ledgers = Ledger.query.order_by(Ledger.name.asc()).all()
    return render_template('modules/accounting/vouchers.html', vouchers=vouchers_list, ledgers=ledgers)

@accounting_bp.route('/ledgers', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def general_ledgers():
    """Manage Chart of Accounts: Ledgers & Account Groups."""
    if request.method == 'POST':
        name = request.form.get('name').strip()
        group_id = request.form.get('group_id')
        opening_balance = float(request.form.get('opening_balance', 0.0))
        ob_type = request.form.get('opening_balance_type', 'Dr')

        if not name or not group_id:
            flash("Ledger name and group are required.", "danger")
            return redirect(url_for('accounting.general_ledgers'))

        try:
            ledger = Ledger(
                name=name,
                group_id=int(group_id),
                opening_balance=opening_balance,
                opening_balance_type=ob_type
            )
            db.session.add(ledger)
            db.session.commit()
            flash(f"Ledger '{name}' created.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating ledger: {str(e)}", "danger")

        return redirect(url_for('accounting.general_ledgers'))

    ledgers = Ledger.query.order_by(Ledger.name.asc()).all()
    groups = AccountGroup.query.order_by(AccountGroup.name.asc()).all()
    return render_template('modules/accounting/ledgers.html', ledgers=ledgers, groups=groups)

@accounting_bp.route('/ledger/transactions/<int:ledger_id>', methods=['GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def ledger_transactions(ledger_id):
    """View transactions for a specific ledger (Tally Ledger Vouchers view)."""
    ledger = Ledger.query.get_or_404(ledger_id)
    entries = VoucherEntry.query.filter_by(ledger_id=ledger.id).join(Voucher).order_by(Voucher.date.asc()).all()
    
    running_balance = ledger.opening_balance if ledger.opening_balance_type == 'Dr' else -ledger.opening_balance
    records = []
    
    for e in entries:
        if e.entry_type == 'Dr':
            running_balance += e.amount
        else:
            running_balance -= e.amount
            
        records.append({
            'date': e.voucher.date,
            'voucher_number': e.voucher.voucher_number,
            'voucher_type': e.voucher.voucher_type,
            'narration': e.voucher.narration,
            'debit': e.amount if e.entry_type == 'Dr' else 0,
            'credit': e.amount if e.entry_type == 'Cr' else 0,
            'balance': abs(running_balance),
            'balance_type': 'Dr' if running_balance >= 0 else 'Cr'
        })
        
    records.reverse()
    return render_template('modules/accounting/transactions.html', ledger=ledger, records=records)

@accounting_bp.route('/expenses', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant'])
def factory_expenses():
    """Legacy route replaced by Vouchers, but keeping logic for basic expenses."""
    flash("Please use the Vouchers (Payment/Journal) section for entering expenses.", "info")
    return redirect(url_for('accounting.vouchers'))

@accounting_bp.route('/add-cash', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner'])
def add_cash():
    """Inject extra cash into the Cash-in-Hand ledger via Owner's Equity."""
    amount = float(request.form.get('amount') or 0.0)
    narration = request.form.get('narration', '').strip()
    
    if amount <= 0:
        flash("Amount must be greater than zero.", "danger")
        return redirect(request.referrer or url_for('dashboard.index'))
        
    try:
        # Find Cash Ledger
        cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
        cash_ledger = Ledger.query.filter_by(group_id=cash_group.id).first()
        if not cash_ledger:
            cash_ledger = Ledger(name="Main Cash", group_id=cash_group.id, is_system=True)
            db.session.add(cash_ledger)
            db.session.flush()

        # Find Owner's Equity Ledger
        equity_group = AccountGroup.query.filter_by(name='Equity').first()
        equity_ledger = Ledger.query.filter_by(name="Owner's Equity").first()
        if not equity_ledger:
            equity_ledger = Ledger(name="Owner's Equity", group_id=equity_group.id, is_system=True)
            db.session.add(equity_ledger)
            db.session.flush()

        # Create Receipt Voucher
        v_number = f"REC-CASH-{uuid.uuid4().hex[:6].upper()}"
        voucher = Voucher(
            voucher_type='Receipt',
            voucher_number=v_number,
            date=datetime.utcnow(),
            narration=f"Cash injected: {narration}" if narration else "Cash injected",
            created_by=current_user.id
        )
        db.session.add(voucher)
        db.session.flush()

        # Dr Cash
        db.session.add(VoucherEntry(voucher_id=voucher.id, ledger_id=cash_ledger.id, entry_type='Dr', amount=amount))
        # Cr Owner's Equity
        db.session.add(VoucherEntry(voucher_id=voucher.id, ledger_id=equity_ledger.id, entry_type='Cr', amount=amount))

        db.session.commit()
        flash(f"Successfully added ₹{amount:,.2f} to Cash Balance.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to add cash balance: {str(e)}", "danger")

    return redirect(request.referrer or url_for('dashboard.index'))

@accounting_bp.route('/add-bank', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner'])
def add_bank():
    """Inject extra bank balance into a specific Bank ledger via Owner's Equity."""
    amount = float(request.form.get('amount') or 0.0)
    narration = request.form.get('narration', '').strip()
    bank_ledger_id = request.form.get('bank_ledger_id')
    
    if amount <= 0:
        flash("Amount must be greater than zero.", "danger")
        return redirect(request.referrer or url_for('dashboard.index'))
        
    if not bank_ledger_id:
        flash("Please select a bank.", "danger")
        return redirect(request.referrer or url_for('dashboard.index'))
        
    try:
        bank_ledger = Ledger.query.get(bank_ledger_id)
        if not bank_ledger:
            flash("Invalid bank selected.", "danger")
            return redirect(request.referrer or url_for('dashboard.index'))

        # Find Owner's Equity Ledger
        equity_group = AccountGroup.query.filter_by(name='Equity').first()
        equity_ledger = Ledger.query.filter_by(name="Owner's Equity").first()
        if not equity_ledger:
            equity_ledger = Ledger(name="Owner's Equity", group_id=equity_group.id, is_system=True)
            db.session.add(equity_ledger)
            db.session.flush()

        # Create Receipt Voucher
        v_number = f"REC-BNK-{uuid.uuid4().hex[:6].upper()}"
        voucher = Voucher(
            voucher_type='Receipt',
            voucher_number=v_number,
            date=datetime.utcnow(),
            narration=f"Bank balance injected: {narration}" if narration else "Bank balance injected",
            created_by=current_user.id
        )
        db.session.add(voucher)
        db.session.flush()

        # Dr Bank
        db.session.add(VoucherEntry(voucher_id=voucher.id, ledger_id=bank_ledger.id, entry_type='Dr', amount=amount))
        # Cr Owner's Equity
        db.session.add(VoucherEntry(voucher_id=voucher.id, ledger_id=equity_ledger.id, entry_type='Cr', amount=amount))

        db.session.commit()
        flash(f"Successfully added ₹{amount:,.2f} to {bank_ledger.name}.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to add bank balance: {str(e)}", "danger")

    return redirect(request.referrer or url_for('dashboard.index'))

@accounting_bp.route('/cash-flow', methods=['GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def cash_flow_statement():
    """Cash Flow based on Cash & Bank ledgers."""
    cash_bank_groups = AccountGroup.query.filter(AccountGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
    group_ids = [g.id for g in cash_bank_groups]
    cash_ledgers = Ledger.query.filter(Ledger.group_id.in_(group_ids)).all()
    ledger_ids = [l.id for l in cash_ledgers]

    inflows = db.session.query(
        Voucher.voucher_type, func.sum(VoucherEntry.amount)
    ).join(Voucher).filter(
        VoucherEntry.ledger_id.in_(ledger_ids), VoucherEntry.entry_type == 'Dr'
    ).group_by(Voucher.voucher_type).all()

    outflows = db.session.query(
        Voucher.voucher_type, func.sum(VoucherEntry.amount)
    ).join(Voucher).filter(
        VoucherEntry.ledger_id.in_(ledger_ids), VoucherEntry.entry_type == 'Cr'
    ).group_by(Voucher.voucher_type).all()

    total_in = sum(val for _, val in inflows) if inflows else 0.0
    total_out = sum(val for _, val in outflows) if outflows else 0.0
    net_position = total_in - total_out

    return render_template(
        'modules/accounting/cash_flow.html',
        inflows=inflows, outflows=outflows,
        total_in=total_in, total_out=total_out,
        net_position=net_position
    )