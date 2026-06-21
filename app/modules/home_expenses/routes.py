from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from app import db
from app.modules.home_expenses import home_expenses_bp
from app.modules.home_expenses.models import (
    HomeExpense, HomeExpenseCategory, seed_home_expense_categories
)
from app.utils.decorators import roles_required
from datetime import datetime


# ---------------------------------------------------------------------------
# MAIN PAGE  –  Dashboard + Form + History (all-in-one)
# ---------------------------------------------------------------------------
@home_expenses_bp.route('/', methods=['GET'])
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def index():
    """Home Expenses dashboard with summary, form, and filterable history."""

    # Auto-seed default categories on first visit
    if HomeExpenseCategory.query.count() == 0:
        seed_home_expense_categories()

    # ── Filters ──
    filter_category = request.args.get('category', '')
    filter_month = request.args.get('month', '')
    filter_year = request.args.get('year', '')
    filter_date_from = request.args.get('date_from', '')
    filter_date_to = request.args.get('date_to', '')

    query = HomeExpense.query

    if filter_category:
        query = query.filter(HomeExpense.category_id == int(filter_category))

    if filter_month:
        query = query.filter(extract('month', HomeExpense.date) == int(filter_month))

    if filter_year:
        query = query.filter(extract('year', HomeExpense.date) == int(filter_year))

    if filter_date_from:
        try:
            d_from = datetime.strptime(filter_date_from, '%Y-%m-%d')
            query = query.filter(HomeExpense.date >= d_from)
        except ValueError:
            pass

    if filter_date_to:
        try:
            d_to = datetime.strptime(filter_date_to, '%Y-%m-%d')
            # Include the entire end date day
            d_to = d_to.replace(hour=23, minute=59, second=59)
            query = query.filter(HomeExpense.date <= d_to)
        except ValueError:
            pass

    expenses = query.order_by(HomeExpense.date.desc()).all()

    # ── Summary calculations ──
    now = datetime.utcnow()

    month_total = db.session.query(func.coalesce(func.sum(HomeExpense.amount), 0)).filter(
        extract('month', HomeExpense.date) == now.month,
        extract('year', HomeExpense.date) == now.year
    ).scalar()

    year_total = db.session.query(func.coalesce(func.sum(HomeExpense.amount), 0)).filter(
        extract('year', HomeExpense.date) == now.year
    ).scalar()

    # Category-wise totals for current month
    category_totals = db.session.query(
        HomeExpenseCategory.name,
        HomeExpenseCategory.icon,
        func.coalesce(func.sum(HomeExpense.amount), 0)
    ).join(HomeExpense).filter(
        extract('month', HomeExpense.date) == now.month,
        extract('year', HomeExpense.date) == now.year
    ).group_by(HomeExpenseCategory.id, HomeExpenseCategory.name, HomeExpenseCategory.icon).all()

    # All categories for the form dropdown
    categories = HomeExpenseCategory.query.order_by(HomeExpenseCategory.name).all()

    # Available years for year filter
    years_raw = db.session.query(
        extract('year', HomeExpense.date).label('yr')
    ).distinct().order_by(extract('year', HomeExpense.date).desc()).all()
    available_years = [int(y.yr) for y in years_raw] if years_raw else [now.year]

    return render_template(
        'modules/home_expenses/home_expenses.html',
        expenses=expenses,
        categories=categories,
        month_total=month_total,
        year_total=year_total,
        category_totals=category_totals,
        available_years=available_years,
        current_month=now.month,
        current_year=now.year,
        # Pass filters back for sticky inputs
        filter_category=filter_category,
        filter_month=filter_month,
        filter_year=filter_year,
        filter_date_from=filter_date_from,
        filter_date_to=filter_date_to,
    )


# ---------------------------------------------------------------------------
# ADD EXPENSE
# ---------------------------------------------------------------------------
@home_expenses_bp.route('/add', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def add_expense():
    """Record a new home expense."""
    date_str = request.form.get('date', '')
    amount = request.form.get('amount', '')
    category_id = request.form.get('category_id', '')
    description = request.form.get('description', '').strip()

    # Validation
    if not amount or not category_id:
        flash('Amount and Category are required.', 'danger')
        return redirect(url_for('home_expenses.index'))

    try:
        expense_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
    except ValueError:
        expense_date = datetime.utcnow()

    try:
        expense = HomeExpense(
            date=expense_date,
            amount=float(amount),
            category_id=int(category_id),
            description=description,
            created_by=current_user.id,
        )
        db.session.add(expense)
        db.session.commit()

        cat = HomeExpenseCategory.query.get(int(category_id))
        flash(f'Home expense of ₹{float(amount):,.2f} ({cat.name if cat else "?"}) recorded.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error saving expense: {str(e)}', 'danger')

    return redirect(url_for('home_expenses.index'))


# ---------------------------------------------------------------------------
# EDIT EXPENSE
# ---------------------------------------------------------------------------
@home_expenses_bp.route('/edit/<int:expense_id>', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def edit_expense(expense_id):
    """Update an existing home expense."""
    expense = HomeExpense.query.get_or_404(expense_id)

    date_str = request.form.get('date', '')
    amount = request.form.get('amount', '')
    category_id = request.form.get('category_id', '')
    description = request.form.get('description', '').strip()

    if not amount or not category_id:
        flash('Amount and Category are required.', 'danger')
        return redirect(url_for('home_expenses.index'))

    try:
        if date_str:
            expense.date = datetime.strptime(date_str, '%Y-%m-%d')
        expense.amount = float(amount)
        expense.category_id = int(category_id)
        expense.description = description
        db.session.commit()
        flash('Expense updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating expense: {str(e)}', 'danger')

    return redirect(url_for('home_expenses.index'))


# ---------------------------------------------------------------------------
# DELETE EXPENSE
# ---------------------------------------------------------------------------
@home_expenses_bp.route('/delete/<int:expense_id>')
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def delete_expense(expense_id):
    """Delete a home expense record."""
    expense = HomeExpense.query.get_or_404(expense_id)

    try:
        db.session.delete(expense)
        db.session.commit()
        flash('Expense deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expense: {str(e)}', 'danger')

    return redirect(url_for('home_expenses.index'))


# ---------------------------------------------------------------------------
# CATEGORY MANAGEMENT
# ---------------------------------------------------------------------------
@home_expenses_bp.route('/categories/add', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def add_category():
    """Add a custom home expense category."""
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '📋').strip()

    if not name:
        flash('Category name is required.', 'danger')
        return redirect(url_for('home_expenses.index'))

    existing = HomeExpenseCategory.query.filter_by(name=name).first()
    if existing:
        flash(f'Category "{name}" already exists.', 'warning')
        return redirect(url_for('home_expenses.index'))

    try:
        category = HomeExpenseCategory(name=name, icon=icon or '📋', is_default=False)
        db.session.add(category)
        db.session.commit()
        flash(f'Category "{name}" added.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding category: {str(e)}', 'danger')

    return redirect(url_for('home_expenses.index'))


@home_expenses_bp.route('/categories/delete/<int:cat_id>')
@login_required
@roles_required(['Admin', 'Owner', 'Home Manager'])
def delete_category(cat_id):
    """Delete a custom category (only if no expenses reference it)."""
    category = HomeExpenseCategory.query.get_or_404(cat_id)

    if category.is_default:
        flash('Cannot delete a default category.', 'warning')
        return redirect(url_for('home_expenses.index'))

    # Check for linked expenses
    count = HomeExpense.query.filter_by(category_id=cat_id).count()
    if count > 0:
        flash(f'Cannot delete "{category.name}" — {count} expense(s) use this category.', 'danger')
        return redirect(url_for('home_expenses.index'))

    try:
        db.session.delete(category)
        db.session.commit()
        flash(f'Category "{category.name}" deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting category: {str(e)}', 'danger')

    return redirect(url_for('home_expenses.index'))
