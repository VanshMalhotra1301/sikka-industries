from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Product, InventoryTransaction, SaleItem, PurchaseItem, ProductionConsumption, ProductionRun
from app.modules.inventory import inventory_bp
from app.utils.decorators import roles_required

@inventory_bp.route('/raw-materials', methods=['GET'])
@login_required
@roles_required(['Admin', 'Store Manager', 'Accountant', 'Owner'])
def raw_materials():
    """Renders the dedicated Raw Materials inventory hub."""
    products = Product.query.filter_by(category='Raw Material').order_by(Product.code.asc()).all()
    return render_template('modules/inventory/raw_materials.html', products=products)

@inventory_bp.route('/finished-goods', methods=['GET'])
@login_required
@roles_required(['Admin', 'Store Manager', 'Accountant', 'Owner'])
def finished_goods():
    """Renders the dedicated Finished Goods inventory hub."""
    products = Product.query.filter_by(category='Finished Goods').order_by(Product.code.asc()).all()
    return render_template('modules/inventory/finished_goods.html', products=products)

@inventory_bp.route('/products/add', methods=['POST'])
@login_required
@roles_required(['Admin', 'Store Manager', 'Accountant', 'Owner'])
def add_product():
    """Inserts new stock lines and redirects to the correct hub."""
    code = request.form.get('code').strip().upper()
    name = request.form.get('name').strip()
    category = request.form.get('category')
    selling_price = float(request.form.get('selling_price') or 0.0)
    purchase_cost = float(request.form.get('purchase_cost') or 0.0)
    initial_stock = float(request.form.get('initial_stock') or 0.0)
    low_stock_threshold = float(request.form.get('low_stock_threshold') or 10.0)

    redirect_url = url_for('inventory.raw_materials') if category == 'Raw Material' else url_for('inventory.finished_goods')

    # Structural Guardrails
    if not code or not name or not category:
        flash('Product Code, Name, and Category are strictly required fields.', 'danger')
        return redirect(redirect_url)

    existing_product = Product.query.filter_by(code=code).first()
    if existing_product:
        flash(f'Product Code "{code}" is already assigned to an item.', 'danger')
        return redirect(redirect_url)

    # Create Product Entry
    new_product = Product(
        code=code, name=name, category=category,
        selling_price=selling_price, purchase_cost=purchase_cost,
        stock_quantity=initial_stock, low_stock_threshold=low_stock_threshold
    )
    db.session.add(new_product)
    db.session.flush() # Extract database ID safely before commit to apply initial logs

    # Write Initial Audit Log if initial inventory balance is configured
    if initial_stock > 0:
        initial_tx = InventoryTransaction(
            product_id=new_product.id,
            quantity=initial_stock,
            transaction_type='Adjustment',
            description='Initial inventory baseline seed configuration.'
        )
        db.session.add(initial_tx)

    db.session.commit()
    flash(f'Product [{code}] {name} has been added to warehouse directories.', 'success')
    return redirect(redirect_url)


@inventory_bp.route('/adjust', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Store Manager'])
def adjust_stock():
    """Executes a manual stock reconciliation entry with audit logging."""
    if request.method == 'POST':
        product_id = int(request.form.get('product_id'))
        delta_quantity = float(request.form.get('quantity'))  # Positive for adding, negative for reducing
        description = request.form.get('description').strip()

        if delta_quantity == 0:
            flash('Adjustment delta cannot be zero.', 'warning')
            return redirect(url_for('inventory.adjust_stock'))

        product = Product.query.get_or_404(product_id)
        
        # Guard against drawing inventory below zero levels
        if product.stock_quantity + delta_quantity < 0:
            flash(f'Insufficient stock. Cannot reduce inventory level below 0. Current: {product.stock_quantity}', 'danger')
            return redirect(url_for('inventory.adjust_stock'))

        # Execute updates safely inside database transaction boundaries
        product.stock_quantity += delta_quantity
        tx_log = InventoryTransaction(
            product_id=product.id,
            quantity=delta_quantity,
            transaction_type='Adjustment',
            description=description or f"Manual update initiated by user: {current_user.username}"
        )
        db.session.add(tx_log)
        db.session.commit()

        flash(f'Stock level for {product.name} successfully updated.', 'success')
        redirect_url = url_for('inventory.raw_materials') if product.category == 'Raw Material' else url_for('inventory.finished_goods')
        return redirect(redirect_url)

    products = Product.query.order_by(Product.code.asc()).all()
    return render_template('modules/inventory/adjustments.html', products=products)


@inventory_bp.route('/ledger/<int:product_id>')
@login_required
@roles_required(['Admin', 'Store Manager', 'Accountant', 'Owner'])
def view_ledger(product_id):
    """Generates an audit trail of physical warehouse transactions for an item."""
    product = Product.query.get_or_404(product_id)
    logs = InventoryTransaction.query.filter_by(product_id=product_id).order_by(InventoryTransaction.date.desc()).all()
    return render_template('modules/inventory/ledger.html', product=product, logs=logs)

@inventory_bp.route('/products/edit/<int:id>', methods=['POST'])
@login_required
@roles_required(['Admin'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    code = request.form.get('code').strip().upper()
    name = request.form.get('name').strip()
    category = request.form.get('category')
    selling_price = float(request.form.get('selling_price') or 0.0)
    purchase_cost = float(request.form.get('purchase_cost') or 0.0)
    low_stock_threshold = float(request.form.get('low_stock_threshold') or 10.0)

    redirect_url = url_for('inventory.raw_materials') if product.category == 'Raw Material' else url_for('inventory.finished_goods')

    if not code or not name or not category:
        flash('Product Code, Name, and Category are required.', 'danger')
        return redirect(redirect_url)

    if code != product.code:
        existing = Product.query.filter_by(code=code).first()
        if existing:
            flash(f'Product Code "{code}" is already assigned to another item.', 'danger')
            return redirect(redirect_url)

    product.code = code
    product.name = name
    product.category = category
    product.selling_price = selling_price
    product.purchase_cost = purchase_cost
    product.low_stock_threshold = low_stock_threshold
    db.session.commit()
    
    redirect_url = url_for('inventory.raw_materials') if product.category == 'Raw Material' else url_for('inventory.finished_goods')
    flash(f'Product [{code}] {name} updated successfully.', 'success')
    return redirect(redirect_url)

@inventory_bp.route('/products/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@roles_required(['Admin'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    has_sales = SaleItem.query.filter_by(product_id=id).first()
    has_purchases = PurchaseItem.query.filter_by(product_id=id).first()
    has_consumption = ProductionConsumption.query.filter_by(raw_material_id=id).first()
    has_production = ProductionRun.query.filter_by(finished_product_id=id).first()
    
    other_tx = InventoryTransaction.query.filter(
        InventoryTransaction.product_id == id,
        InventoryTransaction.transaction_type != 'Adjustment'
    ).first()

    redirect_url = url_for('inventory.raw_materials') if product.category == 'Raw Material' else url_for('inventory.finished_goods')

    if has_sales or has_purchases or has_consumption or has_production or other_tx:
        flash(f'Cannot delete product [{product.code}] because it has associated inventory or transaction history.', 'danger')
        return redirect(redirect_url)

    initial_txs = InventoryTransaction.query.filter_by(product_id=id).all()
    for tx in initial_txs:
        db.session.delete(tx)

    db.session.delete(product)
    db.session.commit()
    flash(f'Product [{product.code}] {product.name} deleted successfully.', 'success')
    return redirect(redirect_url)
    