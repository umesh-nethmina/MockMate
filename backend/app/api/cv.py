from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import CV, User
from app.tools.cv_parser import CVParseError, extract_text

router = APIRouter(prefix="/cv", tags=["cv"])


class CVOut(BaseModel):
    id: int
    file_name: str
    chars: int
    truncated: bool = False
    preview: str
    uploaded_at: datetime


def _out(cv: CV, truncated: bool = False) -> CVOut:
    return CVOut(
        id=cv.id,
        file_name=cv.file_name,
        chars=len(cv.extracted_text),
        truncated=truncated,
        preview=cv.extracted_text[:300],
        uploaded_at=cv.uploaded_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_cv(file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CVOut:
    """FR-06: PDF up to 5 MB; only the extracted text is kept, the file itself is discarded."""
    settings = get_settings()
    name = (file.filename or "cv.pdf")[:255]
    if not name.lower().endswith(".pdf") or file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Please upload your CV as a PDF file.")
    data = await file.read(settings.cv_max_bytes + 1)
    await file.close()
    if len(data) > settings.cv_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The PDF is larger than 5 MB.")
    try:
        parsed = extract_text(data, settings.cv_max_chars)
    except CVParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    finally:
        del data  # not stored: only the extracted text is saved; the upload buffer is freed after the request

    cv = CV(user_id=user.id, file_name=name, extracted_text=parsed.text)
    db.add(cv)
    db.commit()
    return _out(cv, parsed.truncated)


@router.get("")
def list_cvs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[CVOut]:
    rows = db.scalars(select(CV).where(CV.user_id == user.id).order_by(CV.uploaded_at.desc()))
    return [_out(cv) for cv in rows]


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cv(cv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    cv = db.get(CV, cv_id)
    if cv is None or cv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV not found")
    db.delete(cv)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
