import { api } from "../api.js";
import { table, esc, fmtNum, fmtDateTime, badge, showModal, closeModal, toast } from "../utils.js";
import { navigate } from "../router.js";
import { hasPermission } from "../state.js";

export async function renderPhysicalInventoryList(container) {
  const warehouses = await api.get("/warehouses");
  container.innerHTML = `
    <div class="toolbar"><div class="spacer"></div>
      ${hasPermission("count", "edit") ? `<button class="btn btn-primary" id="btn-new">+ Nuevo conteo</button>` : ""}
    </div>
    <div class="card"><div id="tbl"></div></div>`;

  async function load() {
    const rows = await api.get("/physical-counts");
    container.querySelector("#tbl").innerHTML = table(
      [
        { label: "ID", key: "id" },
        { label: "Almacen", key: "warehouse_name" },
        { label: "Alcance", render: (r) => esc(r.rack_code ? `Rack ${r.rack_code}` : r.zone_code || "Todo el almacen") },
        { label: "Creado por", render: (r) => esc(r.created_by_name || "—") },
        { label: "Fecha", render: (r) => fmtDateTime(r.created_at) },
        { label: "Estado", render: (r) => badge(r.status) },
      ],
      rows,
      { rowAttrs: (r) => `class="row-link" data-id="${r.id}"`, emptyText: "Sin conteos de inventario fisico registrados" }
    );
    container.querySelectorAll("[data-id]").forEach((tr) => tr.addEventListener("click", () => navigate(`/inventario-fisico/${tr.dataset.id}`)));
  }

  container.querySelector("#btn-new")?.addEventListener("click", async () => {
    const wmap = await api.get("/warehouse/map");
    const allRacks = wmap.flatMap((w) => w.zones.flatMap((z) => z.racks.map((r) => ({ ...r, warehouse_id: w.id }))));
    showModal(
      `<h3>Nuevo conteo de inventario fisico</h3>
      <form id="f">
        <div class="field"><label>Almacen</label>
          <select name="warehouse_id" id="wh-select" required>${warehouses.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select>
        </div>
        <div class="field">
          <label>Alcance del conteo</label>
          <div class="item-type-toggle">
            <label class="item-type-opt"><input type="radio" name="scope" value="rack" checked /><span class="item-type-text"><span>⚡ Un solo rack</span><small>Recomendado — rapido, no interrumpe el resto del almacen. Ideal para contar seguido (conteo ciclico).</small></span></label>
            <label class="item-type-opt"><input type="radio" name="scope" value="total" /><span class="item-type-text"><span>📋 Todo el almacen</span><small>Conteo completo — mas lento, usar cada cierto tiempo, no seguido.</small></span></label>
          </div>
        </div>
        <div class="field" id="rack-field"><label>Rack a contar</label>
          <select name="rack_id" required>${allRacks.filter((r) => r.code !== "PATIO" && r.code !== "PRODUCCION").map((r) => `<option value="${r.id}">Rack ${esc(r.code)} — ${r.occupancy_pct}% ocupado</option>`).join("")}</select>
        </div>
        <p class="hint">Se generara una linea por cada combinacion producto/lote/ubicacion con stock actual en el alcance elegido. El conteo es <strong>a ciegas</strong>: no se muestra la cantidad del sistema mientras cuentas, para que el conteo sea honesto.</p>
        <button class="btn btn-primary" type="submit">Crear conteo</button>
      </form>`,
      {
        onMount: (root) => {
          const rackField = root.querySelector("#rack-field");
          root.querySelectorAll('input[name="scope"]').forEach((r) =>
            r.addEventListener("change", () => rackField.classList.toggle("hidden", r.value !== "rack" || !r.checked))
          );
          root.querySelector("#f").addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const scope = fd.get("scope");
            const payload = { warehouse_id: fd.get("warehouse_id") };
            if (scope === "rack") payload.rack_id = fd.get("rack_id");
            const res = await api.post("/physical-counts", payload);
            closeModal();
            navigate(`/inventario-fisico/${res.id}`);
          });
        },
      }
    );
  });

  await load();
}

export async function renderPhysicalInventoryDetail(container, id) {
  container.innerHTML = `<div class="empty-state">Cargando...</div>`;
  let count = await api.get(`/physical-counts/${id}`);
  let showOnlyDiffs = false;
  const isBlind = count.status === "ABIERTO"; // mientras se cuenta, no se muestra lo que espera el sistema

  container.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">Conteo #${count.id} ${badge(count.status)}</h3>
        <div class="spacer"></div>
        ${!isBlind ? `<label style="display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;cursor:pointer"><input type="checkbox" id="chk-only-diffs" /> Solo diferencias</label>` : ""}
        ${count.status !== "CERRADO" && hasPermission("approve") ? `<button class="btn btn-primary btn-sm" id="btn-approve">Aprobar ajustes y cerrar</button>` : ""}
      </div>
      ${
        isBlind
          ? `<div class="field" style="max-width:420px">
              <label>🔫 Escanear codigo de barras o ubicacion</label>
              <input id="scan-input" placeholder="Escanee el producto o la posicion para saltar a esa fila..." autocomplete="off" />
            </div>`
          : ""
      }
      <div id="items-table"></div>
    </div>`;

  function renderItems() {
    const rows = showOnlyDiffs ? count.items.filter((r) => (r.difference || 0) !== 0) : count.items;
    const cols = [
      { label: "SKU", render: (r) => `<span class="mono">${esc(r.sku_code)}</span>` },
      { label: "Producto", key: "product_description" },
      { label: "Lote", render: (r) => esc(r.lot_code || "—") },
      { label: "Ubicacion", render: (r) => `<span class="mono">${esc(r.location_code)}</span>` },
    ];
    if (!isBlind) cols.push({ label: "Sistema", render: (r) => fmtNum(r.system_qty) });
    cols.push({
      label: "Fisico (contado)",
      render: (r) =>
        count.status === "CERRADO"
          ? fmtNum(r.counted_qty)
          : `<input type="number" step="any" class="counted-input" data-item="${r.id}" data-sku="${esc(r.sku_code)}" data-loc="${esc(r.location_code)}" value="${r.counted_qty ?? ""}" style="width:110px;padding:5px 8px;border:1px solid var(--line);border-radius:6px" />`,
    });
    if (!isBlind) {
      cols.push({
        label: "Diferencia",
        render: (r) =>
          r.difference === null || r.difference === undefined
            ? "—"
            : `<strong style="color:${r.difference === 0 ? "var(--ok)" : "var(--bad)"}">${r.difference > 0 ? "+" : ""}${fmtNum(r.difference)}</strong>`,
      });
    }
    container.querySelector("#items-table").innerHTML = table(cols, rows, {
      emptyText: showOnlyDiffs ? "Sin diferencias — todo cuadra ✓" : "Sin lineas en este conteo",
      rowAttrs: (r) => `data-row-item="${r.id}"`,
    });
    container.querySelectorAll(".counted-input").forEach((inp) =>
      inp.addEventListener("change", async () => {
        await api.put(`/physical-count-items/${inp.dataset.item}`, { counted_qty: parseFloat(inp.value) || 0 });
        toast("Cantidad registrada", "ok");
        count = await api.get(`/physical-counts/${id}`);
        renderItems();
      })
    );
  }
  renderItems();

  container.querySelector("#chk-only-diffs")?.addEventListener("change", (e) => {
    showOnlyDiffs = e.target.checked;
    renderItems();
  });

  // --- Escaner: busca por SKU/codigo de barras o por ubicacion, salta a la fila ---
  const scanInput = container.querySelector("#scan-input");
  scanInput?.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const code = scanInput.value.trim();
    scanInput.value = "";
    if (!code) return;
    let targetInput = null;
    // 1) intenta como codigo de barras de producto
    try {
      const res = await api.get("/products/by-barcode", { code });
      targetInput = container.querySelector(`.counted-input[data-sku="${res.product.sku_code}"]`);
    } catch (err) {
      /* no es un codigo de barras conocido, sigue intentando */
    }
    // 2) intenta como codigo de ubicacion (ej. escaneando una etiqueta de rack)
    if (!targetInput) {
      targetInput = [...container.querySelectorAll(".counted-input")].find((i) => i.dataset.loc === code);
    }
    if (!targetInput) {
      toast(`No se encontro "${code}" en este conteo`, "error");
      return;
    }
    targetInput.closest("tr")?.scrollIntoView({ behavior: "smooth", block: "center" });
    targetInput.style.outline = "2px solid var(--blue)";
    targetInput.focus();
    targetInput.select();
  });

  container.querySelector("#btn-approve")?.addEventListener("click", async () => {
    if (!confirm("Esto aplicara ajustes de inventario para todas las diferencias registradas. ¿Continuar?")) return;
    try {
      const res = await api.post(`/physical-counts/${id}/approve`);
      toast(`Conteo cerrado. ${res.adjustments_applied} ajustes aplicados.`, "ok");
      navigate(`/inventario-fisico/${id}`);
      renderPhysicalInventoryDetail(container, id);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
