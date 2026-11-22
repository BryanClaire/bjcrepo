CREATE TABLE comics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_title TEXT NOT NULL CHECK (length(trim(series_title)) > 0),
    issue_number TEXT NOT NULL CHECK (length(trim(issue_number)) > 0),
    publisher TEXT NOT NULL CHECK (length(trim(publisher)) > 0),
    publication_year INTEGER,
    variant TEXT NOT NULL DEFAULT '',
    grade TEXT NOT NULL CHECK (length(trim(grade)) > 0),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 0),
    upc TEXT,
    creators TEXT,
    condition_notes TEXT,
    purchase_cost REAL CHECK (purchase_cost IS NULL OR purchase_cost >= 0),
    purchase_date TEXT,
    purchase_source TEXT,
    storage_location TEXT,
    cover_image_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX comics_active_title_idx
    ON comics (deleted_at, series_title COLLATE NOCASE, issue_number);

CREATE TABLE inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comic_id INTEGER NOT NULL REFERENCES comics(id),
    movement_type TEXT NOT NULL CHECK (
        movement_type IN ('initial_entry', 'adjustment', 'deletion', 'restoration')
    ),
    quantity_delta INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL CHECK (quantity_after >= 0),
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX inventory_movements_comic_idx
    ON inventory_movements (comic_id, created_at, id);
