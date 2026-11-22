# Comic Inventory

A single-user, local-first comic collection app. It uses Python 3.12+, FastAPI,
SQLite, and a responsive HTML/JavaScript interface. No account or network
service is required; the server listens on `127.0.0.1`.

## Run locally

1. Install Python 3.12 or newer.
2. Create and activate a virtual environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies and start the app:

   ```powershell
   python -m pip install -r requirements.txt
   python main.py
   ```

4. Open <http://127.0.0.1:8000>.

The SQLite database is created at `data/comics.db`; uploaded cover images are
stored in `data/covers`. Set `COMIC_INVENTORY_DB` to use another database path.
Schema changes are applied from `migrations/` on startup. To run the tests:

```powershell
python -m pytest
```

## Included in this MVP

- Add, view, and edit comic catalog and inventory fields.
- Warn on likely duplicates; continue as a separate copy or merge quantity into
  the first matching active entry.
- Prevent negative quantities and record initial, adjustment, deletion, and
  restoration movements.
- Soft-delete comics and restore them later.
- Upload optional JPEG, PNG, or WebP cover images (up to 10 MB).

Sales, wish lists, market pricing, barcode scanning, cloud deployment,
authentication, and AI features are intentionally out of scope.
