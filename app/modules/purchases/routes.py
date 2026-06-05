from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Purchase, PurchaseItem, Product, Supplier, Voucher, VoucherEntry, Ledger, InventoryTransaction
from app.modules.purchases import purchases_bp
from app.utils.decorators import roles_required
from datetime import datetime
import uuid

COMPANY_STATE = "Delhi"

def get_ledger_by_name(name):
    return Ledger.query.filter_by(name=name).first()

@purchases_bp.route('/register', methods=['GET'])
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def register():
    """Displays chronological registry historical logs of all received item bills."""
    purchase_records = Purchase.query.order_by(Purchase.date.desc()).all()
    return render_template('modules/purchases/register.html', purchases=purchase_records)


@purchases_bp.route('/entry', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Accountant'])
def create_entry():
    """Processes physical item arrivals, calculates GST, and posts financial Vouchers."""
    if request.method == 'POST':
        supplier_id = int(request.form.get('supplier_id'))
        payment_mode = request.form.get('payment_mode') # Cash, Bank, Credit
        paid_amount = float(request.form.get('paid_amount') or 0.0)
        bank_ledger_id = request.form.get('bank_ledger_id')
        
        purchase_date_str = request.form.get('purchase_date')
        due_date_str = request.form.get('due_date')
        
        purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%dT%H:%M') if purchase_date_str else datetime.utcnow()
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d') if due_date_str else None
        
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        unit_costs = request.form.getlist('unit_cost[]')
        
        gst_treatment = request.form.get('gst_treatment', 'none') # 'none', 'manual', 'auto'
        manual_cgst = float(request.form.get('manual_cgst') or 0.0)
        manual_sgst = float(request.form.get('manual_sgst') or 0.0)
        manual_igst = float(request.form.get('manual_igst') or 0.0)

        if not product_ids or len(product_ids) == 0:
            flash('A purchase entry must contain at least one line item.', 'danger')
            return redirect(url_for('purchases.create_entry'))

        try:
            total_invoice_sum = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            total_igst = 0.0
            purchase_items_buffer = []
            
            supplier = Supplier.query.get(supplier_id)
            is_interstate = supplier.state.lower() != COMPANY_STATE.lower()

            for idx in range(len(product_ids)):
                p_id = int(product_ids[idx])
                qty = float(quantities[idx])
                cost = float(unit_costs[idx])
                subtotal = qty * cost
                
                product = Product.query.get(p_id)
                
                cgst = 0.0
                sgst = 0.0
                igst = 0.0
                
                if gst_treatment == 'auto':
                    tax_amount = subtotal * (product.gst_rate / 100.0)
                    if is_interstate:
                        igst = tax_amount
                    else:
                        cgst = tax_amount / 2.0
                        sgst = tax_amount / 2.0
                    
                total_cgst += cgst
                total_sgst += sgst
                total_igst += igst
                
                item_total = subtotal + cgst + sgst + igst
                total_invoice_sum += item_total
                
                item = PurchaseItem(
                    product_id=p_id,
                    quantity=qty,
                    unit_cost=cost,
                    subtotal=subtotal,
                    cgst_amount=cgst,
                    sgst_amount=sgst,
                    igst_amount=igst,
                    total_amount=item_total
                )
                purchase_items_buffer.append((item, product))
                
            if gst_treatment == 'manual':
                total_cgst = manual_cgst
                total_sgst = manual_sgst
                total_igst = manual_igst
                total_invoice_sum += (total_cgst + total_sgst + total_igst)

            balance_outstanding = total_invoice_sum - paid_amount

            new_purchase = Purchase(
                supplier_id=supplier_id,
                total_amount=total_invoice_sum,
                total_cgst=total_cgst,
                total_sgst=total_sgst,
                total_igst=total_igst,
                paid_amount=paid_amount,
                balance_amount=balance_outstanding,
                payment_mode=payment_mode,
                date=purchase_date,
                due_date=due_date
            )
            db.session.add(new_purchase)
            db.session.flush()

            for item, product in purchase_items_buffer:
                item.purchase_id = new_purchase.id
                db.session.add(item)
                
                product.stock_quantity += item.quantity
                product.purchase_cost = item.unit_cost

                inv_log = InventoryTransaction(
                    product_id=product.id,
                    quantity=item.quantity,
                    transaction_type='Purchase',
                    reference_id=new_purchase.id,
                    description=f"Procured from supplier via Bill Reference ID: #{new_purchase.id}"
                )
                db.session.add(inv_log)

            # Tally Voucher Logic
            purchase_ledger = get_ledger_by_name("Purchases")
            cgst_ledger = get_ledger_by_name("CGST")
            sgst_ledger = get_ledger_by_name("SGST")
            igst_ledger = get_ledger_by_name("IGST")
            
            # 1. Purchase Voucher (Accrual)
            supp_ledger = get_ledger_by_name(supplier.name)
            if not supp_ledger:
                from app.models import AccountGroup
                sc_group = AccountGroup.query.filter_by(name="Sundry Creditors").first()
                supp_ledger = Ledger(name=supplier.name, group_id=sc_group.id)
                db.session.add(supp_ledger)
                db.session.flush()

            pv_number = f"PUR-{new_purchase.id}-{uuid.uuid4().hex[:4].upper()}"
            purchase_voucher = Voucher(
                voucher_type="Purchase",
                voucher_number=pv_number,
                date=purchase_date,
                narration=f"Materials purchased from {supplier.name}",
                reference=f"BILL-{new_purchase.id}",
                created_by=current_user.id if current_user else None
            )
            db.session.add(purchase_voucher)
            db.session.flush()
            
            # Cr Supplier
            db.session.add(VoucherEntry(voucher_id=purchase_voucher.id, ledger_id=supp_ledger.id, entry_type='Cr', amount=total_invoice_sum))
            # Dr Purchase
            db.session.add(VoucherEntry(voucher_id=purchase_voucher.id, ledger_id=purchase_ledger.id, entry_type='Dr', amount=(total_invoice_sum - total_cgst - total_sgst - total_igst)))
            # Dr Taxes
            if total_cgst > 0: db.session.add(VoucherEntry(voucher_id=purchase_voucher.id, ledger_id=cgst_ledger.id, entry_type='Dr', amount=total_cgst))
            if total_sgst > 0: db.session.add(VoucherEntry(voucher_id=purchase_voucher.id, ledger_id=sgst_ledger.id, entry_type='Dr', amount=total_sgst))
            if total_igst > 0: db.session.add(VoucherEntry(voucher_id=purchase_voucher.id, ledger_id=igst_ledger.id, entry_type='Dr', amount=total_igst))

            # 2. Payment Voucher (if payment made)
            if paid_amount > 0:
                pmv_number = f"PAY-{new_purchase.id}-{uuid.uuid4().hex[:4].upper()}"
                payment_voucher = Voucher(
                    voucher_type="Payment",
                    voucher_number=pmv_number,
                    date=purchase_date,
                    narration=f"Payment disbursed to {supplier.name}",
                    reference=f"BILL-{new_purchase.id}",
                    created_by=current_user.id if current_user else None
                )
                db.session.add(payment_voucher)
                db.session.flush()
                
                if payment_mode == 'Bank' and bank_ledger_id:
                    asset_ledger = Ledger.query.get(bank_ledger_id)
                else:
                    asset_ledger = get_ledger_by_name("Cash")
                
                if not asset_ledger:
                    asset_ledger = Ledger.query.filter(Ledger.name.like('%Cash%')).first()
                    
                # Cr Asset
                db.session.add(VoucherEntry(voucher_id=payment_voucher.id, ledger_id=asset_ledger.id, entry_type='Cr', amount=paid_amount))
                # Dr Supplier
                db.session.add(VoucherEntry(voucher_id=payment_voucher.id, ledger_id=supp_ledger.id, entry_type='Dr', amount=paid_amount))

            db.session.commit()
            flash(f'Purchase Bill #{new_purchase.id} logged successfully with GST. Ledgers balanced.', 'success')
            return redirect(url_for('purchases.register'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error processing purchase transaction: {str(e)}', 'danger')
            return redirect(url_for('purchases.create_entry'))

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    raw_materials = Product.query.filter_by(category='Raw Material').order_by(Product.code.asc()).all()
    
    from app.models import AccountGroup
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    
    return render_template('modules/purchases/entry.html', suppliers=suppliers, materials=raw_materials, bank_ledgers=bank_ledgers)

@purchases_bp.route('/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin', 'Accountant'])
def delete_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    try:
        for item in purchase.items:
            product = Product.query.get(item.product_id)
            if product:
                product.stock_quantity -= item.quantity

        inv_txs = InventoryTransaction.query.filter_by(reference_id=id, transaction_type='Purchase').all()
        for tx in inv_txs:
            db.session.delete(tx)

        vouchers = Voucher.query.filter_by(reference=f"BILL-{id}").all()
        for v in vouchers:
            db.session.delete(v)

        for item in purchase.items:
            db.session.delete(item)

        db.session.delete(purchase)
        db.session.commit()

        flash(f'Purchase Bill #{id} deleted successfully. Vouchers reversed.', 'success')
        return redirect(url_for('purchases.register'))
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete Purchase Bill: {str(e)}', 'danger')
        return redirect(url_for('purchases.register'))