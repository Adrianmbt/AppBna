try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None

from app.core.config import settings

_client: Client | None = None


def get_supabase_client() -> Client | None:
    """Retorna una instancia única (singleton) del cliente Supabase si las credenciales existen."""
    global _client
    if _client is None:
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            except Exception:
                _client = None
        else:
            _client = None
    return _client


# Instancia singleton para consultas directas en toda la app (None si no hay Supabase).
supabase: Client | None = get_supabase_client()
