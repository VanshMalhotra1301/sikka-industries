from flask import render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import func, cast, Date, extract
from app import db
from app.models import Ledger, AccountGroup, VoucherEntry, Voucher, Sale, Purchase, SaleItem, Product, Customer, Supplier
from app.modules.finance import finance_bp
from app.utils.decorators import roles_required
import datetime
from collections import defaultdict

@finance_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Accountant', 'CFO'])
def hub():
    """Renders the single-page Finance Intelligence Module."""
    return render_template('modules/finance/dashboard.html')

@finance_bp.route('/api-data', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Accountant', 'CFO'])
def api_data():
    """Unified endpoint for Finance Intelligence tabs."""
    tab = request.args.get('tab', 'executive')
    
    today = datetime.date.today()
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else today.replace(day=1)
    except Exception:
        start_date = today.replace(day=1)
    try:
        end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today
    except Exception:
        end_date = today

    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)
    span_days = max(1, (end_date - start_date).days)
    is_daily = span_days <= 31

    try:
        data = {}
        if tab == 'executive':
            data = _compute_executive(start_dt, end_dt, is_daily)
        elif tab == 'banking':
            data = _compute_banking(start_dt, end_dt, is_daily)
        elif tab == 'gl':
            data = _compute_gl(start_dt, end_dt, is_daily)
        elif tab == 'receivables':
            data = _compute_receivables(start_dt, end_dt, is_daily)
        elif tab == 'payables':
            data = _compute_payables(start_dt, end_dt, is_daily)
        elif tab == 'cashflow':
            data = _compute_cashflow(start_dt, end_dt, is_daily)
        elif tab == 'profit':
            data = _compute_profit(start_dt, end_dt, is_daily)
        else:
            data = {'error': 'Unknown tab'}

        return jsonify(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _generate_labels(start_dt, end_dt, is_daily):
    labels = []
    current = start_dt.date()
    end = end_dt.date()
    while current <= end:
        key = current.strftime('%d %b') if is_daily else current.strftime('%b %Y')
        if not labels or labels[-1] != key:
            labels.append(key)
        if is_daily:
            current += datetime.timedelta(days=1)
        else:
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1, day=1)
            else:
                current = current.replace(month=current.month + 1, day=1)
    return labels

def _get_key(dt, is_daily):
    return dt.strftime('%d %b') if is_daily else dt.strftime('%b %Y')

# ──────────────────────────────────────────────────────────────────────────────
def _compute_executive(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    # Revenue & Profit
    rev_trend = defaultdict(float)
    gp_trend = defaultdict(float)
    total_rev = 0.0
    total_gp = 0.0
    
    sales = db.session.query(Sale).filter(Sale.date.between(start_dt, end_dt)).all()
    for s in sales:
        rev = s.total_amount or 0.0
        total_rev += rev
        rev_trend[_get_key(s.date, is_daily)] += rev
        
        # Calculate GP
        s_gp = 0.0
        for i in s.items:
            s_gp += (i.subtotal or 0.0) - (i.quantity * (i.unit_cost or 0.0))
        total_gp += s_gp
        gp_trend[_get_key(s.date, is_daily)] += s_gp

    # Expenses (exclude Purchase Accounts to avoid double counting COGS)
    exp_groups = AccountGroup.query.filter(AccountGroup.nature == 'Expense', AccountGroup.name != 'Purchase Accounts').all()
    exp_group_ids = [g.id for g in exp_groups]
    exp_ledgers = Ledger.query.filter(Ledger.group_id.in_(exp_group_ids)).all() if exp_group_ids else []
    exp_ledger_ids = [l.id for l in exp_ledgers]
    
    total_exp = 0.0
    exp_trend = defaultdict(float)
    if exp_ledger_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(exp_ledger_ids),
            Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            amt = ve.amount if ve.entry_type == 'Dr' else -ve.amount
            total_exp += amt
            exp_trend[_get_key(v.date, is_daily)] += amt

    total_np = total_gp - total_exp

    # Liquidity
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
    
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    cash_ledgers = Ledger.query.filter_by(group_id=cash_group.id).all() if cash_group else []
    
    def get_bal(l):
        dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=l.id, entry_type='Dr').scalar()
        cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=l.id, entry_type='Cr').scalar()
        ob = l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance
        return ob + dr - cr

    total_bank = sum(get_bal(l) for l in bank_ledgers)
    total_cash = sum(get_bal(l) for l in cash_ledgers)
    liquidity = total_bank + total_cash

    # Receivables & Payables (not date filtered - overall)
    receivables = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).scalar()
    payables = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).scalar()
    working_capital = receivables - payables + liquidity

    # Health Score
    health = 50
    if total_rev > 0:
        margin = (total_np / total_rev) * 100
        health = min(100, max(0, int(50 + margin)))
    if payables > 0 and liquidity < payables:
        health = max(0, health - 20)
    if receivables > total_rev * 0.5:
        health = max(0, health - 10)

    insights = [
        f"**Business Health Score:** {health}/100. {'Healthy' if health >= 70 else 'Needs Attention'}.",
        f"**Working Capital** stands at **₹{working_capital:,.2f}**.",
        f"**Net Profit Margin** is **{((total_np/total_rev)*100) if total_rev else 0:,.1f}%** for the period."
    ]

    return {
        'kpis': {
            'revenue': round(total_rev, 2),
            'expenses': round(total_exp, 2),
            'gross_profit': round(total_gp, 2),
            'net_profit': round(total_np, 2),
            'liquidity': round(liquidity, 2),
            'bank': round(total_bank, 2),
            'receivables': round(receivables, 2),
            'payables': round(payables, 2),
            'working_capital': round(working_capital, 2),
            'health': health
        },
        'charts': {
            'labels': labels,
            'revenue_trend': [round(rev_trend.get(l, 0), 2) for l in labels],
            'expense_trend': [round(exp_trend.get(l, 0), 2) for l in labels],
            'profit_trend': [round(gp_trend.get(l, 0) - exp_trend.get(l, 0), 2) for l in labels],
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_banking(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    cash_ledgers = Ledger.query.filter_by(group_id=cash_group.id).all() if cash_group else []
    liq_ledgers = bank_ledgers + cash_ledgers
    liq_ids = [l.id for l in liq_ledgers]

    in_map = defaultdict(float)
    out_map = defaultdict(float)
    
    total_in = 0.0
    total_out = 0.0

    if liq_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(liq_ids), Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            k = _get_key(v.date, is_daily)
            if ve.entry_type == 'Dr':
                in_map[k] += ve.amount
                total_in += ve.amount
            else:
                out_map[k] += ve.amount
                total_out += ve.amount

    def get_bal(l):
        dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=l.id, entry_type='Dr').scalar()
        cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=l.id, entry_type='Cr').scalar()
        ob = l.opening_balance if l.opening_balance_type == 'Dr' else -l.opening_balance
        return ob + dr - cr

    bank_balances = {b.name: get_bal(b) for b in bank_ledgers}
    cash_balances = {c.name: get_bal(c) for c in cash_ledgers}
    
    total_bank = sum(bank_balances.values())
    total_cash = sum(cash_balances.values())

    insights = [
        f"**Liquidity Flow:** Period saw **₹{total_in:,.2f}** inflow vs **₹{total_out:,.2f}** outflow.",
        f"**Cash vs Bank:** Bank holdings (₹{total_bank:,.2f}) vs Physical Cash (₹{total_cash:,.2f})."
    ]

    return {
        'kpis': {
            'total_bank': round(total_bank, 2),
            'total_cash': round(total_cash, 2),
            'total_liquidity': round(total_bank + total_cash, 2),
            'period_inflow': round(total_in, 2),
            'period_outflow': round(total_out, 2)
        },
        'charts': {
            'labels': labels,
            'money_in': [round(in_map.get(l, 0), 2) for l in labels],
            'money_out': [round(out_map.get(l, 0), 2) for l in labels],
            'alloc_labels': [k for k,v in bank_balances.items() if v > 0],
            'alloc_values': [round(v, 2) for k,v in bank_balances.items() if v > 0],
            'cash_bank_labels': ['Bank Funds', 'Cash-in-Hand'],
            'cash_bank_values': [round(total_bank, 2), round(total_cash, 2)]
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_gl(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    # Overall DB/CR
    dr_map = defaultdict(float)
    cr_map = defaultdict(float)
    total_dr = 0.0
    total_cr = 0.0
    
    entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(Voucher.date.between(start_dt, end_dt)).all()
    for ve, v in entries:
        k = _get_key(v.date, is_daily)
        if ve.entry_type == 'Dr':
            dr_map[k] += ve.amount
            total_dr += ve.amount
        else:
            cr_map[k] += ve.amount
            total_cr += ve.amount

    # Top Ledger Movements
    ledger_movement = defaultdict(float)
    for ve, v in entries:
        ledger_movement[ve.ledger.name] += ve.amount
        
    top_ledgers = sorted(ledger_movement.items(), key=lambda x: x[1], reverse=True)[:10]

    insights = [
        f"**Total Volume:** General Ledger processed **₹{total_dr:,.2f}** in transactions.",
        f"**Most Active Ledger:** **{top_ledgers[0][0] if top_ledgers else 'N/A'}** with **₹{top_ledgers[0][1] if top_ledgers else 0:,.2f}** movement."
    ]

    return {
        'kpis': {
            'total_debit': round(total_dr, 2),
            'total_credit': round(total_cr, 2),
            'active_ledgers': len(set(ve.ledger_id for ve, _ in entries)),
            'total_vouchers': db.session.query(Voucher).filter(Voucher.date.between(start_dt, end_dt)).count()
        },
        'charts': {
            'labels': labels,
            'dr_trend': [round(dr_map.get(l, 0), 2) for l in labels],
            'cr_trend': [round(cr_map.get(l, 0), 2) for l in labels],
            'top_labels': [l[0] for l in top_ledgers],
            'top_values': [round(l[1], 2) for l in top_ledgers]
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_receivables(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    receivables = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).scalar()
    
    # Overdue vs Not Due
    today_date = datetime.date.today()
    overdue = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).filter(
        Sale.due_date < today_date, Sale.balance_amount > 0).scalar()
        
    # Collections Trend (Receipts against Customers)
    collection_map = defaultdict(float)
    total_collections = 0.0
    
    cust_groups = AccountGroup.query.filter_by(name='Sundry Debtors').first()
    if cust_groups:
        cust_ledgers = [l.id for l in Ledger.query.filter_by(group_id=cust_groups.id).all()]
        if cust_ledgers:
            # Receipts are credits to customer accounts
            entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
                VoucherEntry.ledger_id.in_(cust_ledgers),
                VoucherEntry.entry_type == 'Cr',
                Voucher.date.between(start_dt, end_dt)
            ).all()
            for ve, v in entries:
                k = _get_key(v.date, is_daily)
                collection_map[k] += ve.amount
                total_collections += ve.amount

    # Top Debtors
    top_debtors = db.session.query(Customer.name, func.sum(Sale.balance_amount)).join(Sale).filter(Sale.balance_amount > 0).group_by(Customer.id).order_by(func.sum(Sale.balance_amount).desc()).limit(10).all()

    insights = [
        f"**Pending Receivables:** **₹{receivables:,.2f}** (Overdue: **₹{overdue:,.2f}**).",
        f"**Collection Performance:** Collected **₹{total_collections:,.2f}** during this period."
    ]

    return {
        'kpis': {
            'total_receivables': round(receivables, 2),
            'overdue': round(overdue, 2),
            'not_due': round(receivables - overdue, 2),
            'period_collections': round(total_collections, 2)
        },
        'charts': {
            'labels': labels,
            'collection_trend': [round(collection_map.get(l, 0), 2) for l in labels],
            'top_labels': [d[0] for d in top_debtors],
            'top_values': [round(d[1], 2) for d in top_debtors],
            'aging_labels': ['Overdue', 'Not Due'],
            'aging_values': [round(overdue, 2), round(receivables - overdue, 2)]
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_payables(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    payables = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).scalar()
    
    # Overdue vs Not Due
    today_date = datetime.date.today()
    overdue = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).filter(
        Purchase.due_date < today_date, Purchase.balance_amount > 0).scalar()
        
    # Payment Trend (Payments against Suppliers)
    payment_map = defaultdict(float)
    total_payments = 0.0
    
    supp_groups = AccountGroup.query.filter_by(name='Sundry Creditors').first()
    if supp_groups:
        supp_ledgers = [l.id for l in Ledger.query.filter_by(group_id=supp_groups.id).all()]
        if supp_ledgers:
            # Payments are debits to supplier accounts
            entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
                VoucherEntry.ledger_id.in_(supp_ledgers),
                VoucherEntry.entry_type == 'Dr',
                Voucher.date.between(start_dt, end_dt)
            ).all()
            for ve, v in entries:
                k = _get_key(v.date, is_daily)
                payment_map[k] += ve.amount
                total_payments += ve.amount

    # Top Creditors
    top_creditors = db.session.query(Supplier.name, func.sum(Purchase.balance_amount)).join(Purchase).filter(Purchase.balance_amount > 0).group_by(Supplier.id).order_by(func.sum(Purchase.balance_amount).desc()).limit(10).all()

    insights = [
        f"**Pending Payables:** **₹{payables:,.2f}** (Overdue: **₹{overdue:,.2f}**).",
        f"**Supplier Payments:** Paid out **₹{total_payments:,.2f}** to vendors this period."
    ]

    return {
        'kpis': {
            'total_payables': round(payables, 2),
            'overdue': round(overdue, 2),
            'not_due': round(payables - overdue, 2),
            'period_payments': round(total_payments, 2)
        },
        'charts': {
            'labels': labels,
            'payment_trend': [round(payment_map.get(l, 0), 2) for l in labels],
            'top_labels': [c[0] for c in top_creditors],
            'top_values': [round(c[1], 2) for c in top_creditors],
            'aging_labels': ['Overdue', 'Not Due'],
            'aging_values': [round(overdue, 2), round(payables - overdue, 2)]
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_cashflow(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
    liq_ledgers = []
    if bank_group: liq_ledgers += Ledger.query.filter_by(group_id=bank_group.id).all()
    if cash_group: liq_ledgers += Ledger.query.filter_by(group_id=cash_group.id).all()
    liq_ids = [l.id for l in liq_ledgers]

    in_map = defaultdict(float)
    out_map = defaultdict(float)
    
    total_in = 0.0
    total_out = 0.0

    if liq_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(liq_ids), Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            k = _get_key(v.date, is_daily)
            if ve.entry_type == 'Dr':
                in_map[k] += ve.amount
                total_in += ve.amount
            else:
                out_map[k] += ve.amount
                total_out += ve.amount

    insights = [
        f"**Cash Burn/Surplus:** Period Net Cash Flow is **₹{(total_in - total_out):,.2f}**.",
        f"**Movement:** Total Cash Activity of **₹{(total_in + total_out):,.2f}**."
    ]

    return {
        'kpis': {
            'inflow': round(total_in, 2),
            'outflow': round(total_out, 2),
            'net_flow': round(total_in - total_out, 2),
            'burn_rate': round(total_out / max(1, (end_dt - start_dt).days), 2)
        },
        'charts': {
            'labels': labels,
            'net_trend': [round(in_map.get(l, 0) - out_map.get(l, 0), 2) for l in labels],
            'in_trend': [round(in_map.get(l, 0), 2) for l in labels],
            'out_trend': [round(out_map.get(l, 0), 2) for l in labels]
        },
        'insights': insights
    }

# ──────────────────────────────────────────────────────────────────────────────
def _compute_profit(start_dt, end_dt, is_daily):
    labels = _generate_labels(start_dt, end_dt, is_daily)
    
    rev_trend = defaultdict(float)
    gp_trend = defaultdict(float)
    total_rev = 0.0
    total_gp = 0.0
    
    product_profit = defaultdict(float)
    customer_profit = defaultdict(float)
    
    sales = db.session.query(Sale).filter(Sale.date.between(start_dt, end_dt)).all()
    for s in sales:
        rev = s.total_amount or 0.0
        total_rev += rev
        k = _get_key(s.date, is_daily)
        rev_trend[k] += rev
        
        s_gp = 0.0
        for i in s.items:
            item_gp = (i.subtotal or 0.0) - (i.quantity * (i.unit_cost or 0.0))
            s_gp += item_gp
            product_profit[i.product.name] += item_gp
            
        total_gp += s_gp
        gp_trend[k] += s_gp
        customer_profit[s.customer.name] += s_gp

    exp_groups = AccountGroup.query.filter(AccountGroup.nature == 'Expense', AccountGroup.name != 'Purchase Accounts').all()
    exp_group_ids = [g.id for g in exp_groups]
    exp_ledgers = Ledger.query.filter(Ledger.group_id.in_(exp_group_ids)).all() if exp_group_ids else []
    exp_ledger_ids = [l.id for l in exp_ledgers]
    
    total_exp = 0.0
    exp_trend = defaultdict(float)
    if exp_ledger_ids:
        entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
            VoucherEntry.ledger_id.in_(exp_ledger_ids),
            Voucher.date.between(start_dt, end_dt)
        ).all()
        for ve, v in entries:
            amt = ve.amount if ve.entry_type == 'Dr' else -ve.amount
            total_exp += amt
            exp_trend[_get_key(v.date, is_daily)] += amt

    total_np = total_gp - total_exp
    
    top_products = sorted(product_profit.items(), key=lambda x: x[1], reverse=True)[:10]
    top_customers = sorted(customer_profit.items(), key=lambda x: x[1], reverse=True)[:10]

    insights = [
        f"**Gross Margin:** **{((total_gp/total_rev)*100) if total_rev else 0:,.1f}%**. Net Margin: **{((total_np/total_rev)*100) if total_rev else 0:,.1f}%**.",
        f"**Most Profitable Product:** **{top_products[0][0] if top_products else 'N/A'}** generating **₹{top_products[0][1] if top_products else 0:,.2f}** profit."
    ]

    return {
        'kpis': {
            'gross_profit': round(total_gp, 2),
            'net_profit': round(total_np, 2),
            'revenue': round(total_rev, 2),
            'expenses': round(total_exp, 2),
            'gross_margin': round(((total_gp/total_rev)*100) if total_rev else 0, 1),
            'net_margin': round(((total_np/total_rev)*100) if total_rev else 0, 1)
        },
        'charts': {
            'labels': labels,
            'gp_trend': [round(gp_trend.get(l, 0), 2) for l in labels],
            'np_trend': [round(gp_trend.get(l, 0) - exp_trend.get(l, 0), 2) for l in labels],
            'top_prod_labels': [p[0] for p in top_products],
            'top_prod_values': [round(p[1], 2) for p in top_products],
            'top_cust_labels': [c[0] for c in top_customers],
            'top_cust_values': [round(c[1], 2) for c in top_customers]
        },
        'insights': insights
    }
