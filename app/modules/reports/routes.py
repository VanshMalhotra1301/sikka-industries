from flask import render_template, send_file, flash, redirect, url_for, request, jsonify
from flask_login import login_required
from sqlalchemy import func, cast, Date, extract
from app import db
from app.models import (
    Sale, SaleItem, Product, Customer, Supplier, Purchase, PurchaseItem,
    ProductionRun, ProductionConsumption, InventoryTransaction,
    AccountGroup, Ledger, Voucher, VoucherEntry
)
from app.modules.reports import reports_bp
from app.utils.decorators import roles_required
import datetime
from collections import defaultdict

# ──────────────────────────────────────────────────────────────────────────────
# ANALYTICS HUB — Page render
# ──────────────────────────────────────────────────────────────────────────────
@reports_bp.route('/hub')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def analytics_hub():
    """Renders the premium BI Analytics Hub page."""
    return render_template('modules/reports/analytics_hub.html')


# ──────────────────────────────────────────────────────────────────────────────
# ANALYTICS DATA — JSON API (AJAX)
# ──────────────────────────────────────────────────────────────────────────────
@reports_bp.route('/analytics-data')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def analytics_data():
    """
    Comprehensive JSON analytics endpoint.
    Accepts ?start=YYYY-MM-DD&end=YYYY-MM-DD for date-range filtering.
    Returns all KPIs, trends, and distributions.
    """
    # Parse date range
    today = datetime.date.today()
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else today.replace(month=1, day=1)
    except Exception:
        start_date = today.replace(month=1, day=1)
    try:
        end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today
    except Exception:
        end_date = today

    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)

    try:
        data = {}

        # ── BI WIDGETS ────────────────────────────────────────────────────────
        data['widgets'] = _compute_widgets(start_dt, end_dt)

        # ── FINANCIAL ─────────────────────────────────────────────────────────
        data['financial'] = _compute_financial(start_dt, end_dt)

        # ── SALES ─────────────────────────────────────────────────────────────
        data['sales'] = _compute_sales(start_dt, end_dt)

        # ── PURCHASES ─────────────────────────────────────────────────────────
        data['purchases'] = _compute_purchases(start_dt, end_dt)

        # ── INVENTORY ─────────────────────────────────────────────────────────
        data['inventory'] = _compute_inventory()

        # ── MANUFACTURING ─────────────────────────────────────────────────────
        data['manufacturing'] = _compute_manufacturing(start_dt, end_dt)

        # ── CASH FLOW ─────────────────────────────────────────────────────────
        data['cashflow'] = _compute_cashflow(start_dt, end_dt)

        return jsonify(data)

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _month_labels(start_dt, end_dt):
    """Generate list of month labels between two dates."""
    labels = []
    current = start_dt.replace(day=1)
    end_month = end_dt.replace(day=1)
    while current <= end_month:
        labels.append(current.strftime('%b %Y'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return labels

def _month_key(dt):
    return dt.strftime('%b %Y')


def _compute_widgets(start_dt, end_dt):
    """Top-level BI widget cards."""
    # Top product by revenue
    top_product = db.session.query(
        Product.name, func.sum(SaleItem.total_amount).label('rev')
    ).join(SaleItem).join(Sale).filter(
        Sale.date.between(start_dt, end_dt)
    ).group_by(Product.id).order_by(func.sum(SaleItem.total_amount).desc()).first()

    # Top customer by revenue
    top_customer = db.session.query(
        Customer.name, func.sum(Sale.total_amount).label('rev')
    ).join(Sale).filter(
        Sale.date.between(start_dt, end_dt)
    ).group_by(Customer.id).order_by(func.sum(Sale.total_amount).desc()).first()

    # Top supplier by purchase value
    top_supplier = db.session.query(
        Supplier.name, func.sum(Purchase.total_amount).label('val')
    ).join(Purchase).filter(
        Purchase.date.between(start_dt, end_dt)
    ).group_by(Supplier.id).order_by(func.sum(Purchase.total_amount).desc()).first()

    # Most profitable product
    most_profitable = db.session.query(
        Product.name,
        func.sum((SaleItem.unit_price - SaleItem.unit_cost) * SaleItem.quantity).label('profit')
    ).join(SaleItem).join(Sale).filter(
        Sale.date.between(start_dt, end_dt)
    ).group_by(Product.id).order_by(
        func.sum((SaleItem.unit_price - SaleItem.unit_cost) * SaleItem.quantity).desc()
    ).first()

    # Total sales & purchases for period
    total_sales = db.session.query(func.coalesce(func.sum(Sale.total_amount), 0.0)).filter(
        Sale.date.between(start_dt, end_dt)).scalar()
    total_purchases = db.session.query(func.coalesce(func.sum(Purchase.total_amount), 0.0)).filter(
        Purchase.date.between(start_dt, end_dt)).scalar()

    # Total expenses (excluding Purchase Accounts)
    expense_groups = AccountGroup.query.filter(
        AccountGroup.nature == 'Expense', AccountGroup.name != 'Purchase Accounts'
    ).all()
    expense_group_ids = [g.id for g in expense_groups]
    expense_ledgers = Ledger.query.filter(Ledger.group_id.in_(expense_group_ids)).all() if expense_group_ids else []
    expense_ledger_ids = [l.id for l in expense_ledgers]

    total_expenses = 0.0
    if expense_ledger_ids:
        exp_dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(expense_ledger_ids), VoucherEntry.entry_type == 'Dr',
            Voucher.date.between(start_dt, end_dt)).scalar()
        exp_cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(expense_ledger_ids), VoucherEntry.entry_type == 'Cr',
            Voucher.date.between(start_dt, end_dt)).scalar()
        total_expenses = exp_dr - exp_cr

    # Receivables & Payables (overall, not date-filtered)
    receivables = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).scalar()
    payables = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).scalar()

    # Gross profit
    gross_profit = 0.0
    sale_items = db.session.query(SaleItem).join(Sale).filter(Sale.date.between(start_dt, end_dt)).all()
    for item in sale_items:
        gross_profit += (item.subtotal or 0.0) - (item.quantity * (item.unit_cost or 0.0))

    # Stock value
    stock_value = db.session.query(
        func.coalesce(func.sum(Product.stock_quantity * Product.purchase_cost), 0.0)
    ).scalar()

    # Business health score (composite 0-100)
    health = 50  # baseline
    if total_sales > 0:
        profit_margin = (gross_profit / total_sales) * 100
        health = min(100, max(0, int(50 + profit_margin)))
    if receivables > total_sales * 0.5:
        health = max(0, health - 10)
    low_stock = Product.query.filter(Product.stock_quantity <= Product.low_stock_threshold).count()
    if low_stock > 5:
        health = max(0, health - 10)

    return {
        'total_sales': round(total_sales, 2),
        'total_purchases': round(total_purchases, 2),
        'total_expenses': round(total_expenses, 2),
        'gross_profit': round(gross_profit, 2),
        'receivables': round(receivables, 2),
        'payables': round(payables, 2),
        'stock_value': round(stock_value, 2),
        'top_product': {'name': top_product[0] if top_product else 'N/A', 'value': round(top_product[1], 2) if top_product else 0},
        'top_customer': {'name': top_customer[0] if top_customer else 'N/A', 'value': round(top_customer[1], 2) if top_customer else 0},
        'top_supplier': {'name': top_supplier[0] if top_supplier else 'N/A', 'value': round(top_supplier[1], 2) if top_supplier else 0},
        'most_profitable': {'name': most_profitable[0] if most_profitable else 'N/A', 'value': round(most_profitable[1], 2) if most_profitable else 0},
        'health_score': health,
        'low_stock_count': low_stock,
    }


def _compute_financial(start_dt, end_dt):
    """Monthly financial trends."""
    labels = _month_labels(start_dt, end_dt)

    # Revenue by month
    revenue = defaultdict(float)
    sales_in_range = Sale.query.filter(Sale.date.between(start_dt, end_dt)).all()
    for s in sales_in_range:
        revenue[_month_key(s.date)] += s.total_amount or 0.0

    # Profit by month (gross)
    profit = defaultdict(float)
    items_in_range = db.session.query(SaleItem).join(Sale).filter(Sale.date.between(start_dt, end_dt)).all()
    for item in items_in_range:
        sale = item.sale
        profit[_month_key(sale.date)] += (item.subtotal or 0.0) - (item.quantity * (item.unit_cost or 0.0))

    # Expenses by month
    expense_groups = AccountGroup.query.filter(
        AccountGroup.nature == 'Expense', AccountGroup.name != 'Purchase Accounts'
    ).all()
    exp_group_ids = [g.id for g in expense_groups]
    exp_ledgers = Ledger.query.filter(Ledger.group_id.in_(exp_group_ids)).all() if exp_group_ids else []
    exp_ledger_ids = [l.id for l in exp_ledgers]

    expenses_monthly = defaultdict(float)
    if exp_ledger_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(exp_ledger_ids),
            Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            key = _month_key(v.date)
            if ve.entry_type == 'Dr':
                expenses_monthly[key] += ve.amount
            else:
                expenses_monthly[key] -= ve.amount

    # Purchases by month
    purchases_monthly = defaultdict(float)
    purchases_in_range = Purchase.query.filter(Purchase.date.between(start_dt, end_dt)).all()
    for p in purchases_in_range:
        purchases_monthly[_month_key(p.date)] += p.total_amount or 0.0

    return {
        'labels': labels,
        'revenue': [round(revenue.get(l, 0), 2) for l in labels],
        'profit': [round(profit.get(l, 0), 2) for l in labels],
        'expenses': [round(expenses_monthly.get(l, 0), 2) for l in labels],
        'purchases': [round(purchases_monthly.get(l, 0), 2) for l in labels],
    }


def _compute_sales(start_dt, end_dt):
    """Sales analytics."""
    labels = _month_labels(start_dt, end_dt)

    # Monthly sales
    monthly = defaultdict(float)
    sales = Sale.query.filter(Sale.date.between(start_dt, end_dt)).all()
    for s in sales:
        monthly[_month_key(s.date)] += s.total_amount or 0.0

    # Product-wise revenue (top 10)
    product_rev = db.session.query(
        Product.name, func.sum(SaleItem.total_amount).label('rev')
    ).join(SaleItem).join(Sale).filter(
        Sale.date.between(start_dt, end_dt)
    ).group_by(Product.id).order_by(func.sum(SaleItem.total_amount).desc()).limit(10).all()

    # Customer-wise revenue (top 10)
    customer_rev = db.session.query(
        Customer.name, func.sum(Sale.total_amount).label('rev')
    ).join(Sale).filter(
        Sale.date.between(start_dt, end_dt)
    ).group_by(Customer.id).order_by(func.sum(Sale.total_amount).desc()).limit(10).all()

    # Payment mode distribution
    payment_dist = db.session.query(
        Sale.payment_mode, func.sum(Sale.total_amount)
    ).filter(Sale.date.between(start_dt, end_dt)).group_by(Sale.payment_mode).all()

    return {
        'labels': labels,
        'monthly': [round(monthly.get(l, 0), 2) for l in labels],
        'product_revenue': {
            'labels': [r[0] for r in product_rev],
            'values': [round(r[1], 2) for r in product_rev]
        },
        'customer_revenue': {
            'labels': [r[0] for r in customer_rev],
            'values': [round(r[1], 2) for r in customer_rev]
        },
        'payment_distribution': {
            'labels': [r[0] or 'Unknown' for r in payment_dist],
            'values': [round(r[1], 2) for r in payment_dist]
        }
    }


def _compute_purchases(start_dt, end_dt):
    """Purchase analytics."""
    labels = _month_labels(start_dt, end_dt)

    # Monthly purchases
    monthly = defaultdict(float)
    purchases = Purchase.query.filter(Purchase.date.between(start_dt, end_dt)).all()
    for p in purchases:
        monthly[_month_key(p.date)] += p.total_amount or 0.0

    # Supplier-wise contribution (top 10)
    supplier_contrib = db.session.query(
        Supplier.name, func.sum(Purchase.total_amount).label('val')
    ).join(Purchase).filter(
        Purchase.date.between(start_dt, end_dt)
    ).group_by(Supplier.id).order_by(func.sum(Purchase.total_amount).desc()).limit(10).all()

    return {
        'labels': labels,
        'monthly': [round(monthly.get(l, 0), 2) for l in labels],
        'supplier_contribution': {
            'labels': [r[0] for r in supplier_contrib],
            'values': [round(r[1], 2) for r in supplier_contrib]
        }
    }


def _compute_inventory():
    """Inventory analytics (not date-filtered — shows current state)."""
    # Category distribution
    raw_value = db.session.query(
        func.coalesce(func.sum(Product.stock_quantity * Product.purchase_cost), 0.0)
    ).filter(Product.category == 'Raw Material').scalar()
    finished_value = db.session.query(
        func.coalesce(func.sum(Product.stock_quantity * Product.purchase_cost), 0.0)
    ).filter(Product.category == 'Finished Goods').scalar()

    # Fast movers (top 10 by sale qty)
    fast_movers = db.session.query(
        Product.name, func.sum(SaleItem.quantity).label('qty')
    ).join(SaleItem).group_by(Product.id).order_by(
        func.sum(SaleItem.quantity).desc()
    ).limit(10).all()

    # Slow movers (products with stock but minimal/no sales)
    slow_movers = db.session.query(
        Product.name, Product.stock_quantity
    ).outerjoin(SaleItem).group_by(Product.id).having(
        func.coalesce(func.sum(SaleItem.quantity), 0) == 0
    ).filter(Product.stock_quantity > 0).limit(10).all()

    # Low stock alerts
    low_stock = Product.query.filter(
        Product.stock_quantity <= Product.low_stock_threshold
    ).order_by(Product.stock_quantity.asc()).limit(15).all()

    return {
        'category_distribution': {
            'labels': ['Raw Materials', 'Finished Goods'],
            'values': [round(raw_value, 2), round(finished_value, 2)]
        },
        'fast_movers': {
            'labels': [r[0] for r in fast_movers],
            'values': [round(r[1], 2) for r in fast_movers]
        },
        'slow_movers': {
            'labels': [r[0] for r in slow_movers],
            'values': [round(r[1], 2) for r in slow_movers]
        },
        'low_stock': [
            {'name': p.name, 'code': p.code, 'qty': p.stock_quantity, 'threshold': p.low_stock_threshold}
            for p in low_stock
        ]
    }


def _compute_manufacturing(start_dt, end_dt):
    """Manufacturing analytics."""
    labels = _month_labels(start_dt, end_dt)

    # Production trend
    prod_monthly = defaultdict(float)
    runs = ProductionRun.query.filter(ProductionRun.date.between(start_dt, end_dt)).all()
    for r in runs:
        prod_monthly[_month_key(r.date)] += r.quantity_produced or 0.0

    # Raw material consumption
    consumption_monthly = defaultdict(float)
    consumptions = db.session.query(ProductionConsumption, ProductionRun).join(
        ProductionRun
    ).filter(ProductionRun.date.between(start_dt, end_dt)).all()
    for pc, pr in consumptions:
        consumption_monthly[_month_key(pr.date)] += pc.quantity_consumed or 0.0

    # Top produced products
    top_produced = db.session.query(
        Product.name, func.sum(ProductionRun.quantity_produced).label('qty')
    ).join(ProductionRun, ProductionRun.finished_product_id == Product.id).filter(
        ProductionRun.date.between(start_dt, end_dt)
    ).group_by(Product.id).order_by(func.sum(ProductionRun.quantity_produced).desc()).limit(10).all()

    return {
        'labels': labels,
        'production': [round(prod_monthly.get(l, 0), 2) for l in labels],
        'consumption': [round(consumption_monthly.get(l, 0), 2) for l in labels],
        'top_produced': {
            'labels': [r[0] for r in top_produced],
            'values': [round(r[1], 2) for r in top_produced]
        }
    }


def _compute_cashflow(start_dt, end_dt):
    """Cash flow analytics based on Vouchers."""
    labels = _month_labels(start_dt, end_dt)

    # Cash & Bank ledger IDs
    cash_groups = AccountGroup.query.filter(AccountGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
    cash_group_ids = [g.id for g in cash_groups]
    cash_ledgers = Ledger.query.filter(Ledger.group_id.in_(cash_group_ids)).all() if cash_group_ids else []
    cash_ledger_ids = [l.id for l in cash_ledgers]

    inflow_monthly = defaultdict(float)
    outflow_monthly = defaultdict(float)

    if cash_ledger_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(cash_ledger_ids),
            Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            key = _month_key(v.date)
            if ve.entry_type == 'Dr':
                inflow_monthly[key] += ve.amount
            else:
                outflow_monthly[key] += ve.amount

    net_monthly = {}
    for l in labels:
        net_monthly[l] = inflow_monthly.get(l, 0) - outflow_monthly.get(l, 0)

    return {
        'labels': labels,
        'inflow': [round(inflow_monthly.get(l, 0), 2) for l in labels],
        'outflow': [round(outflow_monthly.get(l, 0), 2) for l in labels],
        'net': [round(net_monthly.get(l, 0), 2) for l in labels],
    }


# ──────────────────────────────────────────────────────────────────────────────
# EXISTING ROUTES — PRESERVED EXACTLY
# ──────────────────────────────────────────────────────────────────────────────

@reports_bp.route('/export/stock/excel')
@login_required
@roles_required(['Admin', 'Store Manager', 'Accountant', 'Owner'])
def download_stock_excel():
    """Streams live on-demand inventory valuation datasets directly into analytical Excel books."""
    from app.utils.excel_exporter import generate_stock_excel
    try:
        products = Product.query.order_by(Product.code.asc()).all()
        excel_stream = generate_stock_excel(products)
        return send_file(
            excel_stream,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"Sikka_Inventory_Master_{datetime.date.today()}.xlsx"
        )
    except Exception as e:
        flash(f"Data conversion fault block generated an unexpected error: {str(e)}", "danger")
        return redirect(url_for('reports.analytics_hub'))


@reports_bp.route('/export/sales/pdf')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def download_sales_pdf():
    """Generates and streams formal executive PDF summary briefs directly to client browsers."""
    from app.utils.pdf_generator import generate_sales_summary_pdf
    try:
        sales = Sale.query.order_by(Sale.date.desc()).all()
        pdf_stream = generate_sales_summary_pdf(sales)
        return send_file(
            pdf_stream,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=f"Sikka_Executive_Sales_Brief.pdf"
        )
    except Exception as e:
        flash(f"Document build routine encountered structural compilation failures: {str(e)}", "danger")
        return redirect(url_for('reports.analytics_hub'))


@reports_bp.route('/trial_balance')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def trial_balance():
    """Generates a Trial Balance summarizing all ledger closing balances."""
    from app.models import Ledger, VoucherEntry
    ledgers = Ledger.query.order_by(Ledger.name.asc()).all()

    tb_data = []
    total_dr = 0.0
    total_cr = 0.0

    for l in ledgers:
        running_bal = l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance

        # Calculate current balance from vouchers
        entries = VoucherEntry.query.filter_by(ledger_id=l.id).all()
        for e in entries:
            if e.entry_type == 'Dr':
                running_bal += e.amount
            else:
                running_bal -= e.amount

        if abs(running_bal) > 0.001:
            if running_bal > 0:
                total_dr += running_bal
                tb_data.append({'ledger': l.name, 'group': l.group.name, 'dr': running_bal, 'cr': 0})
            else:
                total_cr += abs(running_bal)
                tb_data.append({'ledger': l.name, 'group': l.group.name, 'dr': 0, 'cr': abs(running_bal)})

    return render_template('modules/reports/trial_balance.html', data=tb_data, total_dr=total_dr, total_cr=total_cr)


@reports_bp.route('/profit_loss')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def profit_loss():
    """Generates Profit & Loss Account."""
    from app.models import AccountGroup, Ledger, VoucherEntry

    # Simple P&L Logic: Revenues (Income) vs Expenses
    income_groups = AccountGroup.query.filter_by(nature='Revenue').all()
    expense_groups = AccountGroup.query.filter_by(nature='Expense').all()

    def get_group_balance(group):
        ledgers = Ledger.query.filter_by(group_id=group.id).all()
        bal = 0.0
        for l in ledgers:
            entries = VoucherEntry.query.filter_by(ledger_id=l.id).all()
            for e in entries:
                bal += e.amount if e.entry_type == 'Cr' else -e.amount
            bal += l.opening_balance if l.opening_balance_type == 'Cr' else -l.opening_balance
        return bal

    incomes = []
    total_income = 0.0
    for ig in income_groups:
        b = get_group_balance(ig)
        if b != 0:
            incomes.append({'group': ig.name, 'amount': b})
            total_income += b

    expenses = []
    total_expense = 0.0
    for eg in expense_groups:
        # Expenses are typically Debit balances
        ledgers = Ledger.query.filter_by(group_id=eg.id).all()
        b = 0.0
        for l in ledgers:
            entries = VoucherEntry.query.filter_by(ledger_id=l.id).all()
            for e in entries:
                b += e.amount if e.entry_type == 'Dr' else -e.amount
            b += l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance
        if b != 0:
            expenses.append({'group': eg.name, 'amount': b})
            total_expense += b

    net_profit = total_income - total_expense
    return render_template('modules/reports/profit_loss.html', incomes=incomes, expenses=expenses, total_income=total_income, total_expense=total_expense, net_profit=net_profit)


@reports_bp.route('/balance_sheet')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def balance_sheet():
    """Generates Balance Sheet."""
    from app.models import AccountGroup, Ledger, VoucherEntry

    asset_groups = AccountGroup.query.filter_by(nature='Asset').all()
    liability_groups = AccountGroup.query.filter(AccountGroup.nature.in_(['Liability', 'Equity'])).all()

    def get_group_balance_dr(group):
        ledgers = Ledger.query.filter_by(group_id=group.id).all()
        bal = 0.0
        for l in ledgers:
            entries = VoucherEntry.query.filter_by(ledger_id=l.id).all()
            for e in entries:
                bal += e.amount if e.entry_type == 'Dr' else -e.amount
            bal += l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance
        return bal

    def get_group_balance_cr(group):
        ledgers = Ledger.query.filter_by(group_id=group.id).all()
        bal = 0.0
        for l in ledgers:
            entries = VoucherEntry.query.filter_by(ledger_id=l.id).all()
            for e in entries:
                bal += e.amount if e.entry_type == 'Cr' else -e.amount
            bal += l.opening_balance if l.opening_balance_type == 'Cr' else -l.opening_balance
        return bal

    assets = []
    total_assets = 0.0
    for ag in asset_groups:
        b = get_group_balance_dr(ag)
        if b != 0:
            assets.append({'group': ag.name, 'amount': b})
            total_assets += b

    liabilities = []
    total_liabilities = 0.0
    for lg in liability_groups:
        b = get_group_balance_cr(lg)
        if b != 0:
            liabilities.append({'group': lg.name, 'amount': b})
            total_liabilities += b

    income_groups = AccountGroup.query.filter_by(nature='Revenue').all()
    expense_groups = AccountGroup.query.filter_by(nature='Expense').all()

    total_income = sum(get_group_balance_cr(ig) for ig in income_groups)
    total_expense = sum(get_group_balance_dr(eg) for eg in expense_groups)
    net_profit = total_income - total_expense

    if net_profit > 0:
        liabilities.append({'group': 'Profit & Loss A/c', 'amount': net_profit})
        total_liabilities += net_profit
    elif net_profit < 0:
        assets.append({'group': 'Profit & Loss A/c (Loss)', 'amount': abs(net_profit)})
        total_assets += abs(net_profit)

    return render_template('modules/reports/balance_sheet.html', assets=assets, liabilities=liabilities, total_assets=total_assets, total_liabilities=total_liabilities)

@reports_bp.route('/day_book')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def day_book():
    """Generates Tally-style Day Book."""
    from app.models import Voucher
    import datetime

    target_date = request.args.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    try:
        t_date = datetime.datetime.strptime(target_date, '%Y-%m-%d').date()
    except:
        t_date = datetime.date.today()

    vouchers = Voucher.query.filter(cast(Voucher.date, Date) == t_date).all()

    return render_template('modules/reports/day_book.html', vouchers=vouchers, target_date=t_date)
