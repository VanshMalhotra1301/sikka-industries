from flask import render_template, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, extract, cast, Date
from datetime import datetime, date
from app import db
from app.models import Sale, Purchase, Expense, LedgerEntry, Product, ProductionRun
from app.modules.dashboard import dashboard_bp

# Roles that have full financial visibility
FINANCE_ROLES  = {'Admin', 'Owner', 'Accountant'}
# Roles that have warehouse / operations visibility
WAREHOUSE_ROLES = {'Admin', 'Owner', 'Store Manager'}
# Roles with full access
FULL_ACCESS_ROLES = {'Admin', 'Owner'}

@dashboard_bp.route('/')
@login_required
def index():
    today = date.today()
    role  = current_user.role

    # ── Finance KPIs (Accountant / Admin / Owner) ─────────────────────────────
    today_sales = today_purchases = today_expenses = 0.0
    yearly_net_profit = 0.0
    cash_in_hand = bank_balance = 0.0
    outstanding_receivables = outstanding_payables = 0.0
    months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    sales_trend_data = [0.0] * 12
    profit_trend_data = [0.0] * 12
    pending_sales_dues = []
    pending_purchase_dues = []

    if role in FINANCE_ROLES:
        try:
            # Use cast(col, Date) for PostgreSQL compatibility (func.date() is SQLite-only)
            today_sales = (
                db.session.query(func.coalesce(func.sum(Sale.total_amount), 0.0))
                .filter(cast(Sale.date, Date) == today).scalar()
            )
            today_purchases = (
                db.session.query(func.coalesce(func.sum(Purchase.total_amount), 0.0))
                .filter(cast(Purchase.date, Date) == today).scalar()
            )
            today_expenses = (
                db.session.query(func.coalesce(func.sum(Expense.amount), 0.0))
                .filter(cast(Expense.date, Date) == today).scalar()
            )

            cash_debits  = db.session.query(func.coalesce(func.sum(LedgerEntry.debit), 0.0)).filter(LedgerEntry.account_type  == 'Cash').scalar()
            cash_credits = db.session.query(func.coalesce(func.sum(LedgerEntry.credit), 0.0)).filter(LedgerEntry.account_type == 'Cash').scalar()
            cash_in_hand = cash_debits - cash_credits

            bank_debits  = db.session.query(func.coalesce(func.sum(LedgerEntry.debit), 0.0)).filter(LedgerEntry.account_type  == 'Bank').scalar()
            bank_credits = db.session.query(func.coalesce(func.sum(LedgerEntry.credit), 0.0)).filter(LedgerEntry.account_type == 'Bank').scalar()
            bank_balance = bank_debits - bank_credits

            outstanding_receivables = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).scalar()
            outstanding_payables    = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).scalar()

            # Monthly sales trend and profit trend (current year)
            current_year = datetime.utcnow().year
            monthly_sales_objs = Sale.query.filter(extract('year', Sale.date) == current_year).all()
            yearly_gross_profit = 0.0
            
            for s in monthly_sales_objs:
                m = s.date.month
                if 1 <= m <= 12:
                    sales_trend_data[m - 1] += s.total_amount or 0.0
                    for item in s.items:
                        profit = (item.subtotal or 0.0) - (item.quantity * (item.product.purchase_cost or 0.0))
                        profit_trend_data[m - 1] += profit
                        yearly_gross_profit += profit
                        
            yearly_expenses = (
                db.session.query(func.coalesce(func.sum(Expense.amount), 0.0))
                .filter(extract('year', Expense.date) == current_year).scalar()
            )
            yearly_net_profit = yearly_gross_profit - yearly_expenses

            # Due Date Reminders
            pending_sales_dues = Sale.query.filter(Sale.balance_amount > 0, Sale.due_date != None).order_by(Sale.due_date.asc()).all()
            pending_purchase_dues = Purchase.query.filter(Purchase.balance_amount > 0, Purchase.due_date != None).order_by(Purchase.due_date.asc()).all()
        except Exception as e:
            current_app.logger.error(f'Dashboard finance KPI error: {e}')
            db.session.rollback()

    # ── Warehouse / Inventory KPIs (Store Manager / Admin / Owner) ────────────
    current_stock_value = 0.0
    low_stock_alerts    = []
    recent_production   = []

    if role in WAREHOUSE_ROLES:
        try:
            products = Product.query.all()
            current_stock_value = sum((p.stock_quantity or 0.0) * (p.purchase_cost or 0.0) for p in products)
            low_stock_alerts    = [p for p in products if (p.stock_quantity or 0.0) <= (p.low_stock_threshold or 0.0)]

            recent_production = (
                ProductionRun.query
                .order_by(ProductionRun.date.desc())
                .limit(5)
                .all()
            )
        except Exception as e:
            current_app.logger.error(f'Dashboard warehouse KPI error: {e}')
            db.session.rollback()

    return render_template(
        'modules/dashboard/index.html',
        role=role,
        # Finance
        today_sales=today_sales,
        today_purchases=today_purchases,
        today_expenses=today_expenses,
        yearly_net_profit=yearly_net_profit,
        cash_in_hand=cash_in_hand,
        bank_balance=bank_balance,
        outstanding_receivables=outstanding_receivables,
        outstanding_payables=outstanding_payables,
        # Warehouse
        current_stock_value=current_stock_value,
        low_stock_alerts=low_stock_alerts[:5],
        recent_production=recent_production,
        # Chart data
        months_labels=months_labels,
        sales_trend_data=sales_trend_data,
        profit_trend_data=profit_trend_data,
        current_year=datetime.utcnow().year,
        
        # Reminders
        pending_sales_dues=pending_sales_dues,
        pending_purchase_dues=pending_purchase_dues,
        today_date=today,
    )