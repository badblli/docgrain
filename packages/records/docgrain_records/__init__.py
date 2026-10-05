"""Opt-in hospitality extraction, verified evidence, and JSON Schema contracts."""

from .extractor import build_messages, extract, verify_response
from .model import ChatClient, ModelResponseError
from .models import (
    Activity,
    Contact,
    Evidence,
    ExtractionResult,
    Facility,
    FieldValue,
    Outlet,
    Policy,
    Property,
    RoomType,
    ServicePrice,
    hospitality_schema,
)

__all__ = [
    "Activity", "ChatClient", "Contact", "Evidence", "ExtractionResult", "Facility",
    "FieldValue", "ModelResponseError", "Outlet", "Policy", "Property", "RoomType",
    "ServicePrice", "build_messages", "extract", "hospitality_schema", "verify_response",
]
