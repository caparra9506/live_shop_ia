# LiveShop AI

Servicio nuevo, separado de `live_shop_back`/`live_shop_front`, que orquesta el
agente de IA de WhatsApp por tienda usando LangGraph. Reemplaza (progresivamente)
al workflow `COMPRE_PUES_SISTEMA_N8N` de n8n, resolviendo el problema de que hoy
todas las tiendas comparten un solo número de WhatsApp.

Ver el plan completo en `bubbly-forging-iverson.md` (guardado por Claude Code) para
contexto de por qué se construyó así y qué queda pendiente para fases futuras.

## Estructura

- `backend/` — FastAPI + LangGraph + SQLAlchemy (Python 3.12). Ver `backend/app/`.
- `frontend/` — React + Vite + Tailwind, panel para conectar WhatsApp por tienda
  y ver conversaciones.
- `docker-compose.yml` — despliegue en el server (mismo patrón que `/opt/liveshop/`).

## Desarrollo local

### Backend

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env  # y completar credenciales reales
uvicorn app.main:app --reload
```

Necesita llegar a:
- Postgres propio (`liveshop-ai-db`) — para desarrollo local, levantar un Postgres cualquiera y apuntar `.env` ahí.
- MySQL de LiveShop de solo lectura — por seguridad, mejor usar un tunel SSH al server nuevo (`2.24.139.178`) en vez de credenciales de producción sueltas en el laptop.
- Evolution API y Chatwoot del server — igual, mejor por tunel SSH mientras se prueba.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Abre en `http://localhost:5175`. El login usa el mismo usuario/contraseña del
admin de LiveShop (pega contra `VITE_LIVESHOP_API_URL`).

## Pendiente (fase 2, documentado en el plan)

- Editor de prompt del agente desde el panel.
- Migrar los webhooks simples de n8n (`GUIA_N8N`, `CART_EXPIRED`, `OTP_WEBHOOK`).
- Completar el ruteo real a Chatwoot por intención (`route_to_chatwoot` en
  `backend/app/graph/nodes.py` tiene el hook, falta el mapeo de inbox por tienda
  y las labels reales).
- Confirmar el SQL real de búsqueda de usuario/tiktok-user (`mysql_tools.py` tiene
  un stub marcado `NotImplementedError`).
- Arreglar el JWT secret hardcodeado (`abc123`) en el backend NestJS — hallazgo de
  seguridad aparte, no se tocó porque no era parte de este pedido.
