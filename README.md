# Catálogo de aparelhos

API **FastAPI** + interface **React** (Vite).

## Backend

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Configure .env (PostgreSQL, etc.)
python run_web.py
```

API em `http://127.0.0.1:8000` — documentação em `/docs`.

## Frontend (React)

Em desenvolvimento o Vite faz **proxy** de `/api` para o backend na porta 8000.

```bash
cd frontend
npm install
npm run dev
```

Abra `http://127.0.0.1:5173`.

## Produção (servir React pelo FastAPI)

```bash
cd frontend && npm run build && cd ..
python run_web.py
```

Com `frontend/dist` presente, o FastAPI serve a SPA em `/` e repassa `/api/*` para as rotas JSON. Variável opcional **`CORS_ORIGINS`**: lista separada por vírgulas de origens permitidas (padrão inclui o Vite em 5173).

## Deploy no Render (API + React, sem crawlers)

1. Envie o repositório para o GitHub.
2. No [Render](https://render.com): **New → Blueprint** (ou Web Service) e use o `render.yaml`, ou configure manualmente:
   - **Build:** `pip install -r requirements-prod.txt && cd frontend && npm ci && npm run build`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Variáveis de ambiente no painel — **use o mesmo Supabase do `.env` local** (recomendado):
   - `DB_HOST=aws-1-us-east-1.pooler.supabase.com` (ou o host do seu projeto)
   - `DB_PORT=5432`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`, `DB_SSL=true`
   - **Não** use só `dpg-xxxxx-a` como host (hostname interno do Postgres do Render incompleto → erro DNS).
   - Se usar Postgres **no Render**, cole a **External Database URL** em `DATABASE_URL` (host termina em `.region-postgres.render.com`), não a URL “Internal”.
   - Se existir `DATABASE_URL` **e** `DB_HOST`, `DATABASE_URL` tem prioridade — apague a errada ou corrija-a.
4. Crawlers ficam **desligados** no Render (`RENDER=true` ou `ENABLE_CRAWLERS=0`). Popule o banco rodando crawlers na sua máquina com `pip install -r requirements.txt`.

Para forçar crawlers na API (só local, em geral): `ENABLE_CRAWLERS=1`. Para testar modo produção localmente: `ENABLE_CRAWLERS=0 uvicorn app.main:app --host 127.0.0.1 --port 8000`.
