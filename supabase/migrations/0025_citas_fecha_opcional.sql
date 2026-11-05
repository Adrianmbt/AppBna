-- ============================================================
-- BnaSalud — Migración 0025
-- El paciente ya no elige fecha en el portal público: solo
-- centro y especialidad. La recepción del sistema interno
-- asigna el médico, la fecha y la hora al confirmar.
--
-- Por eso una solicitud pendiente puede no tener fecha ni hora
-- todavía. Se relaja el NOT NULL de `citas`.
--
-- Importante: aplicar esta migración en la base de datos que
-- comparten el portal (Supabase) y el sistema interno. Si cada
-- uno usa una base distinta, el sistema interno nunca verá las
-- solicitudes creadas desde el portal.
--
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
-- ============================================================

ALTER TABLE public.citas
  ALTER COLUMN fecha_cita DROP NOT NULL;

ALTER TABLE public.citas
  ALTER COLUMN hora_inicio DROP NOT NULL;

COMMENT ON COLUMN public.citas.fecha_cita IS
  'Fecha confirmada de la cita. NULL mientras recepción no la asigne (solicitud pendiente del portal).';

COMMENT ON COLUMN public.citas.hora_inicio IS
  'Hora confirmada de la cita. NULL mientras recepción no la asigne (solicitud pendiente del portal).';
