from flask import render_template, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, extract, cast, Date
from datetime import datetime, date
from app import db
from app.models import Sale, Purchase, Expense, LedgerEntry, Product, ProductionRun, AccountGroup, Ledger, Voucher, VoucherEntry
from app.modules.home_expenses.models import HomeExpense
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

    # Home Manager users go directly to their dedicated page
    if role == 'Home Manager':
        from flask import redirect, url_for
        return redirect(url_for('home_expenses.index'))

    # ── Finance KPIs (Accountant / Admin / Owner) ─────────────────────────────
    total_sales = total_purchases = total_expenses = 0.0
    yearly_net_profit = 0.0
    home_expenses_total = 0.0
    cash_in_hand = bank_balance = 0.0
    outstanding_receivables = outstanding_payables = 0.0
    months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    sales_trend_data = [0.0] * 12
    profit_trend_data = [0.0] * 12
    pending_sales_dues = []
    pending_purchase_dues = []
    bank_ledgers = []

    if role in FINANCE_ROLES:
        try:
            # Use cast(col, Date) for PostgreSQL compatibility (func.date() is SQLite-only)
            total_sales = (
                db.session.query(func.coalesce(func.sum(Sale.total_amount), 0.0)).scalar()
            )
            total_purchases = (
                db.session.query(func.coalesce(func.sum(Purchase.total_amount), 0.0)).scalar()
            )
            # Calculate from VoucherEntries based on AccountGroups
            # 1. Total Expenses
            expense_groups = AccountGroup.query.filter(
                AccountGroup.nature == 'Expense',
                AccountGroup.name != 'Purchase Accounts'
            ).all()
            expense_group_ids = [g.id for g in expense_groups]
            expense_ledgers = Ledger.query.filter(Ledger.group_id.in_(expense_group_ids)).all()
            expense_ledger_ids = [l.id for l in expense_ledgers]
            
            if expense_ledger_ids:
                exp_dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(expense_ledger_ids), VoucherEntry.entry_type == 'Dr').scalar()
                exp_cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(expense_ledger_ids), VoucherEntry.entry_type == 'Cr').scalar()
                total_expenses = exp_dr - exp_cr
            else:
                total_expenses = 0.0

            # Add Home Expenses to total (lightweight personal expenses)
            home_expenses_total = db.session.query(
                func.coalesce(func.sum(HomeExpense.amount), 0.0)
            ).scalar()
            total_expenses += home_expenses_total

            # 2. Cash in Hand
            cash_groups = AccountGroup.query.filter(AccountGroup.name == 'Cash-in-Hand').all()
            cash_group_ids = [g.id for g in cash_groups]
            cash_ledgers = Ledger.query.filter(Ledger.group_id.in_(cash_group_ids)).all()
            cash_ledger_ids = [l.id for l in cash_ledgers]
            
            if cash_ledger_ids:
                cash_dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(cash_ledger_ids), VoucherEntry.entry_type == 'Dr').scalar()
                cash_cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(cash_ledger_ids), VoucherEntry.entry_type == 'Cr').scalar()
            else:
                cash_dr, cash_cr = 0.0, 0.0
            cash_ob = sum(l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance for l in cash_ledgers)
            cash_in_hand = cash_ob + cash_dr - cash_cr

            # 3. Bank Balance
            bank_groups = AccountGroup.query.filter(AccountGroup.name == 'Bank Accounts').all()
            bank_group_ids = [g.id for g in bank_groups]
            bank_ledgers = Ledger.query.filter(Ledger.group_id.in_(bank_group_ids)).all()
            bank_ledger_ids = [l.id for l in bank_ledgers]
            
            if bank_ledger_ids:
                bank_dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(bank_ledger_ids), VoucherEntry.entry_type == 'Dr').scalar()
                bank_cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter(
                    VoucherEntry.ledger_id.in_(bank_ledger_ids), VoucherEntry.entry_type == 'Cr').scalar()
            else:
                bank_dr, bank_cr = 0.0, 0.0
            bank_ob = sum(l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance for l in bank_ledgers)
            bank_balance = bank_ob + bank_dr - bank_cr

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
            yearly_net_profit = yearly_gross_profit

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
        total_sales=total_sales,
        total_purchases=total_purchases,
        total_expenses=total_expenses,
        yearly_net_profit=yearly_net_profit,
        cash_in_hand=cash_in_hand,
        bank_balance=bank_balance,
        outstanding_receivables=outstanding_receivables,
        outstanding_payables=outstanding_payables,
        bank_ledgers=bank_ledgers,
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
        home_expenses_total=home_expenses_total if role in FINANCE_ROLES else 0.0,
    )