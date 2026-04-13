# Scrapper Threehouse + Barceló Portugal

Colecta precios por noche de **Three House Hotel (Funchal)** y **todos los Barceló de Portugal** y los publica en Google Sheets + un dashboard en Vercel.

```
┌──────────────────────────┐   scrape every 4h   ┌──────────────────┐    read (ISR 5min)    ┌──────────────────┐
│  GitHub Actions (cron)   │ ──────────────────▶ │  Google Sheets   │ ─────────────────────▶│  Vercel Next.js  │
│  Python + Playwright     │                     │  (source of      │                       │  Dashboard        │
│  src/ (scraper)          │                     │   truth)         │                       │  web/             │
└──────────────────────────┘                     └──────────────────┘                       └──────────────────┘
         ▲                                                                                           │
         └────────────── POST /api/refresh (workflow_dispatch) ─────────────────────────────────────┘
```

- **Threehouse** — motor Mirai (hotel id `100380501`). Precios capturados de `twin.mirai.com` mediante interceptación de respuestas en Playwright.
- **Barceló** — motor propio. Hoteles de Portugal descubiertos automáticamente; cada calendario se pide a `reservation-api.barcelo.com` a través del contexto del browser (CSRF + Incapsula heredados de la sesión).
- **Google Sheet** — `1HPyd0LnqI7c1eKKY4gGQcQ__ct0hnVZxkUaOeEYAJKY`, pestaña `gid=1379799510`. Se sobrescribe en cada ejecución.
- **Dashboard** — `web/` — tabla, calendario heatmap, gráfico de precio medio mensual y comparador Threehouse vs Barceló.

## Estructura del repo

```
.
├── src/                    # Python scraper (worker)
├── web/                    # Next.js 14 dashboard (Vercel)
├── .github/workflows/      # Cron + workflow_dispatch
├── requirements.txt
└── README.md
```

---

## 1. Correr el scraper en local

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

### Credenciales Google Sheets

1. Crea un service account en Google Cloud, activa **Google Sheets API** y **Google Drive API**, descarga la JSON key.
2. Guárdala como `credentials/service_account.json`.
3. Comparte la Sheet con el email del service account (**Editor**). Es el fallo #1 la primera vez.

### Comandos

```bash
python -m src.main             # scrape completo + escribe a Sheets
python -m src.main --dry-run   # scrape pero no escribe
python -m src.main --only threehouse
python -m src.main --only barcelo
python -m src.main --rediscover   # fuerza redescubrir hoteles Barceló PT
```

---

## 2. GitHub Actions (worker automático)

Archivo: `.github/workflows/scrape.yml` — corre cada 4h y expone `workflow_dispatch` para disparos manuales.

### Configuración del repo en GitHub

**Secrets** (`Settings → Secrets and variables → Actions → New repository secret`):

- `GOOGLE_SERVICE_ACCOUNT_JSON` → pega el JSON completo del service account (una sola línea vale).

**Variables** (`Settings → Secrets and variables → Actions → Variables`):

- `GOOGLE_SHEET_ID` = `1HPyd0LnqI7c1eKKY4gGQcQ__ct0hnVZxkUaOeEYAJKY`
- `GOOGLE_SHEET_GID` = `1379799510`

Primer run: `Actions → scrape → Run workflow` (manual). Si pasa, el cron se encarga en adelante.

---

## 3. Dashboard en Vercel

Directorio: `web/`. Next.js 14 App Router + Tailwind + Recharts.

### Vistas

- `/` — Tabla filtrable (por marca, hotel, disponibilidad) + exportar CSV.
- `/heatmap` — Calendario coloreado por precio (uno por mes, por hotel).
- `/chart` — Precio medio mensual por hotel (multiselección).
- `/compare` — Threehouse vs Barceló side-by-side en días comunes.

### Deploy a Vercel

1. **Importa el repo en Vercel** (`New Project` → selecciona este repo).
2. En el wizard, marca **Root Directory** = `web` (importante — el `src/` del scraper no es parte del build de Vercel).
3. Framework preset: **Next.js** (se detecta solo).
4. Vercel asignará por defecto un subdominio `*.vercel.app`. En `Settings → Domains` puedes renombrar a `scrapper-threehouse-barcelo.vercel.app`.

### Variables de entorno en Vercel

| Nombre                         | Valor                                                  | Obligatoria |
|-------------------------------|--------------------------------------------------------|-------------|
| `GOOGLE_SHEET_ID`              | `1HPyd0LnqI7c1eKKY4gGQcQ__ct0hnVZxkUaOeEYAJKY`         | sí          |
| `GOOGLE_SHEET_GID`             | `1379799510`                                           | sí          |
| `GOOGLE_SERVICE_ACCOUNT_JSON`  | JSON del service account en una sola línea            | sí          |
| `GITHUB_REPO`                  | `tu-usuario/scrapper-threehouse-barcelo`              | para botón "Scrape now" |
| `GITHUB_WORKFLOW`              | `scrape.yml`                                           | idem        |
| `GITHUB_TOKEN`                 | PAT clásico con scope `repo` **o** fine-grained con `actions: write` | idem |

El mismo service account que usa el scraper puede usarse en Vercel (solo necesita lectura; el scope que pedimos es `spreadsheets.readonly`).

### Local dev del dashboard

```bash
cd web
cp .env.example .env.local     # pega aquí tu GOOGLE_SERVICE_ACCOUNT_JSON
npm install
npm run dev
# http://localhost:3000
```

---

## Esquema de columnas de la Sheet

`scraped_at | brand | hotel_name | hotel_id | city | date | price | currency | available | min_stay | source_url`

---

## Troubleshooting

- **Sheets write → 403** → el email del service account no está compartido como **Editor** en la Sheet.
- **Barceló devuelve 0 filas** → borra `barcelo_hotels.json` (o corre con `--rediscover`); Barceló puede haber renombrado la landing país.
- **Mirai devuelve 0 filas** → corre con `HEADLESS=false -v` y observa el navegador; el selector del botón "siguiente mes" puede haber cambiado.
- **Dashboard muestra "Aún no hay datos"** → corre el workflow de GitHub Actions manualmente una vez.
- **Botón "Scrape now" devuelve 501** → falta `GITHUB_TOKEN` + `GITHUB_REPO` en Vercel.
- **Build de Vercel falla con errores de Python** → Root Directory no está puesto a `web/`.
