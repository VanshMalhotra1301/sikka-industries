from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Sale, SaleItem, Product, Customer, Voucher, VoucherEntry, Ledger, InventoryTransaction
from app.modules.sales import sales_bp
from app.utils.decorators import roles_required
from datetime import datetime
import uuid

COMPANY_STATE = "Delhi"

def get_ledger_by_name(name):
    return Ledger.query.filter_by(name=name).first()

@sales_bp.route('/register', methods=['GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def register():
    """Displays chronological registry historical logs of all issued sales invoices."""
    sales_records = Sale.query.order_by(Sale.date.desc()).all()
    return render_template('modules/sales/register.html', sales=sales_records)


@sales_bp.route('/entry', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant'])
def create_entry():
    """Validates warehouse availability, cuts new sales invoices, calculates GST, and posts financial Vouchers."""
    if request.method == 'POST':
        customer_id = int(request.form.get('customer_id'))
        payment_mode = request.form.get('payment_mode') # Cash, Bank, Credit
        paid_amount = float(request.form.get('paid_amount') or 0.0)
        bank_ledger_id = request.form.get('bank_ledger_id')
        
        # Real Date & Due Date
        sale_date_str = request.form.get('sale_date')
        due_date_str = request.form.get('due_date')
        
        sale_date = datetime.strptime(sale_date_str, '%Y-%m-%dT%H:%M') if sale_date_str else datetime.utcnow()
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d') if due_date_str else None
        
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')
        discount_percentage = float(request.form.get('discount_percentage') or 0.0)
        
        gst_treatment = request.form.get('gst_treatment', 'none') # 'none', 'manual', 'auto'
        manual_cgst = float(request.form.get('manual_cgst') or 0.0)
        manual_sgst = float(request.form.get('manual_sgst') or 0.0)
        manual_igst = float(request.form.get('manual_igst') or 0.0)

        if not product_ids or len(product_ids) == 0:
            flash('A sales invoice must contain at least one finished item line row.', 'danger')
            return redirect(url_for('sales.create_entry'))

        try:
            total_invoice_sum = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            total_igst = 0.0
            sales_items_buffer = []
            
            customer = Customer.query.get(customer_id)
            is_interstate = customer.state.lower() != COMPANY_STATE.lower()

            for idx in range(len(product_ids)):
                p_id = int(product_ids[idx])
                qty = float(quantities[idx])
                price = float(unit_prices[idx])
                subtotal = qty * price
                
                # Apply discount per item for tax calculation
                item_discount = subtotal * (discount_percentage / 100.0)
                discounted_subtotal = subtotal - item_discount
                
                product = Product.query.get(p_id)
                if not product:
                    flash('Selected product structural trace error.', 'danger')
                    return redirect(url_for('sales.create_entry'))
                
                if product.stock_quantity < qty:
                    flash(f'Stock Out Deficit! Insufficient items for [{product.code}] {product.name}. Available: {product.stock_quantity}', 'danger')
                    return redirect(url_for('sales.create_entry'))

                cgst = 0.0
                sgst = 0.0
                igst = 0.0
                
                if gst_treatment == 'auto':
                    tax_amount = discounted_subtotal * (product.gst_rate / 100.0)
                    if is_interstate:
                        igst = tax_amount
                    else:
                        cgst = tax_amount / 2.0
                        sgst = tax_amount / 2.0
                    
                total_cgst += cgst
                total_sgst += sgst
                total_igst += igst
                
                item_total = discounted_subtotal + cgst + sgst + igst
                total_invoice_sum += item_total
                
                item = SaleItem(
                    product_id=p_id,
                    quantity=qty,
                    unit_price=price,
                    unit_cost=product.purchase_cost,
                    subtotal=subtotal,
                    cgst_amount=cgst,
                    sgst_amount=sgst,
                    igst_amount=igst,
                    total_amount=item_total
                )
                sales_items_buffer.append((item, product))
                
            if gst_treatment == 'manual':
                total_cgst = manual_cgst
                total_sgst = manual_sgst
                total_igst = manual_igst
                total_invoice_sum += (total_cgst + total_sgst + total_igst)

            # Calculate total discount
            total_discount_amount = sum((i.subtotal * discount_percentage / 100.0) for i, p in sales_items_buffer)

            balance_receivable = total_invoice_sum - paid_amount

            new_sale = Sale(
                customer_id=customer_id,
                total_amount=total_invoice_sum,
                total_cgst=total_cgst,
                total_sgst=total_sgst,
                total_igst=total_igst,
                discount_percentage=discount_percentage,
                discount_amount=total_discount_amount,
                paid_amount=paid_amount,
                balance_amount=balance_receivable,
                payment_mode=payment_mode,
                date=sale_date,
                due_date=due_date
            )
            db.session.add(new_sale)
            db.session.flush()

            for item, product in sales_items_buffer:
                item.sale_id = new_sale.id
                db.session.add(item)
                product.stock_quantity -= item.quantity

                inv_log = InventoryTransaction(
                    product_id=product.id,
                    quantity=-item.quantity,
                    transaction_type='Sale',
                    reference_id=new_sale.id,
                    description=f"Issued to dealer via Invoice ID: #{new_sale.id}"
                )
                db.session.add(inv_log)

            # Tally Voucher Logic
            sales_ledger = get_ledger_by_name("Sales")
            cgst_ledger = get_ledger_by_name("CGST")
            sgst_ledger = get_ledger_by_name("SGST")
            igst_ledger = get_ledger_by_name("IGST")
            
            # 1. Sales Voucher (Accrual)
            # Create a customer ledger if not exists (In a real Tally, every customer is a ledger. Here we can map it dynamically or just create ledgers for customers)
            cust_ledger = get_ledger_by_name(customer.name)
            if not cust_ledger:
                from app.models import AccountGroup
                sd_group = AccountGroup.query.filter_by(name="Sundry Debtors").first()
                cust_ledger = Ledger(name=customer.name, group_id=sd_group.id)
                db.session.add(cust_ledger)
                db.session.flush()

            sv_number = f"SAL-{new_sale.id}-{uuid.uuid4().hex[:4].upper()}"
            sales_voucher = Voucher(
                voucher_type="Sales",
                voucher_number=sv_number,
                date=sale_date,
                narration=f"Goods sold to {customer.name}",
                reference=f"INV-{new_sale.id}",
                created_by=current_user.id if current_user else None
            )
            db.session.add(sales_voucher)
            db.session.flush()
            
            # Dr Customer
            db.session.add(VoucherEntry(voucher_id=sales_voucher.id, ledger_id=cust_ledger.id, entry_type='Dr', amount=total_invoice_sum))
            # Cr Sales
            db.session.add(VoucherEntry(voucher_id=sales_voucher.id, ledger_id=sales_ledger.id, entry_type='Cr', amount=(total_invoice_sum - total_cgst - total_sgst - total_igst)))
            # Cr Taxes
            if total_cgst > 0: db.session.add(VoucherEntry(voucher_id=sales_voucher.id, ledger_id=cgst_ledger.id, entry_type='Cr', amount=total_cgst))
            if total_sgst > 0: db.session.add(VoucherEntry(voucher_id=sales_voucher.id, ledger_id=sgst_ledger.id, entry_type='Cr', amount=total_sgst))
            if total_igst > 0: db.session.add(VoucherEntry(voucher_id=sales_voucher.id, ledger_id=igst_ledger.id, entry_type='Cr', amount=total_igst))

            # 2. Receipt Voucher (if payment made)
            if paid_amount > 0:
                rv_number = f"REC-{new_sale.id}-{uuid.uuid4().hex[:4].upper()}"
                receipt_voucher = Voucher(
                    voucher_type="Receipt",
                    voucher_number=rv_number,
                    date=sale_date,
                    narration=f"Payment received from {customer.name}",
                    reference=f"INV-{new_sale.id}",
                    created_by=current_user.id if current_user else None
                )
                db.session.add(receipt_voucher)
                db.session.flush()
                
                if payment_mode == 'Bank' and bank_ledger_id:
                    asset_ledger = Ledger.query.get(bank_ledger_id)
                else:
                    asset_ledger = get_ledger_by_name("Cash")
                
                if not asset_ledger:
                    asset_ledger = Ledger.query.filter(Ledger.name.like('%Cash%')).first()
                    
                # Dr Asset
                db.session.add(VoucherEntry(voucher_id=receipt_voucher.id, ledger_id=asset_ledger.id, entry_type='Dr', amount=paid_amount))
                # Cr Customer
                db.session.add(VoucherEntry(voucher_id=receipt_voucher.id, ledger_id=cust_ledger.id, entry_type='Cr', amount=paid_amount))

            db.session.commit()
            flash(f'Sales Invoice #{new_sale.id} issued successfully with GST calculated. Ledgers posted.', 'success')
            return redirect(url_for('sales.register'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error processing sales transaction: {str(e)}', 'danger')
            return redirect(url_for('sales.create_entry'))

    customers = Customer.query.order_by(Customer.name.asc()).all()
    finished_motors = Product.query.filter_by(category='Finished Goods').order_by(Product.code.asc()).all()
    
    from app.models import AccountGroup
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    
    return render_template('modules/sales/entry.html', customers=customers, products=finished_motors, bank_ledgers=bank_ledgers)

@sales_bp.route('/invoice/<int:id>', methods=['GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def view_invoice(id):
    """Renders a clean, print-ready document invoice layout."""
    sale = Sale.query.get_or_404(id)
    return render_template('modules/sales/invoice_print.html', sale=sale)

@sales_bp.route('/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin'])
def delete_sale(id):
    sale = Sale.query.get_or_404(id)
    try:
        # Reverse stock level updates
        for item in sale.items:
            product = Product.query.get(item.product_id)
            if product:
                product.stock_quantity += item.quantity
            
        inv_txs = InventoryTransaction.query.filter_by(reference_id=id, transaction_type='Sale').all()
        for tx in inv_txs:
            db.session.delete(tx)

        vouchers = Voucher.query.filter_by(reference=f"INV-{id}").all()
        for v in vouchers:
            db.session.delete(v)

        for item in sale.items:
            db.session.delete(item)

        db.session.delete(sale)
        db.session.commit()
        
        flash(f'Sales Invoice #{id} deleted successfully. Vouchers reversed.', 'success')
        return redirect(url_for('sales.register'))
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete Sales Invoice: {str(e)}', 'danger')
        return redirect(url_for('sales.register'))