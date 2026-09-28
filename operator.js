import { api } from "../api.js";
import { esc, fmtNum, toast, showModal, closeModal } from "../utils.js";
import { navigate } from "../router.js";
import { state } from "../state.js";

export async function renderOperatorHome(container) {
  container.innerHTML = `<div class="empty-state">Preparando tus tareas...</div>`;
  const tasks = await api.get("/operator/tasks");
  const rec = tasks.receptions || [];
  const dsp = tasks.dispatches || [];
  const picks = tasks.picking || [];
  const putaway = rec.reduce((n, r) => n + Number(r.putaway_pending || 0), 0);
  const quality = rec.reduce((n, r) => n + Number(r.quality_pending || 0), 0);

  container.innerHTML = `
    <section class="operator-hero">
      <div><div class="eyebrow">CENTRO DE TRABAJO</div><h1>Hola, ${esc((state.user?.name || "").split(" ")[0])}</h1>
      <p>Estas son las tareas que necesitan atención. Elige una y el sistema te guiará.</p></div>
      <button class="scan-main" id="op-search">⌕ <span>Buscar producto, lote o ubicación</span></button>
    </section>
    <div class="operator-stats">
      <button class="op-stat" data-go="/recepciones"><strong>${fmtNum(rec.length)}</strong><span>Recepciones abiertas</span></button>
      <button class="op-stat" data-go="/recepciones"><strong>${fmtNum(putaway)}</strong><span>Productos por ubicar</span></button>
      <button class="op-stat" data-go="/despachos"><strong>${fmtNum(picks.length || dsp.length)}</strong><span>${picks.length ? "Líneas por recoger" : "Despachos pendientes"}</span></button>
      <button class="op-stat ${quality ? "attention" : ""}" data-go="/recepciones"><strong>${fmtNum(quality)}</strong><span>Por revisar</span></button>
    </div>

    <div class="operator-actions">
      <button class="op-action receive" data-go="/recepciones"><span class="op-action-icon">↓</span><span><strong>Recibir mercadería</strong><small>Registrar lo que acaba de llegar</small></span><b>→</b></button>
      <button class="op-action locate" data-go="/recepciones"><span class="op-action-icon">⌖</span><span><strong>Ubicar en rack</strong><small>${putaway ? `${putaway} producto(s) esperando ubicación` : "No hay ubicaciones pendientes"}</small></span><b>→</b></button>
      <button class="op-action dispatch" data-go="/despachos"><span class="op-action-icon">↑</span><span><strong>Preparar despacho</strong><small>${picks.length ? `${picks.length} línea(s) listas para picking` : "Ver pedidos pendientes"}</small></span><b>→</b></button>
      <button class="op-action stock" data-go="/stock"><span class="op-action-icon">⌕</span><span><strong>Consultar stock</strong><small>Buscar producto, lote o ubicación</small></span><b>→</b></button>
    </div>

    <div class="operator-grid">
      <section class="card op-card"><div class="op-card-head"><div><h2>Siguiente trabajo</h2><p>Prioridad operativa</p></div></div><div id="next-work"></div></section>
      <section class="card op-card"><div class="op-card-head"><div><h2>Recepciones</h2><p>Mercadería pendiente</p></div><button class="btn btn-sm" data-go="/recepciones">Ver todas</button></div><div id="op-receptions"></div></section>
    </div>`;

  const next = container.querySelector("#next-work");
  if (picks.length) {
    const p = picks[0];
    next.innerHTML = `<div class="next-task"><div class="task-label">PICKING · ${esc(p.dispatch_number)}</div><div class="task-location">${esc(p.location_code || "SIN UBICACIÓN")}</div><div class="task-product"><strong>${esc(p.product_description)}</strong><span>${esc(p.sku_code)}${p.lot_code ? ` · Lote ${esc(p.lot_code)}` : ""}</span></div><div class="task-qty"><span>Retirar</span><strong>${fmtNum(p.qty_requested)}</strong></div><button class="btn btn-primary btn-task" data-pick-now="${p.id}" data-qty="${p.qty_requested}">Confirmar retiro</button><button class="btn btn-ghost btn-task" data-go="/despachos/${p.dispatch_id}">Ver despacho</button></div>`;
  } else if (rec.length) {
    const r = rec[0];
    next.innerHTML = `<div class="next-task"><div class="task-label">RECEPCIÓN · ${esc(r.reception_number)}</div><div class="task-product"><strong>${esc(r.client_name)}</strong><span>${fmtNum(r.item_count)} producto(s)</span></div><div class="task-instruction">${Number(r.quality_pending) ? "Revisa la mercadería recibida" : Number(r.putaway_pending) ? "Ubica la mercadería en rack" : "Continúa esta recepción"}</div><button class="btn btn-primary btn-task" data-go="/recepciones/${r.id}">Continuar recepción</button></div>`;
  } else {
    next.innerHTML = `<div class="op-empty"><strong>✓ Todo al día</strong><span>No tienes tareas operativas pendientes.</span></div>`;
  }

  container.querySelector("#op-receptions").innerHTML = rec.length ? rec.slice(0, 5).map(r => `<button class="op-list-row" data-go="/recepciones/${r.id}"><span><strong>${esc(r.reception_number)}</strong><small>${esc(r.client_name)}</small></span><span class="op-row-state">${Number(r.putaway_pending) ? `${r.putaway_pending} por ubicar` : Number(r.quality_pending) ? `${r.quality_pending} por revisar` : "Continuar"} →</span></button>`).join("") : `<div class="op-empty"><span>Sin recepciones pendientes.</span></div>`;

  container.querySelectorAll("[data-go]").forEach(el => el.addEventListener("click", () => navigate(el.dataset.go)));
  container.querySelector("#op-search").addEventListener("click", () => document.querySelector("#search-input")?.focus());
  container.querySelector("[data-pick-now]")?.addEventListener("click", e => openPickConfirm(e.currentTarget));
}

function openPickConfirm(btn) {
  const requested = Number(btn.dataset.qty || 0);
  showModal("Confirmar retiro", `
    <div class="pick-confirm"><p>Confirma la cantidad que retiraste físicamente del rack.</p>
      <div class="pick-big-number">${fmtNum(requested)}</div><div class="muted" style="text-align:center">cantidad solicitada</div>
      <div class="field" style="margin-top:18px"><label>Cantidad realmente retirada</label><input id="pick-real-qty" type="number" min="0" step="any" value="${requested}" inputmode="decimal"></div>
      <button class="btn btn-primary btn-task" id="pick-confirm-btn">✓ Confirmar retiro</button>
    </div>`);
  document.querySelector("#pick-confirm-btn")?.addEventListener("click", async () => {
    const qty = Number(document.querySelector("#pick-real-qty").value);
    if (!Number.isFinite(qty) || qty < 0) return toast("Ingresa una cantidad válida", "error");
    try { await api.post(`/picking-items/${btn.dataset.pickNow}/pick`, { qty_picked: qty }); closeModal(); toast("Retiro confirmado", "ok"); location.hash = "#/operario"; window.dispatchEvent(new HashChangeEvent("hashchange")); }
    catch (err) { toast(err.message, "error"); }
  });
}
