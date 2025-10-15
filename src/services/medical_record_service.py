# src/services/medical_record_service.py
import os
import uuid
import hashlib
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from models.medical_record import MedicalRecord, RecordType
from models.patient import Patient
from models.user import User
from schemas.medical_record_schemas import MedicalRecordCreate, MedicalRecordUpdate
from utils.logger import setup_logger
from .base_service import BaseService
import aiofiles
from cryptography.fernet import Fernet
import secrets

logger = setup_logger("MEDICAL_RECORD_SERVICE")


class SecureFileStorage:
    """Secure file storage for medical records with encryption"""

    def __init__(self):
        self.storage_path = os.getenv(
            "MEDICAL_RECORDS_STORAGE_PATH", "./medical_records"
        )
        self.encryption_key = os.getenv("FILE_ENCRYPTION_KEY")

        if not self.encryption_key:
            logger.warning("FILE_ENCRYPTION_KEY not set, generating temporary key")
            self.encryption_key = Fernet.generate_key()

        self.cipher_suite = Fernet(self.encryption_key)

        # Ensure storage directory exists
        os.makedirs(self.storage_path, exist_ok=True)

    def _generate_file_path(self, record_id: UUID, file_name: str) -> str:
        """Generate secure file path with UUID to prevent guessing"""
        file_ext = os.path.splitext(file_name)[1]
        secure_filename = f"{record_id}{file_ext}"
        return os.path.join(self.storage_path, secure_filename)

    def _generate_checksum(self, data: bytes) -> str:
        """Generate SHA-256 checksum for file integrity"""
        return hashlib.sha256(data).hexdigest()

    async def store_file(
        self, record_id: UUID, file_name: str, file_data: bytes
    ) -> Dict[str, Any]:
        """Store file securely with encryption and integrity checks"""
        try:
            file_path = self._generate_file_path(record_id, file_name)
            checksum = self._generate_checksum(file_data)

            # Encrypt file data
            encrypted_data = self.cipher_suite.encrypt(file_data)

            # Write encrypted file
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(encrypted_data)

            file_size = len(file_data)

            logger.info(f"Stored secure file: {file_path} ({file_size} bytes)")

            return {
                "file_path": file_path,
                "file_size": file_size,
                "checksum": checksum,
                "encrypted": True,
            }

        except Exception as e:
            logger.error(f"Error storing file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store medical record file",
            )

    async def retrieve_file(self, file_path: str) -> bytes:
        """Retrieve and decrypt file"""
        try:
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
                )

            # Read encrypted file
            async with aiofiles.open(file_path, "rb") as f:
                encrypted_data = await f.read()

            # Decrypt file data
            decrypted_data = self.cipher_suite.decrypt(encrypted_data)

            return decrypted_data

        except Exception as e:
            logger.error(f"Error retrieving file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve medical record file",
            )

    async def delete_file(self, file_path: str) -> bool:
        """Securely delete file"""
        try:
            if os.path.exists(file_path):
                # Overwrite with random data before deletion (optional)
                file_size = os.path.getsize(file_path)
                random_data = secrets.token_bytes(file_size)

                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(random_data)

                os.remove(file_path)
                logger.info(f"Securely deleted file: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False


class MedicalRecordService(BaseService):
    def __init__(self):
        super().__init__(MedicalRecord)
        self.file_storage = SecureFileStorage()

    async def create_medical_record(
        self, db: AsyncSession, record_data: MedicalRecordCreate
    ) -> MedicalRecord:
        """Create new medical record with secure file storage"""
        # Verify patient exists and is active
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == record_data.patient_id, Patient.is_active
            )
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient not found or inactive",
            )

        # Verify creator exists and is active
        creator_result = await db.execute(
            select(User).where(User.id == record_data.created_by, User.is_active)
        )
        creator = creator_result.scalar_one_or_none()
        if not creator:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creator not found or inactive",
            )

        # Create medical record
        record_dict = record_data.dict(exclude={"file_data"})
        record = MedicalRecord(**record_dict)

        db.add(record)
        await db.flush()  # Get the ID without committing

        # Handle file storage if file data provided
        if record_data.file_data and record_data.file_name:
            try:
                # Decode base64 file data
                file_bytes = base64.b64decode(record_data.file_data)

                # Store file securely
                storage_info = await self.file_storage.store_file(
                    record.id, record_data.file_name, file_bytes
                )

                # Update record with file information
                record.file_path = storage_info["file_path"]
                record.file_size = storage_info["file_size"]
                record.file_name = record_data.file_name
                record.mime_type = record_data.mime_type

            except Exception as e:
                await db.rollback()
                logger.error(f"Error storing medical record file: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to store medical record file",
                )

        await db.commit()
        await db.refresh(record)

        logger.info(f"Created new medical record: {record.id} for patient {patient.id}")
        return record

    async def get_file_data(
        self, db: AsyncSession, record_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Get medical record file data securely"""
        record = await self.get(db, record_id)
        if not record or not record.file_path:
            return None

        try:
            file_data = await self.file_storage.retrieve_file(record.file_path)

            return {
                "file_data": base64.b64encode(file_data).decode("utf-8"),
                "file_name": record.file_name,
                "mime_type": record.mime_type,
                "file_size": record.file_size,
            }
        except Exception as e:
            logger.error(f"Error retrieving file data: {e}")
            return None

    async def get_patient_records(
        self,
        db: AsyncSession,
        patient_id: UUID,
        record_type: Optional[RecordType] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[MedicalRecord]:
        """Get all medical records for a specific patient"""
        try:
            query = select(MedicalRecord).where(MedicalRecord.patient_id == patient_id)

            if record_type:
                query = query.where(MedicalRecord.record_type == record_type)

            query = (
                query.order_by(MedicalRecord.record_date.desc())
                .offset(skip)
                .limit(limit)
            )

            result = await db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting patient medical records: {e}")
            return []

    async def update_medical_record(
        self, db: AsyncSession, record_id: UUID, record_data: MedicalRecordUpdate
    ) -> Optional[MedicalRecord]:
        """Update medical record"""
        record = await self.get(db, record_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Medical record not found"
            )

        update_data = record_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)

        await db.commit()
        await db.refresh(record)

        logger.info(f"Updated medical record: {record_id}")
        return record

    async def delete_medical_record(self, db: AsyncSession, record_id: UUID) -> bool:
        """Delete medical record and associated file"""
        record = await self.get(db, record_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Medical record not found"
            )

        # Delete associated file if exists
        if record.file_path:
            await self.file_storage.delete_file(record.file_path)

        # Delete record from database
        await super().delete(db, record_id)

        logger.info(f"Deleted medical record: {record_id}")
        return True

    async def get_record_stats(
        self, db: AsyncSession, patient_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """Get medical record statistics"""
        try:
            from sqlalchemy import func

            query = select(func.count(MedicalRecord.id))

            if patient_id:
                query = query.where(MedicalRecord.patient_id == patient_id)

            result = await db.execute(query)
            total_records = result.scalar()

            # Count by record type
            type_query = select(
                MedicalRecord.record_type, func.count(MedicalRecord.id)
            ).group_by(MedicalRecord.record_type)

            if patient_id:
                type_query = type_query.where(MedicalRecord.patient_id == patient_id)

            type_result = await db.execute(type_query)
            records_by_type = {row[0]: row[1] for row in type_result}

            return {"total_records": total_records, "records_by_type": records_by_type}
        except Exception as e:
            logger.error(f"Error getting medical record stats: {e}")
            return {}


medical_record_service = MedicalRecordService()
