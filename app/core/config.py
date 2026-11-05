from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRETO_JWT_POR_DEFECTO = "bna-salud-cambiar-en-produccion-por-un-secreto-largo"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Sistema de Salud Barcelona - API Backend"
    API_V1_STR: str = "/api/v1"

    # "development" o "production". El Dockerfile fija production; en local el
    # .env lo deja en development (o no lo define y se asume development).
    ENVIRONMENT: str = "development"

    # Cadena directa a PostgreSQL. El portal NO la usa (todo va por el cliente
    # Supabase); solo la consumen scripts/restore_db.py y docker-compose.yml.
    DATABASE_URL: str = ""

    # Credenciales Supabase: son las dos variables imprescindibles del backend.
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # Google Gemini / GCP (RAG, opcional)
    GOOGLE_API_KEY: str = ""

    # CORS: orígenes permitidos separados por coma. "*" solo para desarrollo.
    CORS_ORIGINS: str = "*"
    # Regex opcional para orígenes cambiantes, p. ej. los previews de Vercel:
    #   CORS_ORIGIN_REGEX=^https://[a-z0-9-]+\.vercel\.app$
    CORS_ORIGIN_REGEX: str = ""

    # Autenticación (JWT)
    JWT_SECRET: str = SECRETO_JWT_POR_DEFECTO
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRACION_MINUTOS: int = 480  # 8 horas
    # Vigencia del código de restablecimiento de contraseña (6 dígitos).
    RECUPERACION_EXPIRACION_MINUTOS: int = 15

    # Recordatorios de cita cada hora (APScheduler). Requiere un proceso vivo:
    # déjalo en true en Railway/Render y en false en plataformas serverless.
    ENABLE_SCHEDULER: bool = True

    # SMTP (Fase 3): bienvenida y restablecimiento de contraseña por correo.
    # Si SMTP_HOST está vacío, no se envía nada.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def es_produccion(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in ("production", "prod")

    @property
    def origenes_cors(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validar_produccion(self) -> "Settings":
        """Falla al arrancar si el despliegue queda inseguro o sin base de datos.

        Es preferible un contenedor que no arranca con un mensaje claro a uno
        que sirve el portal con un JWT falsificable o sin Supabase.
        """
        if not self.es_produccion:
            return self

        problemas: list[str] = []
        if not self.SUPABASE_URL or not self.SUPABASE_KEY:
            problemas.append(
                "SUPABASE_URL y SUPABASE_KEY son obligatorias (clave service_role)."
            )
        if (
            self.JWT_SECRET == SECRETO_JWT_POR_DEFECTO
            or len(self.JWT_SECRET) < 32
        ):
            problemas.append(
                "JWT_SECRET debe ser un secreto propio de al menos 32 caracteres "
                '(genéralo con: python -c "import secrets; print(secrets.token_urlsafe(48))").'
            )
        if not self.origenes_cors or "*" in self.origenes_cors:
            problemas.append(
                "CORS_ORIGINS debe listar el dominio del portal en Vercel "
                "(por ejemplo https://tu-portal.vercel.app)."
            )

        if problemas:
            detalle = "\n  - ".join(problemas)
            raise ValueError(
                "Configuración de producción inválida:\n  - " + detalle
            )
        return self


settings = Settings()
