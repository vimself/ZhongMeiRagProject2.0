from __future__ import annotations

from pydantic import BaseModel


class PdfSignRequest(BaseModel):
    document_id: str


class PdfSignResponse(BaseModel):
    token: str
    expires_at: str
    document_id: str


class AssetSignRequest(BaseModel):
    asset_id: str


class AssetSignResponse(BaseModel):
    token: str
    expires_at: str
    asset_id: str
    document_id: str
    url: str
