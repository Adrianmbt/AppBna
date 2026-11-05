"""Semilla de datos inicial para BnaSalud (Supabase).

Requisitos:
  1. Ejecutar antes las migraciones supabase/migrations/0001 → 0016 (SQL Editor).
  2. Tener las credenciales en el .env (SUPABASE_URL, SUPABASE_KEY).

Uso:
  venv\\Scripts\\python -m app.db.seed

El script es idempotente: puede re-ejecutarse (upserts).
La alternativa 100% SQL es supabase/seed.sql (mismo conjunto de datos).
Contraseña por defecto de los usuarios: BnaSalud2026!
Contraseña por defecto de los pacientes: Paciente2026! (se cambia por recuperación/correo)

La semilla cubre los ciclos de las fases recientes:
  • Fase 0: recetas en PENDIENTE / DESPACHADA / ENTREGADA / RECIBIDA
    (con entregada_por_id y recibida_paciente_id donde corresponde).
  • Fase 1 y 4: cada receta enlaza su consulta (recetas.consulta_id) y los
    despachos registran al farmacéutico (despacho_registros.despachado_por).
  • Fase 2: cola de pacientes con turnos en espera y en consulta (triaje).
"""
from __future__ import annotations

import uuid
from typing import Any

import bcrypt

from app.core.database import supabase

PASSWORD_HASH = "$2b$12$oV8tx83yd/n/1LOhB6.7q.t7Oi3Q2Hwtli5B.IplL/hxdlugMfyWO"

CARGOS: list[dict[str, Any]] = [
    {"id": 1, "nombre": "Superusuario", "departamento": "Administración"},
    {"id": 2, "nombre": "Médico", "departamento": "Asistencial"},
    {"id": 3, "nombre": "Farmacéutico", "departamento": "Farmacia"},
    {"id": 4, "nombre": "Enfermero", "departamento": "Asistencial"},
]

CLINICAS: list[dict[str, Any]] = [
    {"id": 1, "nombre": "Clínica del Niño", "codigo": "CLN-NINO", "parroquia": "El Carmen", "direccion": "Barcelona, Anzoátegui", "activo": True},
    {"id": 2, "nombre": "Clínica de los Trabajadores (CITAB)", "codigo": "CLN-CITAB", "parroquia": "El Carmen", "direccion": "Barcelona, Anzoátegui", "activo": True},
    {"id": 3, "nombre": "Clínica de la Mujer", "codigo": "CLN-MUJER", "parroquia": "San Cristóbal", "direccion": "Barcelona, Anzoátegui", "activo": True},
    {"id": 4, "nombre": "Centro Oncológico Municipal", "codigo": "CLN-ONCO", "parroquia": "El Carmen", "direccion": "Barcelona, Anzoátegui", "activo": True},
    {"id": 5, "nombre": "Jornadas de Salud Móviles", "codigo": "CLN-JORNADAS", "parroquia": "General", "direccion": "Atención Itinerante - Municipio Simón Bolívar", "activo": True},
]

ESPECIALIDADES: list[dict[str, Any]] = [
    {"id": 1, "nombre": "Medicina General", "descripcion": "Medicina de familia y prevención.", "icono": "stethoscope"},
    {"id": 2, "nombre": "Pediatría", "descripcion": "Cuidado integral para los más pequeños.", "icono": "child_care"},
    {"id": 3, "nombre": "Ginecología", "descripcion": "Atención ginecológica y obstetricia.", "icono": "female"},
    {"id": 4, "nombre": "Cardiología", "descripcion": "Diagnóstico y tratamiento cardiovascular.", "icono": "cardiology"},
    {"id": 5, "nombre": "Odontología", "descripcion": "Salud bucodental avanzada y estética.", "icono": "dentistry"},
    {"id": 6, "nombre": "Psicología", "descripcion": "Atención en salud mental y bienestar.", "icono": "psychology"},
    {"id": 7, "nombre": "Oncología", "descripcion": "Diagnóstico y tratamiento del cáncer.", "icono": "radiology"},
]

TURNOS: list[dict[str, Any]] = [
    {"nombre": "Guardia 24h", "hora_inicio": "00:00:00", "hora_fin": "23:59:00"},
    {"nombre": "Mañana", "hora_inicio": "07:00:00", "hora_fin": "13:00:00"},
    {"nombre": "Tarde", "hora_inicio": "13:00:00", "hora_fin": "19:00:00"},
    {"nombre": "Tarde Extendida", "hora_inicio": "13:00:00", "hora_fin": "21:00:00"},
]

PACIENTES: list[dict[str, Any]] = [
    {
        "tipo_cedula": "V", "cedula": "18234567", "nombre_completo": "Carlos Mendoza",
        "fecha_nacimiento": "1980-05-12", "telefono": "04141234567", "email": "carlos.mendoza@example.com",
        "tipo_sangre": "O+", "antecedentes_medicos": ["Hipertensión"], "alergias": ["Penicilina"],
        "numero_historia": "HIS-V18234567",
    },
    {
        "tipo_cedula": "V", "cedula": "12345678", "nombre_completo": "María Rodríguez",
        "fecha_nacimiento": "1985-03-22", "telefono": "04141337899", "email": "maria.rodriguez@example.com",
        "tipo_sangre": "A+", "antecedentes_medicos": ["Asma"], "alergias": [],
        "numero_historia": "HIS-V12345678",
    },
    {
        "tipo_cedula": "V", "cedula": "98765432", "nombre_completo": "Juan Pérez",
        "fecha_nacimiento": "1990-11-02", "telefono": "04241411122", "email": "juan.perez@example.com",
        "tipo_sangre": "B-", "antecedentes_medicos": [], "alergias": ["Sulfamidas"],
        "numero_historia": "HIS-V98765432",
    },
    {
        "tipo_cedula": "V", "cedula": "87654321", "nombre_completo": "Ana Rodríguez",
        "fecha_nacimiento": "1995-07-15", "telefono": "04241556677", "email": "ana.rodriguez@example.com",
        "tipo_sangre": "O-", "antecedentes_medicos": ["Diabetes gestacional"], "alergias": [],
        "numero_historia": "HIS-V87654321",
    },
    {
        "tipo_cedula": "V", "cedula": "76543210", "nombre_completo": "Pedro García",
        "fecha_nacimiento": "1978-01-30", "telefono": "04161788990", "email": "pedro.garcia@example.com",
        "tipo_sangre": "AB+", "antecedentes_medicos": ["Dislipidemia"], "alergias": [],
        "numero_historia": "HIS-V76543210",
    },
]

PERSONAL: list[dict[str, Any]] = [
    # Superusuario
    {"cedula": "99990010", "nombre": "Adrián", "apellido": "Bello", "especialidad": "Administración", "telefono": "+58 281 000 0001", "email": "admin@bnasalud.gob.ve", "cargo": "Superusuario", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 2},
    # Médicos (varios, distribuidos por centro)
    {"cedula": "11111111", "nombre": "Antonio", "apellido": "Valera", "especialidad": "Cardiología", "telefono": "+58 414 123 4567", "email": "antonio.valera@bnasalud.gob.ve", "cargo": "Médico", "status": "EN_GUARDIA", "estado": "ACTIVO", "clinica_id": 2},
    {"cedula": "22222222", "nombre": "María", "apellido": "González", "especialidad": "Pediatría", "telefono": "+58 414 222 3344", "email": "maria.gonzalez@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 1},
    {"cedula": "33333333", "nombre": "Luisa", "apellido": "Pérez", "especialidad": "Ginecología", "telefono": "+58 414 555 6677", "email": "luisa.perez@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 3},
    {"cedula": "55555555", "nombre": "Pedro", "apellido": "Sánchez", "especialidad": "Medicina General", "telefono": "+58 414 111 2233", "email": "pedro.sanchez@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 4},
    {"cedula": "66666666", "nombre": "Elena", "apellido": "Gómez", "especialidad": "Oncología", "telefono": "+58 414 444 5566", "email": "elena.gomez@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 4},
    {"cedula": "77777777", "nombre": "Ramón", "apellido": "Díaz", "especialidad": "Medicina General", "telefono": "+58 414 777 8899", "email": "ramon.diaz@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 5},
    {"cedula": "88888888", "nombre": "Jorge", "apellido": "Blanco", "especialidad": "Medicina General", "telefono": "+58 414 333 4455", "email": "jorge.blanco@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 1},
    {"cedula": "88888889", "nombre": "Sonia", "apellido": "Ramos", "especialidad": "Pediatría", "telefono": "+58 414 666 7788", "email": "sonia.ramos@bnasalud.gob.ve", "cargo": "Médico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 5},
    # Jefatura de farmacia (encargada del inventario y las alertas)
    {"cedula": "99990006", "nombre": "Yolanda", "apellido": "Contreras", "especialidad": "Farmacia", "telefono": "+58 412 200 0006", "email": "yolanda.contreras@bnasalud.gob.ve", "cargo": "Jefa de Farmacia", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 2},
    # Farmacéuticos (1 por centro de salud)
    {"cedula": "99990001", "nombre": "Carlos", "apellido": "Pereira", "especialidad": "Farmacia", "telefono": "+58 412 200 0001", "email": "carlos.pereira@bnasalud.gob.ve", "cargo": "Farmacéutico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 1},
    {"cedula": "99990002", "nombre": "María", "apellido": "Torres", "especialidad": "Farmacia", "telefono": "+58 412 200 0002", "email": "maria.torres@bnasalud.gob.ve", "cargo": "Farmacéutico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 2},
    {"cedula": "99990003", "nombre": "Luis", "apellido": "Hernández", "especialidad": "Farmacia", "telefono": "+58 412 200 0003", "email": "luis.hernandez@bnasalud.gob.ve", "cargo": "Farmacéutico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 3},
    {"cedula": "99990004", "nombre": "Ana", "apellido": "Castillo", "especialidad": "Farmacia", "telefono": "+58 412 200 0004", "email": "ana.castillo@bnasalud.gob.ve", "cargo": "Farmacéutico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 4},
    {"cedula": "99990005", "nombre": "Rosa", "apellido": "Medina", "especialidad": "Farmacia", "telefono": "+58 412 200 0005", "email": "rosa.medina@bnasalud.gob.ve", "cargo": "Farmacéutico", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 5},
    # Enfermeros
    {"cedula": "44444444", "nombre": "Carlos", "apellido": "Ruiz", "especialidad": "Enfermería", "telefono": "+58 414 888 9900", "email": "carlos.ruiz@bnasalud.gob.ve", "cargo": "Enfermero", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 2},
    {"cedula": "44444445", "nombre": "Laura", "apellido": "Mendoza", "especialidad": "Enfermería", "telefono": "+58 414 999 0011", "email": "laura.mendoza@bnasalud.gob.ve", "cargo": "Enfermero", "status": "DISPONIBLE", "estado": "ACTIVO", "clinica_id": 1},
]

MEDICAMENTOS: list[dict[str, Any]] = [
    {"id": 1, "nombre": "Amoxicilina 500mg", "presentacion": "Cápsula", "concentracion": "500 mg", "categoria": "Antibiótico", "stock_actual": 120, "stock_minimo": 30, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 2, "nombre": "Paracetamol 500mg", "presentacion": "Tableta", "concentracion": "500 mg", "categoria": "Analgésico", "stock_actual": 300, "stock_minimo": 50, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 3, "nombre": "Ibuprofeno 400mg", "presentacion": "Tableta", "concentracion": "400 mg", "categoria": "Antiinflamatorio", "stock_actual": 200, "stock_minimo": 40, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 4, "nombre": "Enalapril 10mg", "presentacion": "Tableta", "concentracion": "10 mg", "categoria": "Antihipertensivo", "stock_actual": 90, "stock_minimo": 20, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 5, "nombre": "Metformina 850mg", "presentacion": "Tableta", "concentracion": "850 mg", "categoria": "Antidiabético", "stock_actual": 150, "stock_minimo": 30, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 6, "nombre": "Salbutamol 100mcg", "presentacion": "Inhalador", "concentracion": "100 mcg", "categoria": "Broncodilatador", "stock_actual": 40, "stock_minimo": 10, "unidad": "inhalador", "unidad_medida": "inhalador"},
    {"id": 7, "nombre": "Losartán 50mg", "presentacion": "Tableta", "concentracion": "50 mg", "categoria": "Antihipertensivo", "stock_actual": 110, "stock_minimo": 25, "unidad": "unidad", "unidad_medida": "unidad"},
    {"id": 8, "nombre": "Vitamina C 500mg", "presentacion": "Tableta", "concentracion": "500 mg", "categoria": "Suplemento", "stock_actual": 500, "stock_minimo": 80, "unidad": "unidad", "unidad_medida": "unidad"},
]

CITAS: list[dict[str, Any]] = [
    {"centro_id": 2, "centro_salud": "Clínica de los Trabajadores (CITAB)", "especialidad": "Cardiología", "especialidad_id": 4, "fecha_cita": "2026-08-15", "hora_inicio": "08:30:00", "motivo": "Control cardiovascular", "origen": "cita_web", "estado": "pendiente", "codigo_confirmacion": "CITAB-2026-89A1"},
    {"centro_id": 2, "centro_salud": "Clínica de los Trabajadores (CITAB)", "especialidad": "Medicina General", "especialidad_id": 1, "fecha_cita": "2026-08-16", "hora_inicio": "10:00:00", "motivo": "Chequeo de rutina", "origen": "cita_web", "estado": "confirmada", "codigo_confirmacion": "CITAB-2026-8B2C"},
    {"centro_id": 1, "centro_salud": "Clínica del Niño", "especialidad": "Pediatría", "especialidad_id": 2, "fecha_cita": "2026-08-17", "hora_inicio": "09:15:00", "motivo": "Control pediátrico", "origen": "cita_web", "estado": "pendiente", "codigo_confirmacion": "NINO-2026-3C4D"},
    {"centro_id": 3, "centro_salud": "Clínica de la Mujer", "especialidad": "Ginecología", "especialidad_id": 3, "fecha_cita": "2026-08-19", "hora_inicio": "11:00:00", "motivo": "Control ginecológico", "origen": "cita_web", "estado": "pendiente", "codigo_confirmacion": "MUJER-2026-4D5E"},
]

RECETAS: list[dict[str, Any]] = [
    {
        "codigo_receta": "RX-2026-0892", "paciente_cedula": "V-18234567",
        "paciente_nombre": "Carlos Mendoza", "medico": "Antonio Valera",
        "estado": "PENDIENTE", "clinica_id": 2, "cita_id": "CITAB-2026-89A1",
        "fecha_emision": "2026-08-15 09:05:00",
    },
    {
        "codigo_receta": "RX-2026-0893", "paciente_cedula": "V-98765432",
        "paciente_nombre": "Juan Pérez", "medico": "María González",
        "estado": "DESPACHADA", "clinica_id": 1,
        "fecha_emision": "2026-08-16 10:20:00",
    },
    {
        "codigo_receta": "RX-2026-0894", "paciente_cedula": "V-12345678",
        "paciente_nombre": "María Rodríguez", "medico": "María González",
        "estado": "ENTREGADA", "clinica_id": 1, "cita_id": "NINO-2026-3C4D",
        "fecha_emision": "2026-08-16 11:00:00",
        "entregada_por": "Carlos Pereira", "entregada_at": "2026-08-16 11:40:00",
    },
    {
        "codigo_receta": "RX-2026-0895", "paciente_cedula": "V-87654321",
        "paciente_nombre": "Ana Rodríguez", "medico": "Luisa Pérez",
        "estado": "RECIBIDA", "clinica_id": 3, "cita_id": "MUJER-2026-4D5E",
        "fecha_emision": "2026-08-16 13:15:00",
        "entregada_por": "Luis Hernández", "entregada_at": "2026-08-16 13:50:00",
        "recibida_por_cedula": "87654321", "recibida_at": "2026-08-16 14:05:00",
    },
]

USUARIOS: list[dict[str, Any]] = [
    # Superusuario
    {"username": "abello", "rol": "superusuario", "personal_cedula": "99990010"},
    # Médicos
    {"username": "avalera", "rol": "medico", "personal_cedula": "11111111"},
    {"username": "mgonzalez", "rol": "medico", "personal_cedula": "22222222"},
    {"username": "lperez", "rol": "medico", "personal_cedula": "33333333"},
    {"username": "psanchez", "rol": "medico", "personal_cedula": "55555555"},
    {"username": "egomez", "rol": "medico", "personal_cedula": "66666666"},
    {"username": "rdiaz", "rol": "medico", "personal_cedula": "77777777"},
    {"username": "jblanco", "rol": "medico", "personal_cedula": "88888888"},
    {"username": "sramos", "rol": "medico", "personal_cedula": "88888889"},
    # Jefatura de farmacia (encargada del stock)
    {"username": "ycontreras", "rol": "jefe_farmacia", "personal_cedula": "99990006"},
    # Farmacéuticos (1 por centro)
    {"username": "cpereira", "rol": "farmaceutico", "personal_cedula": "99990001"},
    {"username": "mtorres", "rol": "farmaceutico", "personal_cedula": "99990002"},
    {"username": "lhernandez", "rol": "farmaceutico", "personal_cedula": "99990003"},
    {"username": "acastillo", "rol": "farmaceutico", "personal_cedula": "99990004"},
    {"username": "rmedina", "rol": "farmaceutico", "personal_cedula": "99990005"},
    # Enfermeros
    {"username": "cruiz", "rol": "enfermero", "personal_cedula": "44444444"},
    {"username": "lmendoza", "rol": "enfermero", "personal_cedula": "44444445"},
    # Pacientes
    {"username": "cmendoza", "rol": "paciente", "paciente_cedula": "18234567"},
    {"username": "mrodriguez", "rol": "paciente", "paciente_cedula": "12345678"},
    {"username": "jperez", "rol": "paciente", "paciente_cedula": "98765432"},
    {"username": "arodriguez", "rol": "paciente", "paciente_cedula": "87654321"},
    {"username": "pgarcia", "rol": "paciente", "paciente_cedula": "76543210"},
]

CONSULTAS: list[dict[str, Any]] = [
    {
        "id": "11111111-2222-3333-4444-555555555555",
        "cita_id": "CITAB-2026-89A1",
        "especialidad": "Cardiología",
        "medico_nombre": "Antonio Valera",
        "motivo_consulta": "Cefalea constante de 3 días",
        "examen_fisico": "Presión arterial 130/85. Paciente consciente, orientado.",
        "cie10_codigo": "I10",
        "cie10_descripcion": "Hipertensión esencial (primaria)",
        "tratamiento": "Enalapril 10mg cada 12 hrs",
        "recomendaciones": "Reposo por 48 hrs y baja ingesta de sal",
        "recetas": [{"nombre": "Enalapril 10mg", "posologia": "1 tableta cada 12 horas por 30 días"}],
        "laboratorios": [{"parametro": "Hemoglobina", "valor": "14.2 g/dL"}],
        "comprobante_ref": "ABH-99281",
    },
    {
        "id": "22222222-3333-4444-5555-666666666666",
        "cita_id": "NINO-2026-3C4D",
        "especialidad": "Pediatría",
        "medico_nombre": "María González",
        "motivo_consulta": "Control de crecimiento",
        "examen_fisico": "Peso y talla acordes a la edad. Sin hallazgos.",
        "cie10_codigo": "Z00.1",
        "cie10_descripcion": "Examen de salud de rutina del niño sano",
        "tratamiento": "Esquema de vacunación al día",
        "recomendaciones": "Próxima consulta en 3 meses",
        "recetas": [],
        "laboratorios": [],
        "comprobante_ref": "ABH-99290",
    },
]


def upsert(tabla: str, filas: list[dict[str, Any]], on_conflict: str) -> None:
    if not filas:
        return
    res = supabase.table(tabla).upsert(filas, on_conflict=on_conflict).execute()
    print(f"  {tabla:<18} {len(res.data)} filas")

def get_ids(tabla: str, cols: list[str]) -> list[dict[str, Any]]:
    res = supabase.table(tabla).select(",".join(cols)).execute()
    return res.data or []

def main() -> None:
    print("Semilla BnaSalud\n")

    print("[1/15] Cargos (RRHH)")
    upsert("cargos", CARGOS, "id")

    print("[2/15] Clínicas (centros de salud)")
    upsert("clinicas", CLINICAS, "codigo")
    clinicas_por_codigo = {c["codigo"]: c["id"] for c in get_ids("clinicas", ["id", "codigo"])}

    print("[3/15] Turnos (RRHH)")
    try:
        nombres_existentes = {t["nombre"] for t in get_ids("turnos", ["id", "nombre"])}
        faltantes = [
            {"id": i + 1, **t}
            for i, t in enumerate(TURNOS)
            if t["nombre"] not in nombres_existentes
        ]
        if faltantes:
            upsert("turnos", faltantes, "id")
        else:
            print("  turnos             ya existentes")
    except Exception as e:
        print("  turnos             ERROR:", e)

    print("[4/15] Especialidades")
    upsert("especialidades", ESPECIALIDADES, "id")

    print("[5/15] Medicamentos (inventario_medicamentos)")
    upsert("inventario_medicamentos", MEDICAMENTOS, "id")
    medicamentos_por_nombre = {
        m["nombre"]: m["id"] for m in get_ids("inventario_medicamentos", ["id", "nombre"])
    }

    print("[6/15] Personal (RRHH / médicos)")
    cargos_por_nombre = {c["nombre"]: c["id"] for c in get_ids("cargos", ["id", "nombre"])}
    personal: list[dict[str, Any]] = []
    for p in PERSONAL:
        fila = dict(p)
        fila["cargo_id"] = cargos_por_nombre[p["cargo"]]
        personal.append(fila)
    upsert("personal", personal, "cedula")
    personal_por_nombre = {
        f"{p['nombre']} {p['apellido']}": p["id"]
        for p in get_ids("personal", ["id", "nombre", "apellido"])
    }
    personal_por_cedula = {p["cedula"]: p["id"] for p in get_ids("personal", ["id", "cedula"])}

    print("[7/15] Pacientes (historias_clinicas)")
    pacientes: list[dict[str, Any]] = []
    for p in PACIENTES:
        fila = dict(p)
        fila["pin_hash"] = bcrypt.hashpw(b"Paciente2026!", bcrypt.gensalt()).decode()
        pacientes.append(fila)
    upsert("historias_clinicas", pacientes, "cedula")
    pacientes_por_cedula = {p["cedula"]: p["id"] for p in get_ids("historias_clinicas", ["id", "cedula"])}

    print("[8/15] Usuarios del sistema")
    usuarios: list[dict[str, Any]] = []
    for u in USUARIOS:
        fila = {
            "username": u["username"],
            "password_hash": PASSWORD_HASH,
            "rol": u["rol"],
            "activo": True,
        }
        if u.get("personal_cedula"):
            fila["personal_id"] = personal_por_cedula[u["personal_cedula"]]
        if u.get("paciente_cedula"):
            fila["paciente_id"] = pacientes_por_cedula[u["paciente_cedula"]]
        usuarios.append(fila)
    upsert("usuarios", usuarios, "username")

    print("[9/15] Stock por clínica")
    stock: list[dict[str, Any]] = []
    for clinica in CLINICAS:
        for m in MEDICAMENTOS:
            cantidad = max((m["stock_actual"] // 5) + ((clinica["id"] * 7 + m["id"] * 3) % 5), 2)
            stock.append({
                "clinica_id": clinica["id"],
                "medicamento_id": m["id"],
                "cantidad_actual": cantidad,
                "lote": f"LOTE-{clinica['codigo']}-{m['id']}",
            })
    supabase.table("stock_clinica").upsert(stock, on_conflict="clinica_id,medicamento_id,lote").execute()
    print(f"  stock_clinica      {len(stock)} filas")

    print("[10/15] Citas")
    paciente_por_cita = {
        "CITAB-2026-89A1": "18234567",
        "CITAB-2026-8B2C": "98765432",
        "NINO-2026-3C4D": "12345678",
        "MUJER-2026-4D5E": "87654321",
    }
    citas: list[dict[str, Any]] = []
    id_por_codigo = {
        c["codigo_confirmacion"]: c["id"] for c in get_ids("citas", ["id", "codigo_confirmacion"])
    }
    for cita in CITAS:
        fila = dict(cita)
        fila["paciente_id"] = pacientes_por_cedula[paciente_por_cita[cita["codigo_confirmacion"]]]
        if cita["codigo_confirmacion"] in id_por_codigo:
            fila["id"] = id_por_codigo[cita["codigo_confirmacion"]]
        else:
            fila["id"] = str(uuid.uuid4())
        citas.append(fila)
    upsert("citas", citas, "id")

    print("[11/15] Consultas (historial clínico)")
    paciente_por_consulta = {
        "CITAB-2026-89A1": "18234567",
        "NINO-2026-3C4D": "12345678",
    }
    consultas: list[dict[str, Any]] = []
    for consulta in CONSULTAS:
        fila = dict(consulta)
        fila["paciente_id"] = pacientes_por_cedula[paciente_por_consulta[consulta["cita_id"]]]
        fila["medico_id"] = personal_por_nombre[consulta["medico_nombre"]]
        consultas.append(fila)
    upsert("consultas", consultas, "id")
    consultas_por_cita = {c["cita_id"]: c["id"] for c in consultas}

    print("[12/15] Recetas")
    recetas: list[dict[str, Any]] = []
    for receta in RECETAS:
        fila = dict(receta)
        fila["medico_id"] = personal_por_nombre[receta["medico"]]
        if receta.get("cita_id"):
            fila["consulta_id"] = consultas_por_cita.get(receta["cita_id"])
        fila.pop("cita_id", None)
        if receta.get("entregada_por"):
            fila["entregada_por_id"] = personal_por_nombre[receta["entregada_por"]]
        fila.pop("entregada_por", None)
        if receta.get("recibida_por_cedula"):
            fila["recibida_paciente_id"] = pacientes_por_cedula[receta["recibida_por_cedula"]]
        fila.pop("recibida_por_cedula", None)
        recetas.append(fila)
    upsert("recetas", recetas, "codigo_receta")
    recetas_por_codigo = {r["codigo_receta"]: r["id"] for r in get_ids("recetas", ["id", "codigo_receta"])}

    print("[13/15] Detalles de recetas")
    detalles = [
        {"id": 901, "receta_id": recetas_por_codigo["RX-2026-0892"], "medicamento_id": medicamentos_por_nombre["Amoxicilina 500mg"],
         "cantidad_prescrita": 21, "cantidad_despachada": 0,
         "posologia": "1 cápsula cada 8 horas por 7 días"},
        {"id": 902, "receta_id": recetas_por_codigo["RX-2026-0893"], "medicamento_id": medicamentos_por_nombre["Paracetamol 500mg"],
         "cantidad_prescrita": 20, "cantidad_despachada": 20,
         "posologia": "1 tableta cada 6 horas por 5 días"},
        {"id": 903, "receta_id": recetas_por_codigo["RX-2026-0894"], "medicamento_id": medicamentos_por_nombre["Amoxicilina 500mg"],
         "cantidad_prescrita": 14, "cantidad_despachada": 14,
         "posologia": "1 cápsula cada 12 horas por 7 días"},
        {"id": 904, "receta_id": recetas_por_codigo["RX-2026-0895"], "medicamento_id": medicamentos_por_nombre["Enalapril 10mg"],
         "cantidad_prescrita": 30, "cantidad_despachada": 30,
         "posologia": "1 tableta cada 12 horas por 30 días"},
    ]
    upsert("receta_detalles", detalles, "id")

    print("[14/15] Órdenes de estudios + despachos registrados")
    try:
        ordenes = [{
            "id": "33333333-4444-5555-6666-777777777777",
            "paciente_id": pacientes_por_cedula["18234567"],
            "consulta_id": consultas[0]["id"],
            "cita_id": "CITAB-2026-89A1",
            "origen": "consulta",
            "estado": "solicitada",
            "medico_id": personal_por_nombre["Antonio Valera"],
            "medico_nombre": "Antonio Valera",
            "especialidad": "Cardiología",
            "prioridad": "normal",
            "estudios": [{"tipo": "laboratorio", "nombre": "Perfil lipídico", "estado": "solicitada"}],
            "comprobante_orden": "OE-2026-0001",
        }]
        upsert("ordenes_estudios", ordenes, "id")
        despachos = [
            {"id": 1, "receta_id": recetas_por_codigo["RX-2026-0893"],
             "despachado_por": personal_por_nombre["Carlos Pereira"],
             "observaciones": "Despacho completo de paracetamol (20 unidades)",
             "fecha_despacho": "2026-08-16 12:10:00"},
            {"id": 2, "receta_id": recetas_por_codigo["RX-2026-0894"],
             "despachado_por": personal_por_nombre["Carlos Pereira"],
             "observaciones": "Despacho de amoxicilina (14 unidades)",
             "fecha_despacho": "2026-08-16 11:15:00"},
            {"id": 3, "receta_id": recetas_por_codigo["RX-2026-0895"],
             "despachado_por": personal_por_nombre["Luis Hernández"],
             "observaciones": "Despacho de enalapril (30 unidades)",
             "fecha_despacho": "2026-08-16 13:30:00"},
        ]
        upsert("despacho_registros", despachos, "id")
    except Exception as e:
        print("  ordenes/despacho   ERROR:", e)

    print("[15/15] Cola de pacientes (triaje)")
    try:
        cola = [
            {"token": "C-10001", "paciente_id": pacientes_por_cedula["18234567"],
             "paciente_cedula": "V-18234567", "paciente_nombre": "Carlos Mendoza",
             "clinica_id": 2, "motivo": "consulta", "prioridad": 3,
             "estado": "EN_CONSULTA", "medico_id": personal_por_nombre["Antonio Valera"],
             "creado_en": "2026-08-17 08:10:00+00", "iniciado_en": "2026-08-17 08:15:00+00"},
            {"token": "C-10002", "paciente_id": pacientes_por_cedula["12345678"],
             "paciente_cedula": "V-12345678", "paciente_nombre": "María Rodríguez",
             "clinica_id": 2, "motivo": "consulta", "prioridad": 2,
             "estado": "EN_ESPERA", "creado_en": "2026-08-17 08:20:00+00"},
            {"token": "C-10003", "paciente_id": pacientes_por_cedula["87654321"],
             "paciente_cedula": "V-87654321", "paciente_nombre": "Ana Rodríguez",
             "clinica_id": 2, "motivo": "emergencia", "prioridad": 1,
             "estado": "EN_ESPERA", "creado_en": "2026-08-17 08:25:00+00"},
        ]
        upsert("cola_pacientes", cola, "token")
    except Exception as e:
        print("  cola_pacientes     ERROR:", e)

    print("\nSemilla completada.")


if __name__ == "__main__":
    main()
