const form = document.querySelector("#comic-form");
const comicList = document.querySelector("#comic-list");
const formNotice = document.querySelector("#form-notice");
const catalogNotice = document.querySelector("#catalog-notice");
const showDeleted = document.querySelector("#show-deleted");
const emptyState = document.querySelector("#empty-state");
const count = document.querySelector("#comic-count");
const resultsCount = document.querySelector("#results-count");
const loadMoreButton = document.querySelector("#load-more");
const summaryContainer = document.querySelector("#collection-summary");
const pageSize = 24;
let loadedCount = 0;
let latestBrowseRequest = 0;
let loadingMore = false;
let searchTimer;

const fieldNames = [
  "series_title", "issue_number", "publisher", "publication_year", "variant",
  "grade", "quantity", "upc", "creators", "condition_notes", "purchase_cost",
  "purchase_date", "purchase_source", "storage_location"
];
const filters = [
  ["search", "search-filter"],
  ["publisher", "publisher-filter"],
  ["grade", "grade-filter"],
  ["year", "year-filter"],
  ["variant", "variant-filter"],
  ["storage_location", "location-filter"]
];

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail?.code === "duplicate"
      ? "Likely duplicate comics were found."
      : (typeof data.detail === "string" ? data.detail : "The request could not be completed."));
    error.status = response.status;
    error.detail = data.detail;
    throw error;
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function notice(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("hidden", !message);
  element.classList.toggle("error", isError);
}

function comicData() {
  const data = {};
  for (const name of fieldNames) {
    const input = form.elements.namedItem(name);
    const value = input.value.trim();
    if (name === "quantity") data[name] = Number(value);
    else if (name === "publication_year" || name === "purchase_cost") {
      data[name] = value === "" ? null : Number(value);
    } else if (["upc", "creators", "condition_notes", "purchase_date", "purchase_source", "storage_location"].includes(name)) {
      data[name] = value || null;
    } else {
      data[name] = value;
    }
  }
  return data;
}

async function saveCover(comicId) {
  const file = form.elements.namedItem("cover_image").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  await request(`/api/comics/${comicId}/cover`, { method: "POST", body });
}

function resetForm() {
  form.reset();
  form.elements.namedItem("quantity").value = "1";
  delete form.dataset.editingId;
  document.querySelector("#form-title").textContent = "Add a comic";
  document.querySelector("#submit-button").textContent = "Add comic";
  document.querySelector("#cancel-edit").classList.add("hidden");
}

function startEditing(comic) {
  for (const name of fieldNames) {
    const input = form.elements.namedItem(name);
    input.value = comic[name] ?? (name === "quantity" ? 0 : "");
  }
  form.elements.namedItem("quantity_note").value = "";
  form.elements.namedItem("cover_image").value = "";
  form.dataset.editingId = comic.id;
  document.querySelector("#form-title").textContent = `Edit ${comic.series_title} #${comic.issue_number}`;
  document.querySelector("#submit-button").textContent = "Save changes";
  document.querySelector("#cancel-edit").classList.remove("hidden");
  notice(formNotice, "");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function detailMarkup(comic) {
  const details = [
    ["Publisher", comic.publisher],
    ["Year", comic.publication_year],
    ["Variant", comic.variant],
    ["Grade", comic.grade],
    ["UPC", comic.upc],
    ["Creators", comic.creators],
    ["Condition notes", comic.condition_notes],
    ["Purchase cost", comic.purchase_cost == null ? null : `$${Number(comic.purchase_cost).toFixed(2)}`],
    ["Purchase date", comic.purchase_date],
    ["Purchase source", comic.purchase_source],
    ["Storage location", comic.storage_location]
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  const fields = details.map(([label, value]) =>
    `<div class="detail-item"><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</div>`
  ).join("");
  const movements = (comic.movements || []).map((movement) => {
    const quantity = movement.quantity_delta > 0
      ? `+${movement.quantity_delta}`
      : String(movement.quantity_delta);
    return `<li><strong>${escapeHtml(movement.movement_type.replaceAll("_", " "))}</strong> · ${escapeHtml(quantity)} · ${escapeHtml(movement.notes || "")}<time>${escapeHtml(movement.created_at)}</time></li>`;
  }).join("");
  return `<div class="detail-grid">${fields || "<p>No additional catalog details.</p>"}</div>
    <h4>Movement history</h4>
    <ul class="movement-list">${movements || "<li>No inventory movements recorded.</li>"}</ul>`;
}

function renderComic(comic) {
  const card = document.createElement("article");
  card.className = "comic-card";
  const cover = comic.cover_image_path
    ? `<img class="cover" src="/covers/${encodeURIComponent(comic.cover_image_path)}" alt="Cover of ${escapeHtml(comic.series_title)} #${escapeHtml(comic.issue_number)}">`
    : '<div class="cover cover-placeholder" aria-hidden="true">NO<br>COVER</div>';
  const statusTag = comic.deleted_at ? '<span class="tag tag-deleted">Deleted</span>' : "";
  const actionButtons = comic.deleted_at
    ? `<button class="button button-muted button-small" data-action="restore">Restore</button>`
    : `<button class="button button-muted button-small" data-action="edit">Edit</button>
       <button class="button button-danger button-small" data-action="delete">Delete</button>`;
  card.innerHTML = `
    <div class="comic-top">
      ${cover}
      <div>
        <h3 class="comic-title">${escapeHtml(comic.series_title)} #${escapeHtml(comic.issue_number)}</h3>
        <p class="comic-subtitle">${escapeHtml(comic.publisher)}${comic.publication_year ? ` · ${escapeHtml(comic.publication_year)}` : ""}</p>
        <div class="comic-meta">
          <span class="tag">Grade ${escapeHtml(comic.grade)}</span>
          <span class="tag">Qty ${escapeHtml(comic.quantity)}</span>${statusTag}
        </div>
        <div class="comic-actions">${actionButtons}</div>
      </div>
    </div>
    <details class="comic-details">
      <summary>Catalog details and movement history</summary>
      <div class="comic-detail-content">Loading…</div>
    </details>`;
  card.querySelector('[data-action="edit"]')?.addEventListener("click", () => startEditing(comic));
  card.querySelector('[data-action="delete"]')?.addEventListener("click", async () => {
    if (!window.confirm(`Soft-delete ${comic.series_title} #${comic.issue_number}? You can restore it later.`)) return;
    try {
      await request(`/api/comics/${comic.id}`, { method: "DELETE" });
      await Promise.all([loadComics(), loadCollectionSummary()]);
      await loadFacets();
    } catch (error) {
      notice(catalogNotice, error.message, true);
    }
  });
  card.querySelector('[data-action="restore"]')?.addEventListener("click", async () => {
    try {
      await request(`/api/comics/${comic.id}/restore`, { method: "POST" });
      await Promise.all([loadComics(), loadCollectionSummary()]);
      await loadFacets();
    } catch (error) {
      notice(catalogNotice, error.message, true);
    }
  });
  const details = card.querySelector("details");
  details.addEventListener("toggle", async () => {
    if (!details.open || details.dataset.loaded) return;
    try {
      const fullComic = await request(`/api/comics/${comic.id}`);
      details.querySelector(".comic-detail-content").innerHTML = detailMarkup(fullComic);
      details.dataset.loaded = "true";
    } catch (error) {
      details.querySelector(".comic-detail-content").textContent = error.message;
    }
  });
  return card;
}

function fillSelect(id, values, placeholder) {
  const select = document.querySelector(`#${id}`);
  const currentValue = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  for (const value of values) select.add(new Option(String(value), String(value)));
  if (values.map(String).includes(currentValue)) select.value = currentValue;
}

async function loadFacets() {
  try {
    const facets = await request(`/api/comics/facets?include_deleted=${showDeleted.checked}`);
    fillSelect("publisher-filter", facets.publishers, "All publishers");
    fillSelect("grade-filter", facets.grades, "All grades");
    fillSelect("year-filter", facets.years, "All years");
    fillSelect("variant-filter", facets.variants, "All variants");
    fillSelect("location-filter", facets.storage_locations, "All locations");
  } catch (error) {
    notice(catalogNotice, error.message, true);
  }
}

async function loadCollectionSummary() {
  try {
    const summary = await request("/api/collection/summary");
    const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
    const values = [
      ["Catalog entries", summary.comic_count.toLocaleString()],
      ["Total copies", summary.total_copies.toLocaleString()],
      ["Series", summary.series_count.toLocaleString()],
      ["Publishers", summary.publisher_count.toLocaleString()],
      ["Known purchase cost", currency.format(summary.known_purchase_cost)]
    ];
    summaryContainer.replaceChildren(...values.map(([label, value]) => {
      const card = document.createElement("article");
      const title = document.createElement("span");
      const amount = document.createElement("strong");
      card.className = "summary-card";
      title.textContent = label;
      amount.textContent = value;
      card.append(title, amount);
      return card;
    }));
  } catch (error) {
    notice(catalogNotice, error.message, true);
  }
}

function activeFilters() {
  return filters.some(([key, id]) => key !== "search"
    ? document.querySelector(`#${id}`).value
    : document.querySelector(`#${id}`).value.trim());
}

async function loadComics({ append = false } = {}) {
  if (append && loadingMore) return;
  const requestId = ++latestBrowseRequest;
  if (!append) {
    loadedCount = 0;
    loadingMore = false;
  } else {
    loadingMore = true;
    loadMoreButton.disabled = true;
    loadMoreButton.textContent = "Loading…";
  }

  const params = new URLSearchParams({
    limit: String(pageSize),
    offset: String(append ? loadedCount : 0),
    sort_by: document.querySelector("#sort-by").value,
    sort_order: document.querySelector("#sort-order").value,
    include_deleted: String(showDeleted.checked)
  });
  for (const [key, id] of filters) {
    const value = document.querySelector(`#${id}`).value.trim();
    if (value) params.set(key, value);
  }

  notice(catalogNotice, "");
  try {
    const page = await request(`/api/comics?${params}`);
    if (requestId !== latestBrowseRequest) return;
    const cards = page.items.map(renderComic);
    if (append) comicList.append(...cards);
    else comicList.replaceChildren(...cards);
    loadedCount = append ? loadedCount + cards.length : cards.length;
    count.textContent = `(${page.total.toLocaleString()})`;
    resultsCount.textContent = page.total === 0
      ? ""
      : `Showing ${loadedCount.toLocaleString()} of ${page.total.toLocaleString()} comics`;
    emptyState.classList.toggle("hidden", page.total > 0);
    if (page.total === 0) {
      emptyState.textContent = activeFilters() || showDeleted.checked
        ? "No comics match the current search and filters."
        : "No comics yet. Add your first issue above.";
    }
    loadMoreButton.classList.toggle("hidden", !page.has_more);
  } catch (error) {
    if (requestId === latestBrowseRequest) notice(catalogNotice, error.message, true);
  } finally {
    if (requestId === latestBrowseRequest) {
      loadingMore = false;
      loadMoreButton.disabled = false;
      loadMoreButton.textContent = "Load more comics";
    }
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  notice(formNotice, "");
  const editingId = form.dataset.editingId;
  const data = comicData();
  if (editingId) data.quantity_note = form.elements.namedItem("quantity_note").value.trim() || null;
  try {
    let result;
    if (editingId) {
      result = await request(`/api/comics/${editingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
    } else {
      try {
        result = await request("/api/comics", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        });
      } catch (error) {
        if (error.status !== 409 || error.detail?.code !== "duplicate") throw error;
        const duplicates = error.detail.comics
          .map((comic) => `${comic.series_title} #${comic.issue_number} · ${comic.grade} · qty ${comic.quantity}`)
          .join("\n");
        const merge = window.confirm(`Likely duplicate(s):\n${duplicates}\n\nOK: merge quantity into the first match. Cancel: save as a separate copy.`);
        const action = merge ? "merge" : "continue";
        result = await request(`/api/comics?duplicate_action=${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        });
      }
    }
    const savedComic = result.comic || result;
    await saveCover(savedComic.id);
    resetForm();
    await Promise.all([loadComics(), loadCollectionSummary()]);
    await loadFacets();
    notice(formNotice, result.merged ? "Quantities merged into the matching comic." : "Comic saved.");
  } catch (error) {
    notice(formNotice, error.message, true);
  }
});

for (const [, id] of filters.slice(1)) {
  document.querySelector(`#${id}`).addEventListener("change", () => loadComics());
}
document.querySelector("#sort-by").addEventListener("change", () => loadComics());
document.querySelector("#sort-order").addEventListener("change", () => loadComics());
document.querySelector("#search-filter").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadComics(), 250);
});
showDeleted.addEventListener("change", () => {
  loadFacets();
  loadComics();
});
document.querySelector("#clear-filters").addEventListener("click", () => {
  document.querySelector("#search-filter").value = "";
  for (const [, id] of filters.slice(1)) document.querySelector(`#${id}`).value = "";
  document.querySelector("#sort-by").value = "series_title";
  document.querySelector("#sort-order").value = "asc";
  showDeleted.checked = false;
  loadFacets();
  loadComics();
});
document.querySelector("#load-more").addEventListener("click", () => loadComics({ append: true }));
document.querySelector("#cancel-edit").addEventListener("click", resetForm);

loadFacets();
loadComics();
loadCollectionSummary();
