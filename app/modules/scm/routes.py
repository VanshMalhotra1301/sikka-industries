from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models import Supplier, LedgerEntry, Purchase
from app.modules.scm import scm_bp
from app.utils.decorators import roles_required

@scm_bp.route('/suppliers', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def list_suppliers():
    """Renders supplier profile list entries and captures procurement vendors."""
    if request.method == 'POST':
        name        = (request.form.get('name')        or '').strip()
        phone       = (request.form.get('phone')       or '').strip()
        gst_number  = (request.form.get('gst_number')  or '').strip()
        address     = (request.form.get('address')     or '').strip()
        state       = (request.form.get('state')       or 'Delhi').strip()

        if not name:
            flash('Supplier name cannot be empty.', 'danger')
            return redirect(url_for('scm.list_suppliers'))

        new_supplier = Supplier(name=name, phone=phone, gst_number=gst_number,
                                address=address, state=state)
        db.session.add(new_supplier)
        db.session.flush()

        op_bal  = float(request.form.get('opening_balance') or 0.0)
        op_type = request.form.get('opening_balance_type', 'Cr')

        from app.models import AccountGroup, Ledger
        sc_group = AccountGroup.query.filter_by(name='Sundry Creditors').first()
        if sc_group:
            # Guard against duplicate ledger name (unique constraint)
            existing_ledger = Ledger.query.filter_by(name=name).first()
            if not existing_ledger:
                supp_ledger = Ledger(name=name, group_id=sc_group.id,
                                    opening_balance=op_bal,
                                    opening_balance_type=op_type)
                db.session.add(supp_ledger)

        db.session.commit()
        flash(f'Supplier "{name}" added successfully.', 'success')
        return redirect(url_for('scm.list_suppliers'))

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    
    from app.models import Ledger, VoucherEntry
    supplier_data = []
    for s in suppliers:
        ledger = Ledger.query.filter_by(name=s.name).first()
        
        op_bal = ledger.opening_balance if ledger else 0.0
        op_type = ledger.opening_balance_type if ledger else 'Cr'
        
        if ledger:
            debits = db.session.query(func.sum(VoucherEntry.amount)).filter_by(ledger_id=ledger.id, entry_type='Dr').scalar() or 0.0
            credits = db.session.query(func.sum(VoucherEntry.amount)).filter_by(ledger_id=ledger.id, entry_type='Cr').scalar() or 0.0
            outstanding = (op_bal if op_type == 'Cr' else -op_bal) + credits - debits
        else:
            outstanding = 0.0
        supplier_data.append({'profile': s, 'outstanding': outstanding, 'op_bal': op_bal, 'op_type': op_type})

    return render_template('modules/scm/list.html', suppliers=supplier_data)

@scm_bp.route('/suppliers/statement/<int:id>')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def statement(id):
    """Generates financial liability balances and history reports for suppliers."""
    supplier = Supplier.query.get_or_404(id)
    from app.models import Ledger, VoucherEntry, Voucher
    
    ledger = Ledger.query.filter_by(name=supplier.name).first()
    op_balance = 0.0
    op_type = 'Cr'
    if ledger:
        op_balance = ledger.opening_balance
        op_type = ledger.opening_balance_type
        ledger_items = VoucherEntry.query.filter_by(ledger_id=ledger.id).join(Voucher).order_by(Voucher.date.asc()).all()
    else:
        ledger_items = []
    
    balance = op_balance if op_type == 'Cr' else -op_balance
    statement_records = []
    for entry in ledger_items:
        debit = entry.amount if entry.entry_type == 'Dr' else 0.0
        credit = entry.amount if entry.entry_type == 'Cr' else 0.0
        balance += (credit - debit)
        
        desc = entry.voucher.narration or ""
        
        if entry.voucher.voucher_type == 'Purchase' and entry.voucher.reference and entry.voucher.reference.startswith('BILL-'):
            purchase_id_str = entry.voucher.reference.replace('BILL-', '')
            if purchase_id_str.isdigit():
                from app.models import Purchase
                purchase = Purchase.query.get(int(purchase_id_str))
                if purchase:
                    lines = [f"<strong>Purchase Bill #{purchase.id}</strong>"]
                    for item in purchase.items:
                        lines.append(f"<div style='font-size:0.9em;color:var(--text-secondary);'>• {item.product.name} ({item.quantity:g} qty &times; ₹{item.unit_cost:,.2f}) = ₹{item.total_amount:,.2f}</div>")
                    desc = "".join(lines)
        elif entry.voucher.voucher_type == 'Payment':
            desc = f"<strong>Payment Disbursed</strong><br><span style='font-size:0.9em;color:var(--text-secondary);'>{desc}</span>"

        statement_records.append({
            'date': entry.voucher.date,
            'description': desc,
            'reference': f"{entry.voucher.voucher_type} #{entry.voucher.voucher_number}",
            'debit': debit,
            'credit': credit,
            'running_balance': balance
        })
        
    return render_template('modules/scm/statement.html', supplier=supplier, records=statement_records, current_balance=balance, op_balance=op_balance, op_type=op_type)

@scm_bp.route('/suppliers/edit/<int:id>', methods=['POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def edit_supplier(id):
    supplier    = Supplier.query.get_or_404(id)
    name        = (request.form.get('name')        or '').strip()
    phone       = (request.form.get('phone')       or '').strip()
    gst_number  = (request.form.get('gst_number')  or '').strip()
    address     = (request.form.get('address')     or '').strip()
    op_bal      = float(request.form.get('opening_balance') or 0.0)
    op_type     = request.form.get('opening_balance_type', 'Cr')

    if not name:
        flash('Supplier Name is required.', 'danger')
        return redirect(url_for('scm.list_suppliers'))

    old_name        = supplier.name
    supplier.name   = name
    supplier.phone  = phone
    supplier.gst_number = gst_number
    supplier.address    = address

    from app.models import Ledger, AccountGroup
    ledger = Ledger.query.filter_by(name=old_name).first()
    if ledger:
        # Only rename if the new name isn't already taken by another ledger
        conflict = Ledger.query.filter(
            Ledger.name == name, Ledger.id != ledger.id
        ).first()
        if not conflict:
            ledger.name = name
        ledger.opening_balance      = op_bal
        ledger.opening_balance_type = op_type
    else:
        sc_group = AccountGroup.query.filter_by(name='Sundry Creditors').first()
        if sc_group and not Ledger.query.filter_by(name=name).first():
            new_ledger = Ledger(name=name, group_id=sc_group.id,
                                opening_balance=op_bal,
                                opening_balance_type=op_type)
            db.session.add(new_ledger)

    db.session.commit()
    flash(f'Supplier "{name}" updated successfully.', 'success')
    return redirect(url_for('scm.list_suppliers'))

@scm_bp.route('/suppliers/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def delete_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    has_purchases = Purchase.query.filter_by(supplier_id=id).first()
    has_ledger = LedgerEntry.query.filter_by(account_type='Supplier', entity_id=id).first()

    if has_purchases or has_ledger:
        flash(f'Cannot delete supplier "{supplier.name}" because they have associated transaction history.', 'danger')
        return redirect(url_for('scm.list_suppliers'))

    db.session.delete(supplier)
    db.session.commit()
    flash(f'Supplier account profile "{supplier.name}" deleted successfully.', 'success')
    return redirect(url_for('scm.list_suppliers'))
    