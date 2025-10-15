import os
import uuid
import base64
from fastapi import HTTPException
from datetime import datetime
from typing import Optional

IMAGE_UPLOAD_DIR = "uploads/images"


def save_image(base64_data: str, subfolder: str, name: Optional[str] = None) -> str:
    """
    Save base64 image data to filesystem and return file path

    Args:
        base64_data: Base64 encoded image string (with or without data URL prefix)
        subfolder: Subfolder within the image upload directory
        name: Optional name of the patient/user for filename generation

    Returns:
        str: Path to the saved image file
    """
    try:
        # Ensure upload directory exists
        os.makedirs(os.path.join(IMAGE_UPLOAD_DIR, subfolder), exist_ok=True)

        # Extract image data and format
        if base64_data.startswith("data:"):
            # Handle data URL format: data:image/png;base64,...
            header, encoded = base64_data.split(",", 1)
            image_format = header.split("/")[1].split(";")[0]
        else:
            # Assume it's raw base64, default to jpg
            encoded = base64_data
            image_format = "jpg"

        # Generate filename with current date and name
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")

        if name:
            # Clean the name for filename use (remove special characters)
            clean_name = "".join(
                c for c in name if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            clean_name = clean_name.replace(" ", "_").replace("-", "_")[
                :50
            ]  # Limit length
            filename = (
                f"{current_date}_{clean_name}_{uuid.uuid4().hex[:8]}.{image_format}"
            )
        else:
            filename = f"{current_date}_{uuid.uuid4().hex}.{image_format}"

        filepath = os.path.join(IMAGE_UPLOAD_DIR, subfolder, filename)

        # Save image
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(encoded))

        return filepath

    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid base64 image data: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Image processing failed: {str(e)}"
        )


def delete_image(filepath: str):
    """
    Delete an image file from the filesystem

    Args:
        filepath: Path to the image file to delete
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"Error deleting image: {str(e)}")
