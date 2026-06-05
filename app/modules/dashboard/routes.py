from flask import render_template
from flask_login import login_required, current_user
from sqlalchemy import func
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

    if role in FINANCE_ROLES:
        today_sales = (
            db.session.query(func.sum(Sale.total_amount))
            .filter(func.date(Sale.date) == today).scalar() or 0.0
        )
        today_purchases = (
            db.session.query(func.sum(Purchase.total_amount))
            .filter(func.date(Purchase.date) == today).scalar() or 0.0
        )
        today_expenses = (
            db.session.query(func.sum(Expense.amount))
            .filter(func.date(Expense.date) == today).scalar() or 0.0
        )

        cash_debits  = db.session.query(func.sum(LedgerEntry.debit)).filter(LedgerEntry.account_type  == 'Cash').scalar() or 0.0
        cash_credits = db.session.query(func.sum(LedgerEntry.credit)).filter(LedgerEntry.account_type == 'Cash').scalar() or 0.0
        cash_in_hand = cash_debits - cash_credits

        bank_debits  = db.session.query(func.sum(LedgerEntry.debit)).filter(LedgerEntry.account_type  == 'Bank').scalar() or 0.0
        bank_credits = db.session.query(func.sum(LedgerEntry.credit)).filter(LedgerEntry.account_type == 'Bank').scalar() or 0.0
        bank_balance = bank_debits - bank_credits

        outstanding_receivables = db.session.query(func.sum(Sale.balance_amount)).scalar() or 0.0
        outstanding_payables    = db.session.query(func.sum(Purchase.balance_amount)).scalar() or 0.0

        # Monthly sales trend and profit trend (current year)
        current_year = datetime.utcnow().year
        monthly_sales_objs = Sale.query.filter(func.strftime('%Y', Sale.date) == str(current_year)).all()
        yearly_gross_profit = 0.0
        
        for s in monthly_sales_objs:
            m = s.date.month
            if 1 <= m <= 12:
                sales_trend_data[m - 1] += s.total_amount
                for item in s.items:
                    profit = item.subtotal - (item.quantity * item.product.purchase_cost)
                    profit_trend_data[m - 1] += profit
                    yearly_gross_profit += profit
                    
        yearly_expenses = (
            db.session.query(func.sum(Expense.amount))
            .filter(func.strftime('%Y', Expense.date) == str(current_year)).scalar() or 0.0
        )
        yearly_net_profit = yearly_gross_profit - yearly_expenses

        # Due Date Reminders
        pending_sales_dues = Sale.query.filter(Sale.balance_amount > 0, Sale.due_date != None).order_by(Sale.due_date.asc()).all()
        pending_purchase_dues = Purchase.query.filter(Purchase.balance_amount > 0, Purchase.due_date != None).order_by(Purchase.due_date.asc()).all()
    else:
        pending_sales_dues = []
        pending_purchase_dues = []

    # ── Warehouse / Inventory KPIs (Store Manager / Admin / Owner) ────────────
    current_stock_value = 0.0
    low_stock_alerts    = []
    recent_production   = []

    if role in WAREHOUSE_ROLES:
        products = Product.query.all()
        current_stock_value = sum(p.stock_quantity * p.purchase_cost for p in products)
        low_stock_alerts    = [p for p in products if p.stock_quantity <= p.low_stock_threshold]

        recent_production = (
            ProductionRun.query
            .order_by(ProductionRun.date.desc())
            .limit(5)
            .all()
        )

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