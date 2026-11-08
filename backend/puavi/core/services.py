"""Construye los clientes de servicios externos a partir de la configuración."""

from __future__ import annotations

from pathlib import Path

from puavi.core.config import _Base
from puavi.integrations.storage import LocalStorage, Storage, SupabaseStorage


def build_storage(s: _Base) -> Storage | None:
    if s.supabase_url and s.supabase_anon_key and s.storage_email and s.storage_password:
        return SupabaseStorage(
            url=s.supabase_url,
            anon_key=s.supabase_anon_key.get_secret_value(),
            email=s.storage_email,
            password=s.storage_password.get_secret_value(),
        )
    if s.local_media_dir:
        return LocalStorage(Path(s.local_media_dir))
    return None
