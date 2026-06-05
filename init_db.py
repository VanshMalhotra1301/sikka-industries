import os
from app import create_app, db

app = create_app()

from app.models import AccountGroup, Ledger

with app.app_context():
    # Drop all tables and recreate them
    print("Dropping all tables...")
    db.drop_all()
    print("Creating all tables...")
    db.create_all()
    
    print("Seeding default Account Groups and Ledgers...")
    # Seed Account Groups
    assets = AccountGroup(name='Assets', nature='Asset', is_system=True)
    liabilities = AccountGroup(name='Liabilities', nature='Liability', is_system=True)
    income = AccountGroup(name='Income', nature='Revenue', is_system=True)
    expenses = AccountGroup(name='Expenses', nature='Expense', is_system=True)
    equity = AccountGroup(name='Equity', nature='Equity', is_system=True)
    
    db.session.add_all([assets, liabilities, income, expenses, equity])
    db.session.commit()
    
    current_assets = AccountGroup(name='Current Assets', parent_id=assets.id, nature='Asset', is_system=True)
    cash_group = AccountGroup(name='Cash-in-Hand', parent_id=current_assets.id, nature='Asset', is_system=True)
    bank_group = AccountGroup(name='Bank Accounts', parent_id=current_assets.id, nature='Asset', is_system=True)
    sundry_debtors = AccountGroup(name='Sundry Debtors', parent_id=current_assets.id, nature='Asset', is_system=True)
    
    current_liabilities = AccountGroup(name='Current Liabilities', parent_id=liabilities.id, nature='Liability', is_system=True)
    duties_taxes = AccountGroup(name='Duties & Taxes', parent_id=current_liabilities.id, nature='Liability', is_system=True)
    sundry_creditors = AccountGroup(name='Sundry Creditors', parent_id=current_liabilities.id, nature='Liability', is_system=True)
    
    sales_accounts = AccountGroup(name='Sales Accounts', parent_id=income.id, nature='Revenue', is_system=True)
    purchase_accounts = AccountGroup(name='Purchase Accounts', parent_id=expenses.id, nature='Expense', is_system=True)
    direct_expenses = AccountGroup(name='Direct Expenses', parent_id=expenses.id, nature='Expense', is_system=True)
    indirect_expenses = AccountGroup(name='Indirect Expenses', parent_id=expenses.id, nature='Expense', is_system=True)
    
    db.session.add_all([current_assets, cash_group, bank_group, sundry_debtors, 
                        current_liabilities, duties_taxes, sundry_creditors, 
                        sales_accounts, purchase_accounts, direct_expenses, indirect_expenses])
    db.session.commit()
    
    # Seed Default Ledgers
    cash_ledger = Ledger(name='Cash', group_id=cash_group.id, is_system=True)
    cgst_ledger = Ledger(name='CGST', group_id=duties_taxes.id, is_system=True)
    sgst_ledger = Ledger(name='SGST', group_id=duties_taxes.id, is_system=True)
    igst_ledger = Ledger(name='IGST', group_id=duties_taxes.id, is_system=True)
    sales_ledger = Ledger(name='Sales', group_id=sales_accounts.id, is_system=True)
    purchase_ledger = Ledger(name='Purchases', group_id=purchase_accounts.id, is_system=True)
    
    db.session.add_all([cash_ledger, cgst_ledger, sgst_ledger, igst_ledger, sales_ledger, purchase_ledger])
    db.session.commit()

    print("Database initialized successfully with Tally Prime default groups and ledgers!")
