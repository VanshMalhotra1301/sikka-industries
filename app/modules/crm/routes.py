from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models import Customer, LedgerEntry, Sale
from app.modules.crm import crm_bp
from app.utils.decorators import roles_required

@crm_bp.route('/customers', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def list_customers():
    """Renders all master customer accounts and registers new entities."""
    if request.method == 'POST':
        name       = (request.form.get('name')       or '').strip()
        phone      = (request.form.get('phone')      or '').strip()
        gst_number = (request.form.get('gst_number') or '').strip()
        address    = (request.form.get('address')    or '').strip()
        email      = (request.form.get('email')      or '').strip()
        state      = (request.form.get('state')      or 'Delhi').strip()

        if not name:
            flash('Customer Name is required.', 'danger')
            return redirect(url_for('crm.list_customers'))

        new_customer = Customer(name=name, phone=phone, gst_number=gst_number,
                                address=address, email=email, state=state)
        db.session.add(new_customer)
        db.session.flush()

        op_bal  = float(request.form.get('opening_balance') or 0.0)
        op_type = request.form.get('opening_balance_type', 'Dr')

        from app.models import AccountGroup, Ledger
        sd_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
        if sd_group:
            # Guard against duplicate ledger name (unique constraint)
            existing_ledger = Ledger.query.filter_by(name=name).first()
            if not existing_ledger:
                cust_ledger = Ledger(name=name, group_id=sd_group.id,
                                    opening_balance=op_bal,
                                    opening_balance_type=op_type)
                db.session.add(cust_ledger)

        db.session.commit()
        flash(f'Customer "{name}" added successfully.', 'success')
        return redirect(url_for('crm.list_customers'))

    customers = Customer.query.order_by(Customer.name.asc()).all()
    
    from app.models import Ledger, VoucherEntry
    customer_data = []
    for c in customers:
        ledger = Ledger.query.filter_by(name=c.name).first()
        
        op_bal = ledger.opening_balance if ledger else 0.0
        op_type = ledger.opening_balance_type if ledger else 'Dr'
        
        if ledger:
            debits = db.session.query(func.sum(VoucherEntry.amount)).filter_by(ledger_id=ledger.id, entry_type='Dr').scalar() or 0.0
            credits = db.session.query(func.sum(VoucherEntry.amount)).filter_by(ledger_id=ledger.id, entry_type='Cr').scalar() or 0.0
            outstanding = (op_bal if op_type == 'Dr' else -op_bal) + debits - credits
        else:
            outstanding = 0.0
        customer_data.append({'profile': c, 'outstanding': outstanding, 'op_bal': op_bal, 'op_type': op_type})

    return render_template('modules/crm/list.html', customers=customer_data)

@crm_bp.route('/customers/statement/<int:id>')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def statement(id):
    """Generates an auditable chronological sub-ledger account statement for a customer."""
    customer = Customer.query.get_or_404(id)
    from app.models import Ledger, VoucherEntry, Voucher
    
    ledger = Ledger.query.filter_by(name=customer.name).first()
    op_balance = 0.0
    op_type = 'Dr'
    if ledger:
        op_balance = ledger.opening_balance
        op_type = ledger.opening_balance_type
        ledger_items = VoucherEntry.query.filter_by(ledger_id=ledger.id).join(Voucher).order_by(Voucher.date.asc()).all()
    else:
        ledger_items = []
    
    balance = op_balance if op_type == 'Dr' else -op_balance
    statement_records = []
    for entry in ledger_items:
        debit = entry.amount if entry.entry_type == 'Dr' else 0.0
        credit = entry.amount if entry.entry_type == 'Cr' else 0.0
        balance += (debit - credit)
        
        desc = entry.voucher.narration or ""
        
        if entry.voucher.voucher_type == 'Sales' and entry.voucher.reference and entry.voucher.reference.startswith('INV-'):
            sale_id_str = entry.voucher.reference.replace('INV-', '')
            if sale_id_str.isdigit():
                from app.models import Sale
                sale = Sale.query.get(int(sale_id_str))
                if sale:
                    lines = [f"<strong>Sales Invoice #{sale.id}</strong>"]
                    for item in sale.items:
                        lines.append(f"<div style='font-size:0.9em;color:var(--text-secondary);'>• {item.product.name} ({item.quantity:g} qty &times; ₹{item.unit_price:,.2f}) = ₹{item.total_amount:,.2f}</div>")
                    desc = "".join(lines)
        elif entry.voucher.voucher_type == 'Receipt':
            desc = f"<strong>Payment Received</strong><br><span style='font-size:0.9em;color:var(--text-secondary);'>{desc}</span>"

        statement_records.append({
            'date': entry.voucher.date,
            'description': desc,
            'reference': f"{entry.voucher.voucher_type} #{entry.voucher.voucher_number}",
            'debit': debit,
            'credit': credit,
            'running_balance': balance
        })
        
    # Calculate total profit and discounts
    total_profit = 0.0
    total_discount = 0.0
    
    from app.models import Sale
    customer_sales = Sale.query.filter_by(customer_id=customer.id).all()
    for sale in customer_sales:
        total_discount += sale.discount_amount
        for item in sale.items:
            # Revenue from item (after global discount applied proportionally)
            # We know the total discount amount on the sale.
            # Discount per item = item.subtotal * sale.discount_percentage / 100.0
            item_discount = item.subtotal * (sale.discount_percentage / 100.0)
            item_revenue = item.subtotal - item_discount
            item_cost = item.unit_cost * item.quantity
            total_profit += (item_revenue - item_cost)

    return render_template('modules/crm/statement.html', customer=customer, records=statement_records, current_balance=balance, op_balance=op_balance, op_type=op_type, total_profit=total_profit, total_discount=total_discount)

@crm_bp.route('/customers/statement/<int:id>/print')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def print_statement(id):
    """Generates a print-ready chronological statement for a customer."""
    customer = Customer.query.get_or_404(id)
    from app.models import Ledger, VoucherEntry, Voucher
    
    ledger = Ledger.query.filter_by(name=customer.name).first()
    op_balance = 0.0
    op_type = 'Dr'
    if ledger:
        op_balance = ledger.opening_balance
        op_type = ledger.opening_balance_type
        ledger_items = VoucherEntry.query.filter_by(ledger_id=ledger.id).join(Voucher).order_by(Voucher.date.asc()).all()
    else:
        ledger_items = []
    
    balance = op_balance if op_type == 'Dr' else -op_balance
    statement_records = []
    for entry in ledger_items:
        debit = entry.amount if entry.entry_type == 'Dr' else 0.0
        credit = entry.amount if entry.entry_type == 'Cr' else 0.0
        balance += (debit - credit)
        
        desc = entry.voucher.narration or ""
        
        if entry.voucher.voucher_type == 'Sales' and entry.voucher.reference and entry.voucher.reference.startswith('INV-'):
            sale_id_str = entry.voucher.reference.replace('INV-', '')
            if sale_id_str.isdigit():
                from app.models import Sale
                sale = Sale.query.get(int(sale_id_str))
                if sale:
                    lines = [f"<strong>Sales Invoice #{sale.id}</strong>"]
                    for item in sale.items:
                        lines.append(f"<div style='font-size:0.9em;color:#444;'>&bull; {item.product.name} ({item.quantity:g} qty &times; ₹{item.unit_price:,.2f}) = ₹{item.total_amount:,.2f}</div>")
                    desc = "".join(lines)
        elif entry.voucher.voucher_type == 'Receipt':
            desc = f"<strong>Payment Received</strong><br><span style='font-size:0.9em;color:#444;'>{desc}</span>"

        statement_records.append({
            'date': entry.voucher.date,
            'description': desc,
            'vch_type': entry.voucher.voucher_type,
            'vch_no': entry.voucher.voucher_number,
            'debit': debit,
            'credit': credit,
            'running_balance': balance
        })
        
    # Calculate total profit and discounts
    total_profit = 0.0
    total_discount = 0.0
    
    from app.models import Sale
    customer_sales = Sale.query.filter_by(customer_id=customer.id).all()
    for sale in customer_sales:
        total_discount += sale.discount_amount
        for item in sale.items:
            item_discount = item.subtotal * (sale.discount_percentage / 100.0)
            item_revenue = item.subtotal - item_discount
            item_cost = item.unit_cost * item.quantity
            total_profit += (item_revenue - item_cost)

    return render_template('modules/crm/statement_print.html', customer=customer, records=statement_records, current_balance=balance, op_balance=op_balance, op_type=op_type, total_profit=total_profit, total_discount=total_discount)

@crm_bp.route('/customers/edit/<int:id>', methods=['POST'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def edit_customer(id):
    customer   = Customer.query.get_or_404(id)
    name       = (request.form.get('name')       or '').strip()
    phone      = (request.form.get('phone')      or '').strip()
    gst_number = (request.form.get('gst_number') or '').strip()
    address    = (request.form.get('address')    or '').strip()
    email      = (request.form.get('email')      or '').strip()
    op_bal     = float(request.form.get('opening_balance') or 0.0)
    op_type    = request.form.get('opening_balance_type', 'Dr')

    if not name:
        flash('Customer Name is required.', 'danger')
        return redirect(url_for('crm.list_customers'))

    old_name         = customer.name
    customer.name    = name
    customer.phone   = phone
    customer.gst_number = gst_number
    customer.address = address
    customer.email   = email

    from app.models import Ledger, AccountGroup
    ledger = Ledger.query.filter_by(name=old_name).first()
    if ledger:
        conflict = Ledger.query.filter(
            Ledger.name == name, Ledger.id != ledger.id
        ).first()
        if not conflict:
            ledger.name = name
        ledger.opening_balance      = op_bal
        ledger.opening_balance_type = op_type
    else:
        sd_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
        if sd_group and not Ledger.query.filter_by(name=name).first():
            new_ledger = Ledger(name=name, group_id=sd_group.id,
                                opening_balance=op_bal,
                                opening_balance_type=op_type)
            db.session.add(new_ledger)

    db.session.commit()
    flash(f'Customer "{name}" updated successfully.', 'success')
    return redirect(url_for('crm.list_customers'))

@crm_bp.route('/customers/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def delete_customer(id):
    customer = Customer.query.get_or_404(id)
    has_sales = Sale.query.filter_by(customer_id=id).first()
    has_ledger = LedgerEntry.query.filter_by(account_type='Customer', entity_id=id).first()

    if has_sales or has_ledger:
        flash(f'Cannot delete customer "{customer.name}" because they have associated transaction history.', 'danger')
        return redirect(url_for('crm.list_customers'))

    db.session.delete(customer)
    db.session.commit()
    flash(f'Customer "{customer.name}" deleted successfully.', 'success')
    return redirect(url_for('crm.list_customers'))