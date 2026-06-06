from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, cast, Date, extract
from app import db
from app.models import Ledger, AccountGroup, VoucherEntry, Voucher, Sale, Purchase
from app.modules.banking import banking_bp
from app.utils.decorators import roles_required
import datetime
from collections import defaultdict

@banking_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Accountant'])
def dashboard():
    """Renders the Premium Banking Intelligence Center dashboard."""
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
    return render_template('modules/banking/dashboard.html', bank_ledgers=bank_ledgers)


@banking_bp.route('/treasury-data', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Accountant'])
def treasury_data():
    """Returns JSON analytics for the Treasury Dashboard."""
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

    try:
        data = {}

        # ── 1. FETCH GROUPS & LEDGERS ──────────────────────────────────────
        bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
        cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
        
        bank_ledgers = Ledger.query.filter_by(group_id=bank_group.id).all() if bank_group else []
        cash_ledgers = Ledger.query.filter_by(group_id=cash_group.id).all() if cash_group else []
        
        all_liquidity_ledgers = bank_ledgers + cash_ledgers
        liq_ledger_ids = [l.id for l in all_liquidity_ledgers]

        # ── 2. CURRENT BALANCES ───────────────────────────────────────────
        def get_current_balance(ledger):
            dr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=ledger.id, entry_type='Dr').scalar()
            cr = db.session.query(func.coalesce(func.sum(VoucherEntry.amount), 0.0)).filter_by(ledger_id=ledger.id, entry_type='Cr').scalar()
            ob = ledger.opening_balance if ledger.opening_balance_type == 'Dr' else -ledger.opening_balance
            return ob + dr - cr

        total_bank = sum(get_current_balance(l) for l in bank_ledgers)
        total_cash = sum(get_current_balance(l) for l in cash_ledgers)
        
        data['kpis'] = {
            'total_bank': round(total_bank, 2),
            'total_cash': round(total_cash, 2),
            'total_liquidity': round(total_bank + total_cash, 2)
        }

        # ── 3. PERIOD INFLOW & OUTFLOW (Selected Range) ────────────────────
        period_inflow = 0.0
        period_outflow = 0.0
        
        if liq_ledger_ids:
            entries_in_period = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
                VoucherEntry.ledger_id.in_(liq_ledger_ids),
                Voucher.date.between(start_dt, end_dt)
            ).all()
            
            for ve, v in entries_in_period:
                if ve.entry_type == 'Dr':
                    period_inflow += ve.amount
                else:
                    period_outflow += ve.amount

        data['kpis']['period_inflow'] = round(period_inflow, 2)
        data['kpis']['period_outflow'] = round(period_outflow, 2)
        data['kpis']['net_cash_flow'] = round(period_inflow - period_outflow, 2)

        # Receivables & Payables
        receivables = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).scalar()
        payables = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).scalar()
        data['kpis']['receivables'] = round(receivables, 2)
        data['kpis']['payables'] = round(payables, 2)

        # ── 4. BANK-WISE DETAILS ───────────────────────────────────────────
        bank_details = []
        for l in bank_ledgers:
            bal = get_current_balance(l)
            # Find period inflow/outflow for this specific bank
            b_inflow = 0.0
            b_outflow = 0.0
            last_tx = "No Transactions"
            
            b_entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
                VoucherEntry.ledger_id == l.id,
                Voucher.date.between(start_dt, end_dt)
            ).order_by(Voucher.date.desc()).all()
            
            for ve, v in b_entries:
                if ve.entry_type == 'Dr':
                    b_inflow += ve.amount
                else:
                    b_outflow += ve.amount
                    
            recent_tx = db.session.query(Voucher).join(VoucherEntry).filter(VoucherEntry.ledger_id == l.id).order_by(Voucher.date.desc()).first()
            if recent_tx:
                last_tx = recent_tx.date.strftime('%d %b %Y, %H:%M')
                
            bank_details.append({
                'id': l.id,
                'name': l.name,
                'balance': round(bal, 2),
                'inflow': round(b_inflow, 2),
                'outflow': round(b_outflow, 2),
                'last_tx': last_tx
            })
            
        # Sort banks by balance descending
        bank_details.sort(key=lambda x: x['balance'], reverse=True)
        data['bank_details'] = bank_details

        # ── 5. TREND CHARTS (Monthly / Daily) ──────────────────────────────
        labels = []
        inflow_trend = []
        outflow_trend = []
        
        # Determine interval (Daily if span <= 31 days, otherwise Monthly)
        span_days = (end_date - start_date).days
        is_daily = span_days <= 31
        
        in_map = defaultdict(float)
        out_map = defaultdict(float)
        
        if liq_ledger_ids:
            all_entries = db.session.query(VoucherEntry, Voucher).join(Voucher).filter(
                VoucherEntry.ledger_id.in_(liq_ledger_ids),
                Voucher.date.between(start_dt, end_dt)
            ).all()
            
            for ve, v in all_entries:
                key = v.date.strftime('%d %b') if is_daily else v.date.strftime('%b %Y')
                if ve.entry_type == 'Dr':
                    in_map[key] += ve.amount
                else:
                    out_map[key] += ve.amount
                    
        # Generate labels chronologically
        current = start_date
        while current <= end_date:
            key = current.strftime('%d %b') if is_daily else current.strftime('%b %Y')
            if not labels or labels[-1] != key:
                labels.append(key)
                inflow_trend.append(in_map.get(key, 0.0))
                outflow_trend.append(out_map.get(key, 0.0))
            if is_daily:
                current += datetime.timedelta(days=1)
            else:
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1, day=1)
                else:
                    current = current.replace(month=current.month + 1, day=1)

        data['charts'] = {
            'labels': labels,
            'inflow': [round(x, 2) for x in inflow_trend],
            'outflow': [round(x, 2) for x in outflow_trend],
            'net': [round(inflow_trend[i] - outflow_trend[i], 2) for i in range(len(labels))]
        }
        
        data['distribution'] = {
            'labels': [b['name'] for b in bank_details if b['balance'] > 0],
            'values': [b['balance'] for b in bank_details if b['balance'] > 0]
        }

        # ── 6. TRANSACTIONS LIST ───────────────────────────────────────────
        transactions = []
        if liq_ledger_ids:
            recent_vouchers = db.session.query(Voucher).join(VoucherEntry).filter(
                VoucherEntry.ledger_id.in_(liq_ledger_ids)
            ).order_by(Voucher.date.desc()).limit(15).all()
            
            for v in recent_vouchers:
                # Find the liquidity entry to determine type and amount
                liq_entry = next((e for e in v.entries if e.ledger_id in liq_ledger_ids), None)
                if liq_entry:
                    tx_type = 'Deposit/Inflow' if liq_entry.entry_type == 'Dr' else 'Withdrawal/Outflow'
                    # Find the opposite ledger for description if possible
                    opp_entry = next((e for e in v.entries if e.ledger_id not in liq_ledger_ids), None)
                    party = opp_entry.ledger.name if opp_entry else 'Multiple/Unknown'
                    
                    transactions.append({
                        'date': v.date.strftime('%d %b %Y, %H:%M'),
                        'voucher_no': v.voucher_number,
                        'type': tx_type,
                        'party': party,
                        'amount': round(liq_entry.amount, 2),
                        'narration': v.narration
                    })
        data['recent_transactions'] = transactions

        # ── 7. TREASURY INSIGHTS (AI-style alerts) ─────────────────────────
        insights = []
        if bank_details:
            highest_bank = bank_details[0]
            insights.append({
                'type': 'info',
                'icon': 'bi-bank',
                'text': f"**{highest_bank['name']}** holds the highest balance at **₹{highest_bank['balance']:,.2f}**."
            })
            
        if period_inflow > period_outflow:
            insights.append({
                'type': 'success',
                'icon': 'bi-graph-up-arrow',
                'text': f"Positive net cash flow this period. Inflows exceed outflows by **₹{(period_inflow - period_outflow):,.2f}**."
            })
        elif period_outflow > period_inflow:
            insights.append({
                'type': 'warning',
                'icon': 'bi-graph-down-arrow',
                'text': f"Negative net cash flow. Outflows exceed inflows by **₹{(period_outflow - period_inflow):,.2f}**."
            })
            
        if total_bank + total_cash < payables:
            insights.append({
                'type': 'danger',
                'icon': 'bi-exclamation-triangle',
                'text': f"**Liquidity Risk:** Current available liquidity is less than outstanding payables."
            })
            
        if receivables > payables:
            insights.append({
                'type': 'success',
                'icon': 'bi-shield-check',
                'text': f"Healthy obligation ratio. Receivables exceed payables by **₹{(receivables - payables):,.2f}**."
            })
            
        data['insights'] = insights

        # ── 8. FORECASTING (Next 30 Days) ──────────────────────────────────
        forecast_date = today + datetime.timedelta(days=30)
        expected_in = db.session.query(func.coalesce(func.sum(Sale.balance_amount), 0.0)).filter(
            Sale.due_date <= forecast_date, Sale.balance_amount > 0
        ).scalar()
        expected_out = db.session.query(func.coalesce(func.sum(Purchase.balance_amount), 0.0)).filter(
            Purchase.due_date <= forecast_date, Purchase.balance_amount > 0
        ).scalar()
        
        data['forecast'] = {
            'expected_in': round(expected_in, 2),
            'expected_out': round(expected_out, 2),
            'projected_balance': round(total_bank + total_cash + expected_in - expected_out, 2)
        }

        return jsonify(data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@banking_bp.route('/add', methods=['POST'])
@login_required
@roles_required(['Admin', 'Accountant'])
def add_bank():
    """Adds a new bank ledger."""
    name = request.form.get('name')
    if not name:
        flash('Bank name is required.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    if not bank_group:
        flash('Bank Accounts group not found. Run init_db.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    existing = Ledger.query.filter_by(name=name).first()
    if existing:
        flash(f'Ledger {name} already exists.', 'danger')
        return redirect(url_for('banking.dashboard'))
        
    new_bank = Ledger(name=name, group_id=bank_group.id)
    db.session.add(new_bank)
    db.session.commit()
    
    flash(f'Bank Account "{name}" added successfully.', 'success')
    return redirect(url_for('banking.dashboard'))
