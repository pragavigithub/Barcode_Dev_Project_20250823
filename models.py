from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    role = db.Column(db.String(20), nullable=False,
                  default='user')  # admin, manager, user
    branch_id = db.Column(db.String(10), nullable=True)
    branch_name = db.Column(db.String(100), nullable=True)
    default_branch_id = db.Column(
        db.String(10), nullable=True)  # Default branch if none selected
    active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(
        db.Boolean, default=False)  # Force password change on next login
    last_login = db.Column(db.DateTime, nullable=True)
    permissions = db.Column(db.Text,
                         nullable=True)  # JSON string of screen permissions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,
                        default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    def get_permissions(self):
        """Get user permissions as a dictionary"""
        import json
        if self.permissions:
            try:
                return json.loads(self.permissions)
            except:
                return {}
        return self.get_default_permissions()

    def set_permissions(self, perms_dict):
        """Set user permissions from a dictionary"""
        import json
        self.permissions = json.dumps(perms_dict)

    def get_default_permissions(self):
        """Get default permissions based on role"""
        permissions = {
            'dashboard': True,
            'serial_transfer': False,
            'user_management': False
        }

        if self.role == 'admin':
            # Admin has access to everything
            for key in permissions:
                permissions[key] = True
        elif self.role == 'manager':
            permissions.update({
                'serial_transfer': True,
                'user_management': True
            })
        elif self.role == 'user':
            permissions.update({
                'serial_transfer': True
            })

        return permissions

    def has_permission(self, screen):
        """Check if user has permission for a specific screen"""
        if self.role == 'admin':
            return True
        return self.get_permissions().get(screen, False)


# ================================
# Serial Number Transfer Models
# ================================

class SerialNumberTransfer(db.Model):
    """Serial Number-wise Stock Transfer Document Header"""
    __tablename__ = 'serial_number_transfers'
    
    id = db.Column(db.Integer, primary_key=True)
    transfer_number = db.Column(db.String(50), nullable=False, unique=True)
    sap_document_number = db.Column(db.String(50))
    status = db.Column(db.String(20), default='draft')  # draft, submitted, qc_approved, posted, rejected
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    qc_approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    qc_approved_at = db.Column(db.DateTime)
    qc_notes = db.Column(db.Text)
    from_warehouse = db.Column(db.String(10), nullable=False)
    to_warehouse = db.Column(db.String(10), nullable=False)
    priority = db.Column(db.String(10), default='normal')  # low, normal, high, urgent
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='serial_transfers')
    qc_approver = db.relationship('User', foreign_keys=[qc_approver_id])
    items = db.relationship('SerialNumberTransferItem', backref='serial_transfer', lazy=True, cascade='all, delete-orphan')

class SerialNumberTransferItem(db.Model):
    """Serial Number Transfer Line Items"""
    __tablename__ = 'serial_number_transfer_items'
    
    id = db.Column(db.Integer, primary_key=True)
    serial_transfer_id = db.Column(db.Integer, db.ForeignKey('serial_number_transfers.id'), nullable=False)
    item_code = db.Column(db.String(50), nullable=False)
    item_name = db.Column(db.String(200))
    quantity = db.Column(db.Integer, nullable=False)  # Expected quantity for this item
    unit_of_measure = db.Column(db.String(10), default='EA')
    from_warehouse_code = db.Column(db.String(10), nullable=False)
    to_warehouse_code = db.Column(db.String(10), nullable=False)
    qc_status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    serial_numbers = db.relationship('SerialNumberTransferSerial', backref='transfer_item', lazy=True, cascade='all, delete-orphan')

class SerialNumberTransferSerial(db.Model):
    """Individual Serial Numbers for Transfer Items"""
    __tablename__ = 'serial_number_transfer_serials'
    
    id = db.Column(db.Integer, primary_key=True)
    transfer_item_id = db.Column(db.Integer, db.ForeignKey('serial_number_transfer_items.id'), nullable=False)
    serial_number = db.Column(db.String(100), nullable=False)
    internal_serial_number = db.Column(db.String(100), nullable=False)  # From SAP SerialNumberDetails
    system_serial_number = db.Column(db.Integer)  # SystemNumber from SAP
    is_validated = db.Column(db.Boolean, default=False)  # Validated against SAP
    validation_error = db.Column(db.Text)  # Error message if validation fails
    manufacturing_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    admission_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Note: Unique constraint removed to allow duplicate serial numbers for user review
    # Users can now add duplicates and manually delete unwanted entries from the UI
    # __table_args__ = (db.UniqueConstraint('transfer_item_id', 'serial_number', name='unique_serial_per_item'),)