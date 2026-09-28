"""
Motor de stock: el saldo NUNCA se edita directamente.
Toda variacion pasa por record_movement(), que escribe una partida doble
(pierna 'from' y/o pierna 'to') en inventory_movements. inventory_balances
es una vista SQL calculada a partir de esa tabla (ver schema.sql).
"""
import datetime
from db import q, q1, execute


class StockError(Exception):
    pass


# ---------------------------------------------------------------------------
def get_balance(product_id, lot_id, client_id, location_id, status):
    row = q1(
        """SELECT COALESCE(qty,0) as qty FROM inventory_balances
           WHERE product_id=? AND (lot_id IS ? OR lot_id=?) AND client_id=?
             AND (location_id IS ? OR location_id=?) AND status=?""",
        (product_id, lot_id, lot_id, client_id, location_id, location_id, status),
    )
    return row["qty"] if row else 0.0


def available_balances_for_product(product_id, client_id, lot_id=None):
    """Devuelve saldos DISPONIBLE por lote/ubicacion, ordenado por FEFO (vencimiento) luego FIFO (ingreso)."""
    sql = """
        SELECT b.product_id, b.lot_id, b.location_id, b.qty, b.client_id,
               l.lot_code, l.expiration_date, l.created_at as lot_created_at,
               loc.full_code as location_code
        FROM inventory_balances b
        LEFT JOIN lots l ON l.id = b.lot_id
        LEFT JOIN locations loc ON loc.id = b.location_id
        WHERE b.product_id=? AND b.client_id=? AND b.status='DISPONIBLE'
    """
    params = [product_id, client_id]
    if lot_id:
        sql += " AND b.lot_id=?"
        params.append(lot_id)
    sql += " ORDER BY (l.expiration_date IS NULL), l.expiration_date ASC, l.created_at ASC"
    return q(sql, tuple(params))


def total_available(product_id, client_id, lot_id=None):
    rows = available_balances_for_product(product_id, client_id, lot_id)
    return sum(r["qty"] for r in rows)


# ---------------------------------------------------------------------------
def record_movement(movement_type, product_id, client_id, qty, user_id,
                     lot_id=None, from_location_id=None, from_status=None,
                     to_location_id=None, to_status=None,
                     reference_type=None, reference_id=None, reason=None,
                     allow_negative=False):
    """Escribe un movimiento de inventario. Valida stock suficiente en la pierna 'from'."""
    if qty <= 0:
        raise StockError("La cantidad del movimiento debe ser mayor a cero")

    if from_status and not allow_negative:
        current = get_balance(product_id, lot_id, client_id, from_location_id, from_status)
        if current < qty - 1e-6:
            raise StockError(
                f"Stock insuficiente: disponible {current:g}, solicitado {qty:g} "
                f"(producto={product_id}, lote={lot_id}, estado={from_status})"
            )

    execute(
        """INSERT INTO inventory_movements
           (movement_type, product_id, lot_id, client_id, qty,
            from_location_id, from_status, to_location_id, to_status,
            reference_type, reference_id, user_id, reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (movement_type, product_id, lot_id, client_id, qty,
         from_location_id, from_status, to_location_id, to_status,
         reference_type, reference_id, user_id, reason),
    )


# ---------------------------------------------------------------------------
def suggest_location(product_id, client_id, qty):
    """
    Sugiere una ubicacion para almacenar `qty` unidades.
    Preferencia: (1) ubicaciones DISPONIBLES que ya contienen el mismo producto
    y tienen espacio; (2) ubicaciones DISPONIBLES vacias con capacidad suficiente.
    """
    same_product = q(
        """SELECT loc.id, loc.full_code, loc.capacity,
                  COALESCE((SELECT SUM(b.qty) FROM inventory_balances b
                            WHERE b.location_id=loc.id AND b.status IN ('DISPONIBLE','POR_TRABAJAR','RESERVADO','CUARENTENA','BLOQUEADO','DANADO')),0) as occupied
           FROM locations loc
           WHERE loc.status='DISPONIBLE'
             AND loc.id IN (SELECT location_id FROM inventory_balances WHERE product_id=? AND client_id=? AND status='DISPONIBLE')
        """,
        (product_id, client_id),
    )
    for loc in same_product:
        free = (loc["capacity"] or 0) - loc["occupied"]
        if loc["capacity"] == 0 or free >= qty:
            return {
                "location_id": loc["id"],
                "location_code": loc["full_code"],
                "reason": f"Ya contiene este producto y tiene espacio disponible ({free:g} unidades libres)."
                if loc["capacity"] else "Ya contiene este producto (ubicacion sin limite de capacidad).",
            }

    empty_locs = q(
        """SELECT loc.id, loc.full_code, loc.capacity,
                  COALESCE((SELECT SUM(b.qty) FROM inventory_balances b
                            WHERE b.location_id=loc.id AND b.status IN ('DISPONIBLE','POR_TRABAJAR','RESERVADO','CUARENTENA','BLOQUEADO','DANADO')),0) as occupied
           FROM locations loc
           WHERE loc.status='DISPONIBLE'
           ORDER BY occupied ASC, loc.full_code ASC
        """
    )
    for loc in empty_locs:
        free = (loc["capacity"] or 0) - loc["occupied"]
        if loc["capacity"] == 0 or free >= qty:
            return {
                "location_id": loc["id"],
                "location_code": loc["full_code"],
                "reason": f"Ubicacion con capacidad disponible ({free:g} unidades libres)."
                if loc["capacity"] else "Ubicacion sin producto asignado y sin limite de capacidad.",
            }
    return None


# ---------------------------------------------------------------------------
def putaway(reception_item_id, location_id, user_id, qty=None):
    """Asigna ubicacion a un item de recepcion ya aprobado por calidad (queda
    DISPONIBLE en esa ubicacion). Si `qty` es None, ubica TODO lo pendiente de
    este item de una vez (caso normal, 1 paleta = 1 posicion). Si `qty` es
    menor, hace una ubicacion PARCIAL (ej. 6 paletas del mismo lote en 6
    posiciones distintas) -- se puede llamar varias veces seguidas hasta
    completar todo, y cada llamada queda registrada en
    reception_item_locations para trazabilidad completa. El "restante" que
    devuelve esta funcion es SIEMPRE relativo a este item especifico (lo que
    paso calidad como conforme, menos lo que ya se ubico de el) -- nunca a un
    pool compartido con otros items del mismo lote, para que el frontend
    pueda cerrar la ventana con confianza apenas este item quede completo."""
    item = q1("SELECT * FROM reception_items WHERE id=?", (reception_item_id,))
    if not item:
        raise StockError("Item de recepcion no encontrado")
    if item["quality_status"] not in ("DISPONIBLE", "OBSERVADO"):
        raise StockError("El item debe tener una porcion DISPONIBLE (aprobada por calidad) para poder ubicarse")
    reception = q1("SELECT * FROM receptions WHERE id=?", (item["reception_id"],))

    # Techo de ESTE item: lo que paso calidad como conforme (no siempre es
    # igual a qty_units si hubo defectos) menos lo que ya se ubico de el en
    # otras posiciones.
    conforming = q1(
        "SELECT COALESCE(SUM(conforming_qty),0) as q FROM quality_inspections WHERE reception_item_id=?",
        (reception_item_id,),
    )["q"]
    already_located = q1(
        "SELECT COALESCE(SUM(qty),0) as q FROM reception_item_locations WHERE reception_item_id=?",
        (reception_item_id,),
    )["q"]
    item_ceiling = conforming - already_located
    if item_ceiling <= 1e-6:
        raise StockError("Este item ya esta completamente ubicado")

    # Techo real del sistema (nunca ubicar mas de lo que hay verdaderamente
    # DISPONIBLE y sin ubicar de este producto/lote, por si otro item del
    # mismo lote ya consumio parte del pool).
    pool_available = get_balance(item["product_id"], item["lot_id"], reception["client_id"], None, "DISPONIBLE")
    max_allowed = min(item_ceiling, pool_available)
    if max_allowed <= 1e-6:
        raise StockError("No hay stock disponible pendiente de ubicar para este item")

    qty_to_move = float(qty) if qty else max_allowed
    if qty_to_move <= 1e-6:
        raise StockError("La cantidad a ubicar debe ser mayor a cero")
    if qty_to_move > max_allowed + 1e-6:
        raise StockError(f"Solo quedan {max_allowed:g} unidades sin ubicar de este item (pidio {qty_to_move:g})")

    loc = q1("SELECT * FROM locations WHERE id=?", (location_id,))
    if not loc:
        raise StockError("Ubicacion no encontrada")
    if loc["status"] != "DISPONIBLE":
        raise StockError(f"La ubicacion {loc['full_code']} no esta disponible (estado: {loc['status']})")
    if loc["capacity"]:
        occ = q1(
            """SELECT COALESCE(SUM(qty),0) as q FROM inventory_balances
               WHERE location_id=? AND status IN ('DISPONIBLE','POR_TRABAJAR','RESERVADO','CUARENTENA','BLOQUEADO','DANADO')""",
            (location_id,),
        )["q"]
        free = loc["capacity"] - occ
        if free < qty_to_move - 1e-6:
            raise StockError(
                f"Capacidad insuficiente en {loc['full_code']}: libre {free:g}, requerido {qty_to_move:g}"
            )

    # "Por trabajar" solo aplica a Productos -- doble seguro aca tambien
    # (por si un dato viejo quedo con needs_work=1 en un Material antes de
    # esta validacion, nunca se debe generar stock Material en ese estado).
    product_row = q1("SELECT item_type FROM products WHERE id=?", (item["product_id"],))
    goes_to_work = bool(item["needs_work"]) and product_row and product_row["item_type"] == "PRODUCTO"

    record_movement(
        "ALMACENAMIENTO", item["product_id"], reception["client_id"], qty_to_move, user_id,
        lot_id=item["lot_id"], from_location_id=None, from_status="DISPONIBLE",
        to_location_id=location_id, to_status=("POR_TRABAJAR" if goes_to_work else "DISPONIBLE"),
        reference_type="RECEPTION", reference_id=reception["id"],
        reason="Asignacion de ubicacion tras control de calidad",
    )
    execute(
        "INSERT INTO reception_item_locations (reception_item_id, location_id, qty) VALUES (?,?,?)",
        (reception_item_id, location_id, qty_to_move),
    )

    remaining = item_ceiling - qty_to_move  # relativo a ESTE item, no al pool
    new_status = "UBICADO" if remaining <= 1e-6 else "PARCIAL"
    # Solo actualiza el status de ESTE item (ya no de todas las lineas que
    # comparten lote -- eso causaba que el "restante" se mezclara entre
    # items distintos y la ventana no supiera cerrarse cuando correspondia).
    execute(
        "UPDATE reception_items SET storage_status=?, location_id=? WHERE id=?",
        (new_status, location_id, reception_item_id),
    )
    return {"qty_located": qty_to_move, "remaining": remaining}


def mark_as_worked(product_id, client_id, lot_id, location_id, qty, user_id):
    """Pasa stock de POR_TRABAJAR a DISPONIBLE en la misma posicion (ej. ya se
    le hizo la actividad de produccion pendiente -- empacado, etiquetado,
    etc. -- y ahora si esta listo para despachar)."""
    balance = get_balance(product_id, lot_id, client_id, location_id, "POR_TRABAJAR")
    if balance <= 1e-6:
        raise StockError("No hay stock 'por trabajar' en esa ubicacion para marcar como trabajado")
    qty_to_move = float(qty) if qty else balance
    if qty_to_move > balance + 1e-6:
        raise StockError(f"Solo hay {balance:g} unidades por trabajar ahi (pidio {qty_to_move:g})")
    record_movement(
        "LIBERACION_CALIDAD", product_id, client_id, qty_to_move, user_id,
        lot_id=lot_id, from_location_id=location_id, from_status="POR_TRABAJAR",
        to_location_id=location_id, to_status="DISPONIBLE",
        reference_type="MANUAL", reason="Marcado como trabajado (actividad de produccion completada)",
    )
    return {"qty_worked": qty_to_move, "remaining_por_trabajar": balance - qty_to_move}


# ---------------------------------------------------------------------------
def relocate(product_id, client_id, lot_id, from_location_id, to_location_id, qty, user_id, reason=None):
    """Mueve stock DISPONIBLE de una ubicacion a otra (ej. de Patio de Despacho
    a una posicion real de rack). No cambia el status (sigue DISPONIBLE)."""
    if from_location_id == to_location_id:
        raise StockError("La ubicacion de origen y destino son la misma")

    to_loc = q1("SELECT * FROM locations WHERE id=?", (to_location_id,))
    if not to_loc:
        raise StockError("Ubicacion de destino no encontrada")
    if to_loc["status"] != "DISPONIBLE":
        raise StockError(f"La ubicacion {to_loc['full_code']} no esta disponible (estado: {to_loc['status']})")
    if to_loc["capacity"]:
        occ = q1(
            """SELECT COALESCE(SUM(qty),0) as q FROM inventory_balances
               WHERE location_id=? AND status IN ('DISPONIBLE','POR_TRABAJAR','RESERVADO','CUARENTENA','BLOQUEADO','DANADO')""",
            (to_location_id,),
        )["q"]
        free = to_loc["capacity"] - occ
        if free < qty - 1e-6:
            raise StockError(f"Capacidad insuficiente en {to_loc['full_code']}: libre {free:g}, requerido {qty:g}")

    record_movement(
        "TRANSFERENCIA", product_id, client_id, qty, user_id,
        lot_id=lot_id, from_location_id=from_location_id, from_status="DISPONIBLE",
        to_location_id=to_location_id, to_status="DISPONIBLE",
        reason=reason or "Reubicacion de mercaderia",
    )
    # Mantiene reception_items.location_id sincronizado para que las vistas de
    # recepciones sigan mostrando donde esta el producto realmente hoy. Se usa
    # "IS" (no "=") porque from_location_id puede ser NULL de verdad (stock
    # que nunca tuvo ubicacion, ej. importado) y en SQL "columna = NULL" nunca
    # es verdadero -- "IS" si compara NULL correctamente.
    execute(
        """UPDATE reception_items SET location_id=?
           WHERE location_id IS ? AND product_id=? AND (lot_id IS ? OR lot_id=?)""",
        (to_location_id, from_location_id, product_id, lot_id, lot_id),
    )


def _reserve_qty_for_product(dispatch_item_id, product_id, qty_needed, dispatch, user_id, lot_id=None, kit_note=None):
    """Reserva `qty_needed` unidades DISPONIBLES de `product_id` (FEFO/FIFO) para
    una linea de despacho. Es el motor interno que usa tanto un producto normal
    como cada componente de un combo/kit."""
    remaining = qty_needed
    allocations = []
    candidates = available_balances_for_product(product_id, dispatch["client_id"], lot_id=lot_id)
    product_desc = q1("SELECT description FROM products WHERE id=?", (product_id,))["description"]
    if not candidates:
        raise StockError(f"No hay stock disponible de '{product_desc}'" + (f" (componente del combo)" if kit_note else ""))

    total = sum(c["qty"] for c in candidates)
    if total < remaining - 1e-6:
        raise StockError(
            f"Stock insuficiente de '{product_desc}'" + (" (componente del combo)" if kit_note else "") +
            f": disponible {total:g}, requerido {remaining:g}"
        )

    for c in candidates:
        if remaining <= 1e-6:
            break
        take = min(c["qty"], remaining)
        record_movement(
            "RESERVA", product_id, dispatch["client_id"], take, user_id,
            lot_id=c["lot_id"], from_location_id=c["location_id"], from_status="DISPONIBLE",
            to_location_id=c["location_id"], to_status="RESERVADO",
            reference_type="DISPATCH", reference_id=dispatch["id"],
            reason=f"Reserva FEFO/FIFO para despacho {dispatch['dispatch_number']}" + (f" ({kit_note})" if kit_note else ""),
        )
        rid = execute(
            """INSERT INTO reservations (dispatch_item_id, product_id, lot_id, location_id, client_id, qty, status, reason)
               VALUES (?,?,?,?,?,?,'ACTIVA',?)""",
            (dispatch_item_id, product_id, c["lot_id"], c["location_id"], dispatch["client_id"], take,
             "FEFO" if c["expiration_date"] else "FIFO"),
        )
        why = (f"vence {c['expiration_date']}" if c["expiration_date"] else f"ingreso mas antiguo ({c['lot_created_at']})")
        loc_label = c["location_code"] or "sin ubicacion de rack asignada (stock importado sin ubicar)"
        allocations.append({
            "reservation_id": rid, "location_code": c["location_code"], "lot_code": c["lot_code"],
            "qty": take, "product_description": product_desc,
            "reason": f"Se sugiere {loc_label} / lote {c['lot_code'] or 's/lote'} porque {why}."
            + (f" — componente de combo: {kit_note}" if kit_note else ""),
        })
        remaining -= take

    return allocations


def reserve_for_dispatch_item(dispatch_item_id, user_id):
    """Reserva stock DISPONIBLE (FEFO/FIFO) para cubrir qty_requested de una
    linea de despacho. Si el producto es un COMBO (tiene componentes
    definidos en product_components), no reserva el combo -- reserva cada
    componente segun su cantidad por combo x la cantidad de combos pedida."""
    item = q1("SELECT * FROM dispatch_items WHERE id=?", (dispatch_item_id,))
    dispatch = q1("SELECT * FROM dispatches WHERE id=?", (item["dispatch_id"],))
    components = q("SELECT * FROM product_components WHERE kit_product_id=?", (item["product_id"],))

    if components:
        kit_desc = q1("SELECT description FROM products WHERE id=?", (item["product_id"],))["description"]
        allocations = []
        for comp in components:
            comp_qty_needed = item["qty_requested"] * comp["qty_per_kit"]
            allocations += _reserve_qty_for_product(
                dispatch_item_id, comp["component_product_id"], comp_qty_needed, dispatch, user_id,
                kit_note=f"combo '{kit_desc}' x{item['qty_requested']:g}",
            )
        return allocations

    return _reserve_qty_for_product(dispatch_item_id, item["product_id"], item["qty_requested"], dispatch, user_id, lot_id=item["lot_id"])


def release_reservation(reservation_id, user_id, reason="Liberacion manual"):
    resv = q1("SELECT * FROM reservations WHERE id=?", (reservation_id,))
    if not resv or resv["status"] != "ACTIVA":
        raise StockError("Reserva no encontrada o ya no esta activa")
    record_movement(
        "LIBERACION_RESERVA", resv["product_id"], resv["client_id"], resv["qty"], user_id,
        lot_id=resv["lot_id"], from_location_id=resv["location_id"], from_status="RESERVADO",
        to_location_id=resv["location_id"], to_status="DISPONIBLE",
        reference_type="DISPATCH", reference_id=resv["dispatch_item_id"], reason=reason,
    )
    execute("UPDATE reservations SET status='LIBERADA' WHERE id=?", (reservation_id,))


def confirm_dispatch_movement(reservation_id, user_id, dispatch_id):
    resv = q1("SELECT * FROM reservations WHERE id=?", (reservation_id,))
    if not resv or resv["status"] != "ACTIVA":
        raise StockError("Reserva no encontrada o ya no esta activa")
    record_movement(
        "DESPACHO", resv["product_id"], resv["client_id"], resv["qty"], user_id,
        lot_id=resv["lot_id"], from_location_id=resv["location_id"], from_status="RESERVADO",
        to_location_id=None, to_status=None,
        reference_type="DISPATCH", reference_id=dispatch_id, reason="Salida confirmada de almacen",
    )
    execute("UPDATE reservations SET status='CONSUMIDA' WHERE id=?", (reservation_id,))


# ---------------------------------------------------------------------------
def quick_dispatch(dispatch_id, user_id):
    """Hace TODO el ciclo de despacho de un solo golpe: reserva (FEFO/FIFO) lo
    que falte, genera picking, marca todas las lineas como pickeadas
    completas, verifica y cierra -- descontando el stock real al final. Pensado
    para el caso normal (se despacha exactamente lo solicitado, sin
    diferencias); si algo necesita picking parcial o revision, se sigue
    pudiendo hacer paso a paso con los botones de siempre."""
    dispatch = q1("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if not dispatch:
        raise StockError("Despacho no encontrado")
    if dispatch["status"] in ("CERRADO", "CANCELADO"):
        raise StockError(f"Este despacho ya esta {dispatch['status']}")
    items = q("SELECT * FROM dispatch_items WHERE dispatch_id=?", (dispatch_id,))
    if not items:
        raise StockError("El despacho no tiene lineas. Agregue al menos un producto antes de despachar.")

    # 1) Reservar (FEFO/FIFO) las lineas que todavia no tengan nada reservado.
    for item in items:
        reserved = q1(
            "SELECT COALESCE(SUM(qty),0) as q FROM reservations WHERE dispatch_item_id=? AND status='ACTIVA'",
            (item["id"],),
        )["q"]
        if reserved <= 1e-6:
            reserve_for_dispatch_item(item["id"], user_id)
        elif reserved < item["qty_requested"] - 1e-6:
            raise StockError(
                f"La linea de producto id={item['product_id']} tiene una reserva parcial previa; "
                f"complete o libere esa reserva manualmente antes de usar el despacho rapido."
            )

    # 2) Generar orden de picking (si ya existe una de un intento anterior, se reutiliza).
    po = q1("SELECT * FROM picking_orders WHERE dispatch_id=?", (dispatch_id,))
    if not po:
        reservations = q(
            """SELECT r.* FROM reservations r JOIN dispatch_items di ON di.id = r.dispatch_item_id
               WHERE di.dispatch_id=? AND r.status='ACTIVA' ORDER BY r.id""",
            (dispatch_id,),
        )
        po_id = execute("INSERT INTO picking_orders (dispatch_id, status) VALUES (?, 'PENDIENTE')", (dispatch_id,))
        for idx, r in enumerate(reservations, start=1):
            execute(
                """INSERT INTO picking_items (picking_order_id, reservation_id, product_id, lot_id, location_id,
                     qty_requested, sequence, status) VALUES (?,?,?,?,?,?,?,'PENDIENTE')""",
                (po_id, r["id"], r["product_id"], r["lot_id"], r["location_id"], r["qty"], idx),
            )
    else:
        po_id = po["id"]

    # 3) Marcar todas las lineas de picking como completas (se pidio == se entrego).
    execute(
        "UPDATE picking_items SET qty_picked=qty_requested, status='PICKEADO' WHERE picking_order_id=? AND status='PENDIENTE'",
        (po_id,),
    )
    execute("UPDATE picking_orders SET status='COMPLETADO' WHERE id=?", (po_id,))
    execute("UPDATE dispatches SET status='EN_PICKING', picking_at=COALESCE(picking_at, datetime('now')) WHERE id=?", (dispatch_id,))

    # 4) Verificar.
    execute("UPDATE dispatches SET status='VERIFICADO', verified_at=datetime('now') WHERE id=?", (dispatch_id,))

    # 5) Cerrar: descuenta el stock real de cada reserva activa.
    active_resv = q(
        "SELECT r.* FROM reservations r JOIN dispatch_items di ON di.id=r.dispatch_item_id WHERE di.dispatch_id=? AND r.status='ACTIVA'",
        (dispatch_id,),
    )
    for r in active_resv:
        confirm_dispatch_movement(r["id"], user_id, dispatch_id)
    execute(
        "UPDATE dispatches SET status='CERRADO', closed_at=datetime('now'), prepared_at=COALESCE(prepared_at, datetime('now')) WHERE id=?",
        (dispatch_id,),
    )
    _notify_dispatch_closed(dispatch_id)
    return {"picking_order_id": po_id, "lines": len(items)}


def _notify_dispatch_closed(dispatch_id):
    """Aviso por correo cuando se cierra un despacho: cliente, items,
    cantidades. Si el correo falla o no esta configurado, no interrumpe el
    despacho -- ya quedo cerrado igual, esto es solo la notificacion."""
    try:
        from services import email_service
        dispatch = q1(
            """SELECT d.*, c.name as client_name FROM dispatches d JOIN clients c ON c.id=d.client_id WHERE d.id=?""",
            (dispatch_id,),
        )
        items = q(
            """SELECT di.qty_requested, p.sku_code, p.description FROM dispatch_items di
               JOIN products p ON p.id=di.product_id WHERE di.dispatch_id=?""",
            (dispatch_id,),
        )
        rows_html = "".join(
            f"<tr><td style='padding:4px 10px'>{it['sku_code']}</td><td style='padding:4px 10px'>{it['description']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{it['qty_requested']:g}</td></tr>"
            for it in items
        )
        html = f"""
          <div style="font-family:Arial,sans-serif;color:#1a2130">
            <h2 style="color:#141d30">📦 Despacho cerrado: {dispatch['dispatch_number']}</h2>
            <p><strong>Cliente:</strong> {dispatch['client_name']}<br>
               <strong>Fecha:</strong> {dispatch['dispatch_date']}<br>
               <strong>Guia:</strong> {dispatch.get('guide_number') or '—'}<br>
               <strong>N° Pedido:</strong> {dispatch.get('order_number') or '—'}<br>
               <strong>Destino:</strong> {dispatch.get('destination') or '—'}</p>
            <table style="border-collapse:collapse;margin-top:10px">
              <tr style="background:#f0f2f7"><th style="padding:4px 10px;text-align:left">SKU</th><th style="padding:4px 10px;text-align:left">Producto</th><th style="padding:4px 10px;text-align:right">Cantidad</th></tr>
              {rows_html}
            </table>
          </div>"""
        email_service.send_email(f"Despacho cerrado — {dispatch['dispatch_number']} ({dispatch['client_name']})", html)
    except Exception as e:
        print(f"[email] No se pudo preparar el aviso de despacho: {e}")


def send_daily_summary():
    """Arma y envia el correo de resumen diario: recepciones/despachos de
    hoy, alertas pendientes (calidad observada, vencimientos, ubicaciones
    bloqueadas). Pensado para dispararse una vez al dia desde un servicio
    externo de cron (ver /admin/send-daily-summary)."""
    import datetime
    from services import email_service
    today = datetime.date.today().isoformat()

    receptions_today = q1("SELECT COUNT(*) as n FROM receptions WHERE reception_date=?", (today,))["n"]
    dispatches_today = q1("SELECT COUNT(*) as n FROM dispatches WHERE dispatch_date=?", (today,))["n"]
    units_received = q1(
        "SELECT COALESCE(SUM(qty),0) as n FROM inventory_movements WHERE movement_type='RECEPCION' AND date(movement_date)=?",
        (today,),
    )["n"]
    units_dispatched = q1(
        "SELECT COALESCE(SUM(qty),0) as n FROM inventory_movements WHERE movement_type='DESPACHO' AND date(movement_date)=?",
        (today,),
    )["n"]
    receptions_observed = q1("SELECT COUNT(*) as n FROM receptions WHERE status='OBSERVADO'")["n"]
    dispatches_observed = q1("SELECT COUNT(*) as n FROM dispatches WHERE status='OBSERVADO'")["n"]
    pending_locate = q1(
        "SELECT COUNT(*) as n FROM reception_items WHERE storage_status IN ('PENDIENTE','PARCIAL') AND quality_status IN ('DISPONIBLE','OBSERVADO')"
    )["n"]
    expired = q1(
        """SELECT COALESCE(SUM(b.qty),0) as qty, COUNT(DISTINCT b.product_id) as skus
           FROM inventory_balances b JOIN lots l ON l.id=b.lot_id
           WHERE b.status='DISPONIBLE' AND l.expiration_date IS NOT NULL AND l.expiration_date < ?""",
        (today,),
    )
    soon_limit = (datetime.date.today() + datetime.timedelta(days=15)).isoformat()
    expiring_soon = q1(
        """SELECT COALESCE(SUM(b.qty),0) as qty, COUNT(DISTINCT b.product_id) as skus
           FROM inventory_balances b JOIN lots l ON l.id=b.lot_id
           WHERE b.status='DISPONIBLE' AND l.expiration_date IS NOT NULL
             AND l.expiration_date <= ? AND l.expiration_date >= ?""",
        (soon_limit, today),
    )

    alert_lines = []
    if receptions_observed:
        alert_lines.append(f"⚠️ {receptions_observed} recepcion(es) con calidad observada, pendientes de revision")
    if dispatches_observed:
        alert_lines.append(f"⚠️ {dispatches_observed} despacho(s) observado(s), pendientes de revision")
    if pending_locate:
        alert_lines.append(f"📍 {pending_locate} producto(s) aprobados por calidad pero todavia sin ubicar en rack")
    if expired["qty"]:
        alert_lines.append(f"⛔ {expired['qty']:g} unidades YA VENCIDAS en {expired['skus']} SKU(s) — revisar cuanto antes")
    if expiring_soon["qty"]:
        alert_lines.append(f"⏳ {expiring_soon['qty']:g} unidades vencen en los proximos 15 dias ({expiring_soon['skus']} SKU(s))")

    alerts_html = (
        "<ul>" + "".join(f"<li style='margin-bottom:4px'>{a}</li>" for a in alert_lines) + "</ul>"
        if alert_lines
        else "<p style='color:#15803d'>✓ Sin alertas pendientes hoy.</p>"
    )

    html = f"""
      <div style="font-family:Arial,sans-serif;color:#1a2130;max-width:520px">
        <h2 style="color:#141d30">📋 Resumen del dia — {today}</h2>
        <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
          <tr><td style="padding:6px 0"><strong>Recepciones hoy:</strong></td><td style="text-align:right">{receptions_today} ({units_received:g} unidades)</td></tr>
          <tr><td style="padding:6px 0"><strong>Despachos hoy:</strong></td><td style="text-align:right">{dispatches_today} ({units_dispatched:g} unidades)</td></tr>
        </table>
        <h3 style="color:#141d30;margin-bottom:6px">Alertas pendientes</h3>
        {alerts_html}
      </div>"""
    email_service.send_email(f"Resumen diario CIANSE — {today}", html)


def quarantine(reception_item_id, user_id, qty, reason):
    item = q1("SELECT * FROM reception_items WHERE id=?", (reception_item_id,))
    reception = q1("SELECT * FROM receptions WHERE id=?", (item["reception_id"],))
    record_movement(
        "CUARENTENA", item["product_id"], reception["client_id"], qty, user_id,
        lot_id=item["lot_id"], from_location_id=item["location_id"], from_status="DISPONIBLE",
        to_location_id=item["location_id"], to_status="CUARENTENA",
        reference_type="RECEPTION", reference_id=reception["id"], reason=reason,
    )


def adjust(product_id, client_id, lot_id, location_id, status, qty, user_id, positive, reference_type, reference_id, reason):
    if positive:
        record_movement("AJUSTE_POSITIVO", product_id, client_id, qty, user_id, lot_id=lot_id,
                         to_location_id=location_id, to_status=status,
                         reference_type=reference_type, reference_id=reference_id, reason=reason)
    else:
        record_movement("AJUSTE_NEGATIVO", product_id, client_id, qty, user_id, lot_id=lot_id,
                         from_location_id=location_id, from_status=status,
                         reference_type=reference_type, reference_id=reference_id, reason=reason)


def merma(product_id, client_id, lot_id, location_id, status, qty, user_id, reason):
    record_movement("MERMA", product_id, client_id, qty, user_id, lot_id=lot_id,
                     from_location_id=location_id, from_status=status,
                     reference_type="MANUAL", reference_id=None, reason=reason)
