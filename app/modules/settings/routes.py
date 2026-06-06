from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user, logout_user
from app import db, bcrypt
from app.models import (
    User, AccountGroup, Ledger,
    Customer, Supplier, Product, InventoryTransaction,
    Sale, SaleItem, Purchase, PurchaseItem,
    LedgerEntry, Voucher, VoucherEntry, Expense,
    ProductionRun, ProductionConsumption
)
from app.modules.settings import settings_bp
from app.utils.decorators import roles_required
import os

@settings_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin'])
def index():
    """System Settings & Developer Tools Dashboard"""
    db_url = os.environ.get('DATABASE_URL', 'SQLite Local')
    if 'supabase' in db_url or 'pooler' in db_url or 'postgresql' in db_url:
        db_display = 'Supabase PostgreSQL (Cloud)'
        env_display = 'Production'
    else:
        db_display = 'SQLite Local'
        env_display = 'Development'
    return render_template('modules/settings/index.html',
                           db_display=db_display, env_display=env_display)


def _seed_accounts_and_ledgers():
    """Seeds the full Tally Prime-style chart of accounts. Same as init_db.py."""
    # Top-level groups
    assets      = AccountGroup(name='Assets',      nature='Asset',     is_system=True)
    liabilities = AccountGroup(name='Liabilities', nature='Liability', is_system=True)
    income      = AccountGroup(name='Income',      nature='Revenue',   is_system=True)
    expenses    = AccountGroup(name='Expenses',    nature='Expense',   is_system=True)
    equity      = AccountGroup(name='Equity',      nature='Equity',    is_system=True)
    db.session.add_all([assets, liabilities, income, expenses, equity])
    db.session.flush()

    # Sub-groups
    current_assets    = AccountGroup(name='Current Assets',    parent_id=assets.id,      nature='Asset',     is_system=True)
    cash_group        = AccountGroup(name='Cash-in-Hand',      parent_id=current_assets.id if True else None,  nature='Asset',     is_system=True)
    bank_group        = AccountGroup(name='Bank Accounts',     parent_id=current_assets.id if True else None,  nature='Asset',     is_system=True)
    sundry_debtors    = AccountGroup(name='Sundry Debtors',    parent_id=current_assets.id if True else None,  nature='Asset',     is_system=True)
    current_liab      = AccountGroup(name='Current Liabilities', parent_id=liabilities.id, nature='Liability', is_system=True)
    duties_taxes      = AccountGroup(name='Duties & Taxes',    parent_id=current_liab.id if True else None,    nature='Liability', is_system=True)
    sundry_creditors  = AccountGroup(name='Sundry Creditors',  parent_id=current_liab.id if True else None,    nature='Liability', is_system=True)
    sales_accounts    = AccountGroup(name='Sales Accounts',    parent_id=income.id,       nature='Revenue',   is_system=True)
    purchase_accounts = AccountGroup(name='Purchase Accounts', parent_id=expenses.id,     nature='Expense',   is_system=True)
    direct_expenses   = AccountGroup(name='Direct Expenses',   parent_id=expenses.id,     nature='Expense',   is_system=True)
    indirect_expenses = AccountGroup(name='Indirect Expenses', parent_id=expenses.id,     nature='Expense',   is_system=True)

    db.session.add_all([
        current_assets, cash_group, bank_group, sundry_debtors,
        current_liab, duties_taxes, sundry_creditors,
        sales_accounts, purchase_accounts, direct_expenses, indirect_expenses
    ])
    db.session.flush()

    # Default ledgers
    db.session.add_all([
        Ledger(name='Cash',      group_id=cash_group.id,        is_system=True),
        Ledger(name='CGST',      group_id=duties_taxes.id,      is_system=True),
        Ledger(name='SGST',      group_id=duties_taxes.id,      is_system=True),
        Ledger(name='IGST',      group_id=duties_taxes.id,      is_system=True),
        Ledger(name='Sales',     group_id=sales_accounts.id,    is_system=True),
        Ledger(name='Purchases', group_id=purchase_accounts.id, is_system=True),
    ])
    db.session.flush()


@settings_bp.route('/factory-reset', methods=['POST'])
@login_required
@roles_required(['Admin'])
def factory_reset():
    """Wipes the database and recreates the baseline structure."""
    password = request.form.get('password')

    if not password:
        flash('Password is required to confirm a factory reset.', 'danger')
        return redirect(url_for('settings.index'))

    if not bcrypt.check_password_hash(current_user.password_hash, password):
        flash('Authentication failed. Incorrect password.', 'danger')
        return redirect(url_for('settings.index'))

    try:
        # Preserve admin credentials before wiping
        admin_username    = current_user.username
        admin_pw_hash     = current_user.password_hash
        admin_role        = current_user.role

        # --- Wipe all data ------------------------------------------------
        # Use TRUNCATE … CASCADE for PostgreSQL (Supabase) — fast & reliable.
        # Fall back to drop_all / create_all for SQLite / other databases.
        db_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql' in db_url or 'postgres' in db_url:
            # PostgreSQL: truncate every table in one statement
            db.session.execute(db.text(
                "TRUNCATE TABLE "
                "production_consumptions, production_runs, "
                "voucher_entries, vouchers, "
                "sale_items, sales, purchase_items, purchases, "
                "inventory_transactions, expenses, ledger_entries, "
                "ledgers, account_groups, "
                "products, customers, suppliers, users "
                "RESTART IDENTITY CASCADE"
            ))
            db.session.commit()
            # Recreate tables in case schema drifted (safe no-op if they exist)
            db.create_all()
        else:
            # SQLite / other: full drop + recreate
            db.drop_all()
            db.create_all()

        # --- Re-seed chart of accounts ------------------------------------
        _seed_accounts_and_ledgers()

        # --- Recreate admin user ------------------------------------------
        admin_user = User(
            username=admin_username,
            password_hash=admin_pw_hash,
            role=admin_role,
            is_active=True
        )
        db.session.add(admin_user)
        db.session.commit()

        logout_user()
        flash('Database wiped and re-seeded successfully. Please log in again.', 'success')
        return redirect(url_for('auth.login'))

    except Exception as e:
        db.session.rollback()
        flash(f'Critical error during factory reset: {str(e)}', 'danger')
        return redirect(url_for('settings.index'))
