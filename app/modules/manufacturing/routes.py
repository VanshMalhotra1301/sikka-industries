from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import ProductionRun, ProductionConsumption, Product, InventoryTransaction
from app.modules.manufacturing import manufacturing_bp
from app.utils.decorators import roles_required
from datetime import datetime

@manufacturing_bp.route('/logs', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Store Manager', 'Owner'])
def production_logs():
    """Handles manufacturing batch records and processes raw-to-finished assemblies."""
    if request.method == 'POST':
        finished_product_id = int(request.form.get('finished_product_id'))
        quantity_produced = float(request.form.get('quantity_produced') or 0.0)
        
        # Capture raw components consumed from dynamic form arrays
        raw_material_ids = request.form.getlist('raw_material_id[]')
        quantities_consumed = request.form.getlist('quantity_consumed[]')

        if quantity_produced <= 0 or not raw_material_ids:
            flash('Production quantity must exceed zero and require component consumption mapping.', 'danger')
            return redirect(url_for('manufacturing.production_logs'))

        try:
            consumption_buffer = []

            # Phase 1: Verify raw material balances before making any modifications
            for idx in range(len(raw_material_ids)):
                rm_id = int(raw_material_ids[idx])
                qty_req = float(quantities_consumed[idx])
                
                raw_item = Product.query.get(rm_id)
                if not raw_item:
                    flash('Selected raw component lookup tracing error.', 'danger')
                    return redirect(url_for('manufacturing.production_logs'))
                
                # Check for component shortages
                if raw_item.stock_quantity < qty_req:
                    flash(f'Material Shortage! Insufficient stock for [{raw_item.code}] {raw_item.name}. Available: {raw_item.stock_quantity}, Required: {qty_req}', 'danger')
                    return redirect(url_for('manufacturing.production_logs'))

                consumption_buffer.append((raw_item, qty_req))

            # Phase 2: Record Master Production Batch Order
            new_run = ProductionRun(
                finished_product_id=finished_product_id,
                quantity_produced=quantity_produced,
                logged_by=current_user.id,
                date=datetime.utcnow()
            )
            db.session.add(new_run)
            db.session.flush() # Safely acquire production batch identifier sequence

            # Phase 3: Deduct components from stock and write audit trails
            for raw_item, qty_req in consumption_buffer:
                # Store line-item child record
                consumption_entry = ProductionConsumption(
                    production_run_id=new_run.id,
                    raw_material_id=raw_item.id,
                    quantity_consumed=qty_req
                )
                db.session.add(consumption_entry)

                # Deduct from raw stock
                raw_item.stock_quantity -= qty_req

                # Log physical inventory movement
                raw_tx = InventoryTransaction(
                    product_id=raw_item.id,
                    quantity=-qty_req,
                    transaction_type='Consumption',
                    reference_id=new_run.id,
                    description=f"Consumed in batch run: #{new_run.id} for motor assembly."
                )
                db.session.add(raw_tx)

            # Phase 4: Increase Finished Goods Stock
            finished_motor = Product.query.get(finished_product_id)
            finished_motor.stock_quantity += quantity_produced

            # Log production output to inventory ledger
            fg_tx = InventoryTransaction(
                product_id=finished_motor.id,
                quantity=quantity_produced,
                transaction_type='Production',
                reference_id=new_run.id,
                description=f"Assembled and logged on factory floor under Batch Run Reference: #{new_run.id}"
            )
            db.session.add(fg_tx)

            db.session.commit()
            flash(f'Production batch run #{new_run.id} logged. Finished motor stock updated successfully.', 'success')
            return redirect(url_for('manufacturing.production_logs'))

        except Exception as e:
            db.session.rollback()
            flash(f'An exception derailed production tracking logs: {str(e)}', 'danger')
            return redirect(url_for('manufacturing.production_logs'))

    # Load master records for template select configurations
    runs = ProductionRun.query.order_by(ProductionRun.date.desc()).all()
    finished_goods = Product.query.filter_by(category='Finished Goods').order_by(Product.code.asc()).all()
    raw_materials = Product.query.filter_by(category='Raw Material').order_by(Product.code.asc()).all()
    
    return render_template(
        'modules/manufacturing/production_log.html',
        runs=runs,
        finished_goods=finished_goods,
        raw_materials=raw_materials
    )

@manufacturing_bp.route('/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin', 'Store Manager'])
def delete_production_run(id):
    run = ProductionRun.query.get_or_404(id)
    try:
        # Reverse finished goods stock
        finished_product = Product.query.get(run.finished_product_id)
        if finished_product:
            finished_product.stock_quantity -= run.quantity_produced

        # Reverse raw materials stock
        for consumption in run.consumptions:
            raw_material = Product.query.get(consumption.raw_material_id)
            if raw_material:
                raw_material.stock_quantity += consumption.quantity_consumed

        # Delete associated inventory transactions
        inv_txs = InventoryTransaction.query.filter(
            InventoryTransaction.reference_id == id,
            InventoryTransaction.transaction_type.in_(['Production', 'Consumption'])
        ).all()
        for tx in inv_txs:
            db.session.delete(tx)

        # Delete consumption child rows
        for consumption in run.consumptions:
            db.session.delete(consumption)

        # Delete production run master
        db.session.delete(run)
        db.session.commit()

        flash(f'Production Run #{id} deleted successfully. Finished stock and raw component levels reverted.', 'success')
        return redirect(url_for('manufacturing.production_logs'))
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete Production Run: {str(e)}', 'danger')
        return redirect(url_for('manufacturing.production_logs'))
