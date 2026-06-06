from datetime import datetime
from app import db, login_manager
from flask_login import UserMixin


# ---------------------------------------------------------------------------
# Flask-Login user loader callback
# ---------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# USER / AUTH
# ---------------------------------------------------------------------------
class User(db.Model, UserMixin):
    """Internal staff accounts with role-based access control."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Roles: Admin | Accountant | Store Manager | Owner
    role = db.Column(db.String(50), nullable=False, default='Accountant')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username} [{self.role}]>'


# ---------------------------------------------------------------------------
# CRM  –  Customer Master
# ---------------------------------------------------------------------------
class Customer(db.Model):
    """Dealer / customer master profiles."""
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    gst_number = db.Column(db.String(20))
    state = db.Column(db.String(50), default="Delhi")
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales = db.relationship('Sale', backref='customer', lazy=True)

    def __repr__(self):
        return f'<Customer {self.name}>'


# ---------------------------------------------------------------------------
# SCM  –  Supplier Master
# ---------------------------------------------------------------------------
class Supplier(db.Model):
    """Vendor / supplier master profiles."""
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    gst_number = db.Column(db.String(20))
    state = db.Column(db.String(50), default="Delhi")
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    purchases = db.relationship('Purchase', backref='supplier', lazy=True)

    def __repr__(self):
        return f'<Supplier {self.name}>'


# ---------------------------------------------------------------------------
# INVENTORY  –  Product / Stock Master
# ---------------------------------------------------------------------------
class Product(db.Model):
    """
    Unified product catalog covering Raw Materials and Finished Goods (motors).
    category: 'Raw Material' | 'Finished Goods'
    """
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    # 'Raw Material' or 'Finished Goods'
    category = db.Column(db.String(50), nullable=False)
    selling_price = db.Column(db.Float, default=0.0)
    purchase_cost = db.Column(db.Float, default=0.0)
    stock_quantity = db.Column(db.Float, default=0.0)
    low_stock_threshold = db.Column(db.Float, default=10.0)
    gst_rate = db.Column(db.Float, default=18.0)
    hsn_code = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    inventory_logs = db.relationship('InventoryTransaction', backref='product', lazy=True)

    def __repr__(self):
        return f'<Product [{self.code}] {self.name}>'


class InventoryTransaction(db.Model):
    """Audit trail for every physical stock movement."""
    __tablename__ = 'inventory_transactions'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    # Positive = inbound, Negative = outbound
    quantity = db.Column(db.Float, nullable=False)
    # 'Purchase' | 'Sale' | 'Production' | 'Consumption' | 'Adjustment'
    transaction_type = db.Column(db.String(50), nullable=False)
    reference_id = db.Column(db.Integer)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<InvTx {self.transaction_type} qty={self.quantity}>'


# ---------------------------------------------------------------------------
# SALES
# ---------------------------------------------------------------------------
class Sale(db.Model):
    """Master sales invoice header."""
    __tablename__ = 'sales'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    paid_amount = db.Column(db.Float, default=0.0)
    balance_amount = db.Column(db.Float, default=0.0)
    total_cgst = db.Column(db.Float, default=0.0)
    total_sgst = db.Column(db.Float, default=0.0)
    total_igst = db.Column(db.Float, default=0.0)
    discount_percentage = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    # 'Cash' | 'Bank' | 'Credit'
    payment_mode = db.Column(db.String(20))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)

    items = db.relationship('SaleItem', backref='sale', lazy=True)

    def __repr__(self):
        return f'<Sale #{self.id} ₹{self.total_amount}>'


class SaleItem(db.Model):
    """Line items belonging to a sale invoice."""
    __tablename__ = 'sale_items'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, default=0.0)
    subtotal = db.Column(db.Float, nullable=False)
    cgst_amount = db.Column(db.Float, default=0.0)
    sgst_amount = db.Column(db.Float, default=0.0)
    igst_amount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)

    product = db.relationship('Product')

    def __repr__(self):
        return f'<SaleItem sale={self.sale_id} product={self.product_id}>'


# ---------------------------------------------------------------------------
# PURCHASES
# ---------------------------------------------------------------------------
class Purchase(db.Model):
    """Master purchase bill / GRN header."""
    __tablename__ = 'purchases'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    paid_amount = db.Column(db.Float, default=0.0)
    balance_amount = db.Column(db.Float, default=0.0)
    total_cgst = db.Column(db.Float, default=0.0)
    total_sgst = db.Column(db.Float, default=0.0)
    total_igst = db.Column(db.Float, default=0.0)
    # 'Cash' | 'Bank' | 'Credit'
    payment_mode = db.Column(db.String(20))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)

    items = db.relationship('PurchaseItem', backref='purchase', lazy=True)

    def __repr__(self):
        return f'<Purchase #{self.id} ₹{self.total_amount}>'


class PurchaseItem(db.Model):
    """Line items belonging to a purchase bill."""
    __tablename__ = 'purchase_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    cgst_amount = db.Column(db.Float, default=0.0)
    sgst_amount = db.Column(db.Float, default=0.0)
    igst_amount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)

    product = db.relationship('Product')

    def __repr__(self):
        return f'<PurchaseItem purchase={self.purchase_id} product={self.product_id}>'


# ---------------------------------------------------------------------------
# ACCOUNTING  –  General Ledger & Expenses
# ---------------------------------------------------------------------------
class LedgerEntry(db.Model):
    """
    Double-entry style general ledger.
    account_type: 'Cash' | 'Bank' | 'Customer' | 'Supplier' | 'Expense'
    reference_type: 'Sale' | 'Purchase' | 'Receipt' | 'Payment' | 'Expense'
    """
    __tablename__ = 'ledger_entries'

    id = db.Column(db.Integer, primary_key=True)
    account_type = db.Column(db.String(50), nullable=False)
    # entity_id links to Customer.id or Supplier.id for sub-ledgers
    entity_id = db.Column(db.Integer, nullable=True)
    debit = db.Column(db.Float, default=0.0)
    credit = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    reference_type = db.Column(db.String(50))
    reference_id = db.Column(db.Integer)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LedgerEntry {self.account_type} Dr={self.debit} Cr={self.credit}>'


# ---------------------------------------------------------------------------
# NEW: TALLY PRIME-STYLE CHART OF ACCOUNTS & VOUCHERS
# ---------------------------------------------------------------------------
class AccountGroup(db.Model):
    """Hierarchical group of accounts (e.g. Assets, Current Assets, Bank Accounts)"""
    __tablename__ = 'account_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('account_groups.id'), nullable=True)
    nature = db.Column(db.String(50)) # 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense'
    is_system = db.Column(db.Boolean, default=False)

    parent = db.relationship('AccountGroup', remote_side=[id], backref='children')

    def __repr__(self):
        return f'<AccountGroup {self.name}>'


class Ledger(db.Model):
    """Specific account ledgers (e.g. HDFC Bank, Ram & Co., Electricity Exp)"""
    __tablename__ = 'ledgers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('account_groups.id'), nullable=False)
    opening_balance = db.Column(db.Float, default=0.0)
    opening_balance_type = db.Column(db.String(2), default='Dr') # 'Dr' or 'Cr'
    is_system = db.Column(db.Boolean, default=False)

    group = db.relationship('AccountGroup', backref='ledgers')

    def __repr__(self):
        return f'<Ledger {self.name}>'


class Voucher(db.Model):
    """Tally style voucher entry header"""
    __tablename__ = 'vouchers'
    id = db.Column(db.Integer, primary_key=True)
    voucher_type = db.Column(db.String(50), nullable=False) # 'Receipt', 'Payment', 'Contra', 'Journal', 'Sales', 'Purchase'
    voucher_number = db.Column(db.String(50), unique=True, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    narration = db.Column(db.Text)
    reference = db.Column(db.String(100))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    def __repr__(self):
        return f'<Voucher {self.voucher_number} [{self.voucher_type}]>'


class VoucherEntry(db.Model):
    """Voucher line items (Debit or Credit)"""
    __tablename__ = 'voucher_entries'
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=False)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'), nullable=False)
    entry_type = db.Column(db.String(2), nullable=False) # 'Dr' or 'Cr'
    amount = db.Column(db.Float, nullable=False, default=0.0)

    voucher = db.relationship('Voucher', backref=db.backref('entries', lazy=True, cascade='all, delete-orphan'))
    ledger = db.relationship('Ledger', backref='voucher_entries')

    def __repr__(self):
        return f'<VoucherEntry {self.entry_type} {self.amount}>'


class Expense(db.Model):
    """Operational overhead / factory expense records."""
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    # Electricity | Labour | Transport | Office Expense | Maintenance | Miscellaneous
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    # 'Cash' | 'Bank'
    payment_mode = db.Column(db.String(20))
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Expense [{self.category}] ₹{self.amount}>'


# ---------------------------------------------------------------------------
# MANUFACTURING
# ---------------------------------------------------------------------------
class ProductionRun(db.Model):
    """Master batch production log record."""
    __tablename__ = 'production_runs'

    id = db.Column(db.Integer, primary_key=True)
    finished_product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_produced = db.Column(db.Float, nullable=False)
    logged_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    date = db.Column(db.DateTime, default=datetime.utcnow)

    finished_product = db.relationship('Product', foreign_keys=[finished_product_id])
    logger = db.relationship('User', foreign_keys=[logged_by])
    consumptions = db.relationship('ProductionConsumption', backref='run', lazy=True)

    def __repr__(self):
        return f'<ProductionRun #{self.id} qty={self.quantity_produced}>'


class ProductionConsumption(db.Model):
    """Child rows recording raw material consumption per production batch."""
    __tablename__ = 'production_consumptions'

    id = db.Column(db.Integer, primary_key=True)
    production_run_id = db.Column(db.Integer, db.ForeignKey('production_runs.id'), nullable=False)
    raw_material_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_consumed = db.Column(db.Float, nullable=False)

    raw_material = db.relationship('Product', foreign_keys=[raw_material_id])

    def __repr__(self):
        return f'<ProductionConsumption run={self.production_run_id} rm={self.raw_material_id}>'

