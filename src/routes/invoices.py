# src/routes/invoices.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.invoice_schemas import (
    InvoiceCreate,
    InvoiceUpdate,
    InvoicePublic,
    InvoiceDetail,
    PaymentCreate,
    PaymentPublic,
    InvoiceSummary,
)
from services.invoice_service import invoice_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get(
    "/",
    response_model=List[InvoicePublic],
    summary="List invoices",
    description="Get list of invoices",
)
async def list_invoices(
    skip: int = 0,
    limit: int = 50,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List invoices endpoint"""
    filters = {}
    if patient_id:
        filters["patient_id"] = patient_id
    if status:
        filters["status"] = status

    invoices = await invoice_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [InvoicePublic.from_orm(invoice) for invoice in invoices]


@router.post(
    "/",
    response_model=InvoicePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create invoice",
    description="Create a new invoice",
)
async def create_invoice(
    invoice_data: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create invoice endpoint"""
    invoice = await invoice_service.create_invoice(db, invoice_data)
    return InvoicePublic.from_orm(invoice)


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetail,
    summary="Get invoice",
    description="Get invoice details by ID",
)
async def get_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get invoice by ID endpoint"""
    invoice = await invoice_service.get(db, invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
        )

    invoice_detail = InvoiceDetail.from_orm(invoice)
    invoice_detail.patient_name = (
        f"{invoice.patient.first_name} {invoice.patient.last_name}"
    )
    invoice_detail.patient_contact = invoice.patient.contact_number

    return invoice_detail


@router.put(
    "/{invoice_id}",
    response_model=InvoicePublic,
    summary="Update invoice",
    description="Update invoice information",
)
async def update_invoice(
    invoice_id: UUID,
    invoice_data: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update invoice endpoint"""
    invoice = await invoice_service.update(db, invoice_id, invoice_data)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
        )
    return InvoicePublic.from_orm(invoice)


@router.post(
    "/{invoice_id}/payments",
    response_model=PaymentPublic,
    summary="Add payment",
    description="Add payment to invoice",
)
async def add_payment(
    invoice_id: UUID,
    payment_data: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Add payment endpoint"""
    payment = await invoice_service.add_payment(db, invoice_id, payment_data)
    return PaymentPublic.from_orm(payment)


@router.get(
    "/summary/dashboard",
    response_model=InvoiceSummary,
    summary="Get invoice summary",
    description="Get invoice summary for dashboard",
)
async def get_invoice_summary(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get invoice summary endpoint"""
    summary = await invoice_service.get_invoice_summary(db)
    return summary
