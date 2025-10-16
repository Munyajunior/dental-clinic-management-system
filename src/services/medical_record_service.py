# src/services/medical_record_service.py (Fixed SecureFileStorage)
import os
import hashlib
from typing import List, Optional, Dict, Any
from uuid import UUID
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from models.medical_record import MedicalRecord, RecordType
from models.patient import Patient
from models.user import User
from schemas.medical_record_schemas import MedicalRecordCreate, MedicalRecordUpdate
from utils.logger import setup_logger
from .base_service import BaseService
import aiofiles
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import secrets
from core.config import settings

logger = setup_logger("MEDICAL_RECORD_SERVICE")


class SecureFileStorage:
    """Secure file storage for medical records with AES-256 encryption"""

    def __init__(self):
        self.storage_path = settings.MEDICAL_RECORDS_STORAGE_PATH

        # Get the hexadecimal AES key from settings
        hex_key = settings.FILE_ENCRYPTION_KEY

        if not hex_key:
            logger.warning("FILE_ENCRYPTION_KEY not set, generating temporary key")
            # Generate a random 256-bit (32-byte) key and store as hex
            hex_key = secrets.token_hex(32)
            logger.warning(f"Generated temporary key: {hex_key}")

        # Convert hex key to bytes
        try:
            self.encryption_key = bytes.fromhex(hex_key)
            if len(self.encryption_key) != 32:  # 256 bits = 32 bytes
                raise ValueError("AES-256 key must be 32 bytes (64 hex characters)")
        except ValueError as e:
            logger.error(f"Invalid encryption key format: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid encryption key configuration",
            )

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

    def _pad_data(self, data: bytes) -> bytes:
        """Pad data to be compatible with AES block size"""
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        return padder.update(data) + padder.finalize()

    def _unpad_data(self, data: bytes) -> bytes:
        """Unpad data after decryption"""
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        return unpadder.update(data) + unpadder.finalize()

    async def store_file(
        self, record_id: UUID, file_name: str, file_data: bytes
    ) -> Dict[str, Any]:
        """Store file securely with AES-256 encryption and integrity checks"""
        try:
            file_path = self._generate_file_path(record_id, file_name)
            checksum = self._generate_checksum(file_data)

            # Generate random IV (Initialization Vector)
            iv = secrets.token_bytes(16)  # 128 bits for AES

            # Create cipher and encrypt
            cipher = Cipher(
                algorithms.AES(self.encryption_key),
                modes.CBC(iv),
                backend=default_backend(),
            )
            encryptor = cipher.encryptor()

            # Pad and encrypt data
            padded_data = self._pad_data(file_data)
            encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

            # Prepend IV to encrypted data (IV doesn't need to be secret)
            final_data = iv + encrypted_data

            # Write encrypted file
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(final_data)

            file_size = len(file_data)

            logger.info(f"Stored secure file: {file_path} ({file_size} bytes)")

            return {
                "file_path": file_path,
                "file_size": file_size,
                "checksum": checksum,
                "encrypted": True,
                "algorithm": "AES-256-CBC",
            }

        except Exception as e:
            logger.error(f"Error storing file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store medical record file",
            )

    async def retrieve_file(self, file_path: str) -> bytes:
        """Retrieve and decrypt file using AES-256"""
        try:
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
                )

            # Read encrypted file
            async with aiofiles.open(file_path, "rb") as f:
                encrypted_data_with_iv = await f.read()

            # Extract IV (first 16 bytes) and encrypted data
            iv = encrypted_data_with_iv[:16]
            encrypted_data = encrypted_data_with_iv[16:]

            # Create cipher and decrypt
            cipher = Cipher(
                algorithms.AES(self.encryption_key),
                modes.CBC(iv),
                backend=default_backend(),
            )
            decryptor = cipher.decryptor()

            # Decrypt and unpad data
            decrypted_padded_data = (
                decryptor.update(encrypted_data) + decryptor.finalize()
            )
            decrypted_data = self._unpad_data(decrypted_padded_data)

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
                # Overwrite with random data before deletion
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

    async def get_medical_record_with_relations(
        self, db: AsyncSession, record_id: UUID
    ) -> Optional[MedicalRecord]:
        """Get medical record with related data (patient, creator)"""
        try:
            result = await db.execute(
                select(MedicalRecord)
                .join(Patient, MedicalRecord.patient_id == Patient.id)
                .join(User, MedicalRecord.created_by == User.id)
                .where(MedicalRecord.id == record_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting medical record with relations: {e}")
            return None


medical_record_service = MedicalRecordService()
