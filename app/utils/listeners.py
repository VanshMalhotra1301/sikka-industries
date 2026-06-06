from sqlalchemy import event
from sqlalchemy.orm import attributes
from flask import request
from flask_login import current_user
import json

def register_listeners(app, db):
    """
    Registers SQLAlchemy event listeners to automatically track field-level changes
    for critical models and logs them to AuditLog.
    """
    with app.app_context():
        from app.models import AuditLog, Customer, Supplier, Product, Sale, Purchase, Expense, Ledger, Voucher, User, SystemNotification, InventoryTransaction

        # List of models to track for auditing
        tracked_models = [Customer, Supplier, Product, Sale, Purchase, Expense, Ledger, Voucher, User]

        def get_current_user_id():
            try:
                if current_user and current_user.is_authenticated:
                    return current_user.id
            except Exception:
                pass
            return None

        def audit_before_update(mapper, connection, target):
            """Capture field changes before an update is committed."""
            try:
                user_id = get_current_user_id()
                state = db.inspect(target)
                
                # Check all columns for changes
                for attr in state.attrs:
                    hist = attr.history
                    if hist.has_changes():
                        # hist.deleted is the old value, hist.added is the new value
                        old_val = hist.deleted[0] if hist.deleted else None
                        new_val = hist.added[0] if hist.added else None
                        
                        # Only log if there's a real difference
                        if old_val != new_val:
                            # Convert to strings for storage, handle objects safely
                            old_str = str(old_val) if old_val is not None else ''
                            new_str = str(new_val) if new_val is not None else ''
                            
                            audit_log = AuditLog(
                                user_id=user_id,
                                model_name=target.__class__.__name__,
                                record_id=target.id if hasattr(target, 'id') else 0,
                                field_name=attr.key,
                                old_value=old_str,
                                new_value=new_str
                            )
                            # We must insert directly using connection since we're in a before_update hook
                            connection.execute(
                                AuditLog.__table__.insert(),
                                {
                                    'user_id': audit_log.user_id,
                                    'model_name': audit_log.model_name,
                                    'record_id': audit_log.record_id,
                                    'field_name': audit_log.field_name,
                                    'old_value': audit_log.old_value,
                                    'new_value': audit_log.new_value,
                                    'date': audit_log.date
                                }
                            )
            except Exception as e:
                app.logger.error(f"Audit log error: {e}")

        # Register before_update event for all tracked models
        for model in tracked_models:
            event.listen(model, 'before_update', audit_before_update)

        def audit_after_insert(mapper, connection, target):
            """Trigger notifications on new critical records."""
            try:
                msg = None
                module = 'System'
                level = 'info'
                
                if target.__class__.__name__ == 'Sale':
                    msg = f"New Sale Invoice #{target.id} created for amount ₹{target.total_amount}."
                    module = 'Sales'
                    level = 'success'
                elif target.__class__.__name__ == 'Purchase':
                    msg = f"New Purchase Bill #{target.id} created for amount ₹{target.total_amount}."
                    module = 'Purchases'
                    level = 'warning'
                elif target.__class__.__name__ == 'Expense':
                    msg = f"New Expense '{target.category}' recorded for amount ₹{target.amount}."
                    module = 'Finance'
                    level = 'danger'
                elif target.__class__.__name__ == 'Voucher':
                    if target.voucher_type == 'Receipt':
                        msg = f"Payment Received: Voucher {target.voucher_number} for ₹{target.amount if hasattr(target, 'amount') else 'Unknown'}."
                        module = 'Banking'
                        level = 'success'
                    elif target.voucher_type == 'Payment':
                        msg = f"Payment Made: Voucher {target.voucher_number}."
                        module = 'Banking'
                        level = 'warning'
                elif target.__class__.__name__ == 'Product' and target.category == 'Raw Material':
                    msg = f"New Raw Material '{target.name}' added."
                    module = 'Inventory'
                    level = 'info'
                elif target.__class__.__name__ == 'InventoryTransaction' and target.quantity > 0:
                    msg = f"Stock Added: {target.quantity} units for Product #{target.product_id}."
                    module = 'Inventory'
                    level = 'info'
                    
                if msg:
                    from datetime import datetime
                    connection.execute(
                        SystemNotification.__table__.insert(),
                        {
                            'message': msg,
                            'alert_level': level,
                            'module': module,
                            'is_read': False,
                            'target_role': None,
                            'date': datetime.utcnow()
                        }
                    )
            except Exception as e:
                app.logger.error(f"Notification error: {e}")

        # Register after_insert event for notification models
        notification_models = [Sale, Purchase, Expense, Voucher, Product, InventoryTransaction]
        for model in notification_models:
            event.listen(model, 'after_insert', audit_after_insert)
