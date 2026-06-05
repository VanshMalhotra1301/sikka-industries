from flask import render_template, send_file, flash, redirect, url_for, request
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models import Sale, Product, Customer, SaleItem
from app.modules.reports import reports_bp
from app.utils.decorators import roles_required

@reports_bp.route('/hub')
@login_required
@roles_required(['Admin', 'Accountant', 'Owner'])
def analytics_hub():
    """Aggregates high-level corporate performance metrics and charts parameters."""
    
    # 1. Best Selling Motor Model Query (Aggregating items sold via line-item joins)
    best_seller_query = db.session.query(
        Product.name, func.sum(SaleItem.quantity).label('total_units')
    ).join(SaleItem, SaleItem.product_id == Product.id)\
     .filter(Product.category == 'Finished Goods')\
     .group_by(Product.id).order_by(func.sum(SaleItem.quantity).desc()).first()
     
    best_product_name = best_seller_query[0] if best_seller_query else "No Dispatches Logged"
    best_product_volume = best_seller_query[1] if best_seller_query else 0.0

    # 2. Top Revenue Customer Dealer Query Tracking Loop
    top_client_query = db.session.query(
        Customer.name, func.sum(Sale.total_amount).label('gross_revenue')
    ).join(Sale, Sale.customer_id == Customer.id)\
     .group_by(Customer.id).order_by(func.sum(Sale.total_amount).desc()).first()
     
    top_customer_name = top_client_query[0] if top_client_query else "No Trades Documented"
    top_customer_billing = top_client_query[1] if top_client_query else 0.0

    # 3. Dynamic Warehouse Health Totals Calculations
    total_raw_lines = Product.query.filter_by(category='Raw Material').count()
    low_stock_count = Product.query.filter(Product.stock_quantity <= Product.low_stock_threshold).count()

    return render_template(
        'modules/reports/analytics_hub.html',
        best_product=best_product_name, best_volume=best_product_volume,
        top_customer=top_customer_name, top_billing=top_customer_billing,
        total_raw=total_raw_lines, alarms=low_stock_count
    )

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
            download_name=f"Sikka_Inventory_Master_{func.date(func.now())}.xlsx"
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
            as_attachment=False, # Opens directly inside native web preview frames cleanly
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
                bal += e.amount if e.entry_type == 'Cr' else -e.amount # For Income/Liability credit is positive
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
            
    # Calculate P&L balance to balance the sheet
    # (Omitted full calculation here, fetching total net profit dynamically)
    # Re-evaluating P&L inline for complete BS
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
        
    vouchers = Voucher.query.filter(db.func.date(Voucher.date) == t_date).all()
    
    return render_template('modules/reports/day_book.html', vouchers=vouchers, target_date=t_date)
