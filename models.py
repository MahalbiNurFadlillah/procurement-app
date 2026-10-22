from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="requester")
    full_name = db.Column(db.String(150))
    email = db.Column(db.String(150))

    requests = db.relationship("PurchaseRequest", back_populates="requester")
    notifications = db.relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(200))
    address = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)

    purchase_orders = db.relationship("PurchaseOrder", back_populates="supplier")


class PurchaseRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    item_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    specification = db.Column(db.Text)
    budget = db.Column(db.Float)
    attachment_path = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approver_note = db.Column(db.Text)

    requester = db.relationship("User", back_populates="requests")
    purchase_order = db.relationship(
        "PurchaseOrder", back_populates="purchase_request", uselist=False
    )


class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer, db.ForeignKey("purchase_request.id"), nullable=False, unique=True
    )
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False)
    po_number = db.Column(db.String(50), unique=True, nullable=False)
    payment_terms = db.Column(db.String(200), nullable=False, default="Sesuai kesepakatan")
    status = db.Column(db.String(20), nullable=False, default="draft")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    purchase_request = db.relationship("PurchaseRequest", back_populates="purchase_order")
    supplier = db.relationship("Supplier", back_populates="purchase_orders")
    receivings = db.relationship("Receiving", back_populates="purchase_order")


class Receiving(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey("purchase_order.id"), nullable=False)
    received_qty = db.Column(db.Integer, nullable=False)
    condition = db.Column(db.String(100), nullable=False)
    compliant = db.Column(db.Boolean, nullable=False, default=True)
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    note = db.Column(db.Text)

    purchase_order = db.relationship("PurchaseOrder", back_populates="receivings")


class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(200), unique=True, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("purchase_request.id"))
    message = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(20), nullable=False, default="info")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="notifications")
    purchase_request = db.relationship("PurchaseRequest")
