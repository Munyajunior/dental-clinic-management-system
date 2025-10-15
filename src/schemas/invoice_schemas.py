# src/schemas/invoice_schemas.py
from pydantic import field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from models.invoice import InvoiceStatus, PaymentMethod
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class InvoiceBase(BaseSchema):
    """Base invoice schema"""

    patient_id: UUID
    issue_date: datetime = datetime.now()


class InvoiceCreate(InvoiceBase):
    """Schema for creating an invoice"""

    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    invoice_items: List[Dict[str, Any]] = []


class InvoiceUpdate(BaseSchema):
    """Schema for updating an invoice"""

    status: Optional[InvoiceStatus] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    discount_amount: Optional[Decimal] = None


class InvoiceInDB(IDMixin, TenantMixin, InvoiceBase, TimestampMixin):
    """Invoice schema for database representation"""

    invoice_number: str
    status: InvoiceStatus
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    due_date: Optional[datetime] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    terms: Optional[str] = None


class InvoicePublic(BaseSchema):
    """Public invoice schema"""

    id: UUID
    invoice_number: str
    patient_id: UUID
    status: InvoiceStatus
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    issue_date: datetime
    due_date: Optional[datetime] = None
    is_overdue: bool


class InvoiceDetail(InvoicePublic):
    """Detailed invoice schema"""

    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    notes: Optional[str] = None
    terms: Optional[str] = None
    paid_date: Optional[datetime] = None
    patient_name: str
    patient_contact: str
    invoice_items: List[Dict[str, Any]]


class InvoiceItemBase(BaseSchema):
    """Base invoice item schema"""

    description: str
    quantity: int = 1
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0.0")


class InvoiceItemCreate(InvoiceItemBase):
    """Schema for creating an invoice item"""

    treatment_item_id: Optional[UUID] = None


class InvoiceItemInDB(IDMixin, InvoiceItemBase):
    """Invoice item schema for database representation"""

    invoice_id: UUID
    treatment_item_id: Optional[UUID] = None


class PaymentBase(BaseSchema):
    """Base payment schema"""

    invoice_id: UUID
    amount: Decimal
    payment_method: PaymentMethod


class PaymentCreate(PaymentBase):
    """Schema for creating a payment"""

    reference_number: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Payment amount must be positive")
        return v


class PaymentInDB(IDMixin, TenantMixin, PaymentBase, TimestampMixin):
    """Payment schema for database representation"""

    reference_number: Optional[str] = None
    notes: Optional[str] = None
    is_confirmed: bool
    payment_date: datetime


class PaymentPublic(BaseSchema):
    """Public payment schema"""

    id: UUID
    invoice_id: UUID
    amount: Decimal
    payment_method: PaymentMethod
    reference_number: Optional[str] = None
    is_confirmed: bool
    payment_date: datetime


class InvoiceSummary(BaseSchema):
    """Invoice summary for dashboard"""

    total_invoices: int
    total_revenue: Decimal
    pending_invoices: int
    overdue_invoices: int
    average_invoice_amount: Decimal
