# src/services/invoice_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from fastapi import HTTPException, status
from models.invoice import Invoice, InvoiceStatus, InvoiceItem, Payment, PaymentMethod
from models.patient import Patient
from models.treatment_item import TreatmentItem
from schemas.invoice_schemas import (
    InvoiceCreate,
    InvoiceUpdate,
    PaymentCreate,
    InvoiceSummary,
)
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("INVOICE_SERVICE")


class InvoiceService(BaseService):
    def __init__(self):
        super().__init__(Invoice)

    async def generate_invoice_number(self, db: AsyncSession) -> str:
        """Generate unique invoice number"""
        # Format: INV-YYYYMMDD-XXXX
        today = date.today()
        date_part = today.strftime("%Y%m%d")

        # Count invoices for today
        result = await db.execute(
            select(func.count(Invoice.id)).where(func.date(Invoice.created_at) == today)
        )
        count_today = result.scalar() or 0

        sequence = count_today + 1
        return f"INV-{date_part}-{sequence:04d}"

    async def create_invoice(
        self, db: AsyncSession, invoice_data: InvoiceCreate
    ) -> Invoice:
        """Create new invoice with items"""
        # Verify patient exists
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == invoice_data.patient_id, Patient.is_active
            )
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient not found or inactive",
            )

        # Generate invoice number
        invoice_number = await self.generate_invoice_number(db)

        # Create invoice
        invoice_dict = invoice_data.dict(exclude={"invoice_items"})
        invoice = Invoice(
            **invoice_dict,
            invoice_number=invoice_number,
            status=InvoiceStatus.DRAFT,
            subtotal=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("0.00"),
        )

        db.add(invoice)
        await db.flush()  # Get the ID without committing

        # Add invoice items and calculate totals
        subtotal = Decimal("0.00")

        for item_data in invoice_data.invoice_items:
            # If treatment_item_id is provided, verify it exists
            if item_data.get("treatment_item_id"):
                treatment_item_result = await db.execute(
                    select(TreatmentItem).where(
                        TreatmentItem.id == item_data["treatment_item_id"]
                    )
                )
                treatment_item = treatment_item_result.scalar_one_or_none()
                if not treatment_item:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Treatment item {item_data['treatment_item_id']} not found",
                    )

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                description=item_data["description"],
                quantity=item_data.get("quantity", 1),
                unit_price=Decimal(str(item_data["unit_price"])),
                tax_rate=Decimal(str(item_data.get("tax_rate", 0.0))),
                treatment_item_id=item_data.get("treatment_item_id"),
            )

            db.add(invoice_item)

            # Calculate item total
            item_total = invoice_item.quantity * invoice_item.unit_price
            item_tax = item_total * (invoice_item.tax_rate / Decimal("100.00"))
            subtotal += item_total + item_tax

        # Update invoice totals
        invoice.subtotal = subtotal
        invoice.tax_amount = subtotal * Decimal(
            "0.00"
        )  # Adjust based on your tax logic
        invoice.discount_amount = Decimal("0.00")  # Add discount logic if needed
        invoice.total_amount = (
            invoice.subtotal + invoice.tax_amount - invoice.discount_amount
        )
        invoice.balance_due = invoice.total_amount - invoice.amount_paid

        await db.commit()
        await db.refresh(invoice)

        logger.info(
            f"Created new invoice: {invoice.invoice_number} for patient {patient.id}"
        )
        return invoice

    async def add_payment(
        self, db: AsyncSession, invoice_id: UUID, payment_data: PaymentCreate
    ) -> Payment:
        """Add payment to invoice"""
        invoice = await self.get(db, invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
            )

        if invoice.status == InvoiceStatus.PAID:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invoice is already paid",
            )

        if invoice.status == InvoiceStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add payment to cancelled invoice",
            )

        # Create payment
        payment = Payment(
            invoice_id=invoice_id,
            amount=payment_data.amount,
            payment_method=payment_data.payment_method,
            reference_number=payment_data.reference_number,
            notes=payment_data.notes,
            payment_date=datetime.utcnow(),
        )

        db.add(payment)

        # Update invoice payment status
        invoice.amount_paid += payment_data.amount
        invoice.balance_due = invoice.total_amount - invoice.amount_paid

        # Update invoice status if fully paid
        if invoice.balance_due <= Decimal("0.00"):
            invoice.status = InvoiceStatus.PAID
            invoice.paid_date = datetime.utcnow()
        elif invoice.amount_paid > Decimal("0.00"):
            invoice.status = InvoiceStatus.PARTIAL

        await db.commit()
        await db.refresh(payment)

        logger.info(f"Added payment of {payment_data.amount} to invoice: {invoice_id}")
        return payment

    async def get_invoice_payments(
        self, db: AsyncSession, invoice_id: UUID
    ) -> List[Payment]:
        """Get all payments for an invoice"""
        try:
            result = await db.execute(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.payment_date)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting invoice payments: {e}")
            return []

    async def get_invoice_summary(self, db: AsyncSession) -> InvoiceSummary:
        """Get invoice summary for dashboard"""
        try:
            # Total invoices
            total_result = await db.execute(select(func.count(Invoice.id)))
            total_invoices = total_result.scalar()

            # Total revenue
            revenue_result = await db.execute(
                select(func.sum(Invoice.total_amount)).where(
                    Invoice.status == InvoiceStatus.PAID
                )
            )
            total_revenue = revenue_result.scalar() or Decimal("0.00")

            # Pending invoices
            pending_result = await db.execute(
                select(func.count(Invoice.id)).where(
                    Invoice.status.in_(
                        [InvoiceStatus.DRAFT, InvoiceStatus.SENT, InvoiceStatus.PARTIAL]
                    )
                )
            )
            pending_invoices = pending_result.scalar()

            # Overdue invoices
            overdue_result = await db.execute(
                select(func.count(Invoice.id)).where(
                    Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIAL]),
                    Invoice.due_date < datetime.utcnow(),
                )
            )
            overdue_invoices = overdue_result.scalar()

            # Average invoice amount
            avg_result = await db.execute(
                select(func.avg(Invoice.total_amount)).where(
                    Invoice.status == InvoiceStatus.PAID
                )
            )
            avg_invoice_amount = avg_result.scalar() or Decimal("0.00")

            return InvoiceSummary(
                total_invoices=total_invoices,
                total_revenue=float(total_revenue),
                pending_invoices=pending_invoices,
                overdue_invoices=overdue_invoices,
                average_invoice_amount=float(avg_invoice_amount),
            )
        except Exception as e:
            logger.error(f"Error getting invoice summary: {e}")
            return InvoiceSummary(
                total_invoices=0,
                total_revenue=0.0,
                pending_invoices=0,
                overdue_invoices=0,
                average_invoice_amount=0.0,
            )

    async def send_invoice(
        self, db: AsyncSession, invoice_id: UUID
    ) -> Optional[Invoice]:
        """Mark invoice as sent"""
        invoice = await self.get(db, invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
            )

        if invoice.status != InvoiceStatus.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invoice is not in draft status",
            )

        invoice.status = InvoiceStatus.SENT
        await db.commit()
        await db.refresh(invoice)

        logger.info(f"Sent invoice: {invoice.invoice_number}")
        return invoice


invoice_service = InvoiceService()
