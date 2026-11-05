# AppBna — Backend del portal público de pacientes (BnaSalud)

Este repositorio contiene únicamente el **backend del portal público del paciente**, el que se despliega en **Render** y atiende al frontend desplegado en **Vercel** (`https://saludbarcelona.vercel.app`).

Es un repositorio independiente del sistema clínico interno (`interno/`): no comparten modelos, componentes ni base de datos.

## Estructura

```
app/              # Código FastAPI del portal público (imports `from app...`)
requirements.txt  # Dependencias de producción
Dockerfile        # Imagen del contenedor (Render / Railway)
.dockerignore     # Qué no se copia a la imagen
render.yaml       # Blueprint de Render
.env.example      # Plantilla de variables de entorno (no subir .env real)
supabase/migrations/0025_citas_fecha_opcional.sql  # Migración de nulabilidad de citas
```

## Despliegue en Render

1. Subir este repositorio a GitHub (rama principal).
2. En Render: *New → Blueprint*, elegir el repositorio y *Apply*. `render.yaml` define el servicio `bnasalud-api` (plan free, Docker, health check `/api/v1/health`).
3. En el panel de Render, definir las variables marcadas como `sync: false`:
   - `SUPABASE_URL`: `https://unvtznfvbdqzsmtlvqkf.supabase.co`
   - `SUPABASE_KEY`: la **`service_role` key** de Supabase (no la `anon`; solo en el backend, nunca en Vercel).
   - `CORS_ORIGINS`: `https://saludbarcelona.vercel.app`
   - `JWT_SECRET`: secreto de 32+ caracteres (Render puede generarlo).
   - `TZ`: `America/Caracas` (ya definido en render.yaml).
   - `ENVIRONMENT`: `production`
   - `ENABLE_SCHEDULER`: `false` (plan free sin proceso vivo).
4. Render inyecta `$PORT`; el `CMD` del Dockerfile lo respeta.

## Base de datos (Supabase) — paso obligatorio antes del primer despliegue

El portal y el sistema interno usan bases distintas. Las migraciones del portal viven en `supabase/migrations/` y se aplican **a mano, en orden numérico, desde el SQL Editor de Supabase**.

Antes de recibir solicitudes de cita, aplicar:

```
supabase/migrations/0025_citas_fecha_opcional.sql
```

Esta migración relaja el `NOT NULL` de `citas.fecha_cita` y `citas.hora_inicio` para que el paciente pueda solicitar una cita **sin elegir fecha** (solo centro + especialidad). La recepción del sistema interno asigna después el médico, la fecha y la hora.

## Flujo de citas (portal → recepción)

1. Paciente elige **centro + especialidad** (+ motivo opcional) y envía `POST /citas/solicitar`.
2. La cita se crea en estado `pendiente` con `fecha_cita = NULL` y `hora_inicio = NULL`.
3. Recepción (sistema interno) lista las solicitudes por `centro_id` y confirma con `PATCH /citas/{id}/asignar` (médico, fecha, hora), pasando la cita a `confirmada`.

## Variables de entorno (copiar `.env.example` a `.env` solo en local)

Ver `.env.example`. Nunca subir `.env` al repositorio.

## Notas

- El frontend en Vercel no habla con Supabase: toda la comunicación va por `VITE_API_URL` → este backend en Render.
- Plan free de Render: la instancia se duerme tras inactividad; la primera petición tarda 30–60 s (el frontend timeout es 15 s, considerar ajustarlo o usar un servicio siempre encendido para producción estable).
- Sin SMTP configurado, la recuperación de contraseña no envía código por correo (solo devuelve en `development`).
