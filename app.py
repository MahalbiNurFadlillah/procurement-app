import os
import re
import uuid
from datetime import date, datetime, time, timedelta
from functools import wraps
from io import BytesIO
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from models import (
    InventoryItem,
    Notification,
    PurchaseOrder,
    PurchaseRequest,
    Receiving,
    Supplier,
    User,
    db,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}
ROLES = ("requester", "procurement", "approver", "warehouse", "admin")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("PROCUREMENT_SECRET_KEY", "development-only-change-me"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "procurement.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Silakan login untuk melanjutkan."
login_manager.login_message_category = "warning"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def allowed_file(filename, extensions):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in extensions
    )


def save_upload(file_storage, extensions):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename, extensions):
        raise ValueError("Format file tidak didukung.")
    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        raise ValueError("Nama file tidak valid.")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_storage.save(os.path.join(UPLOAD_FOLDER, stored_name))
    return stored_name


def parse_request_form():
    item_name = request.form.get("item_name", "").strip()
    specification = request.form.get("specification", "").strip()
    quantity_value = request.form.get("quantity", "").strip()
    budget_value = request.form.get("budget", "").strip()
    if not item_name:
        raise ValueError("Nama barang wajib diisi.")
    try:
        quantity = int(quantity_value)
    except ValueError as exc:
        raise ValueError("Kuantitas harus berupa bilangan bulat.") from exc
    if quantity < 1:
        raise ValueError("Kuantitas minimal 1.")
    try:
        budget = float(budget_value) if budget_value else None
    except ValueError as exc:
        raise ValueError("Anggaran harus berupa angka.") from exc
    if budget is not None and budget < 0:
        raise ValueError("Anggaran tidak boleh negatif.")
    return item_name, quantity, specification, budget


def extract_ocr_fields(text):
    patterns = {
        "item_name": r"^(?:nama\s*barang|barang|item|nama\s*item)\s*[:：-]\s*(.+)$",
        "quantity": r"^(?:qty|quantity|kuantitas|jumlah)\s*[:：-]\s*(\d+)\b.*$",
        "specification": r"^(?:spesifikasi|specification|spec)\s*[:：-]\s*(.+)$",
        "budget": r"^(?:budget|anggaran)\s*[:：-]\s*[RrPp.\s]*([\d.,]+).*$",
    }
    fields = {}
    for line in text.splitlines():
        normalized = line.strip()
        for field, pattern in patterns.items():
            match = re.match(pattern, normalized, re.IGNORECASE)
            if match and field not in fields:
                fields[field] = match.group(1).strip()
    if "budget" in fields:
        fields["budget"] = fields["budget"].replace(".", "").replace(",", ".")
    return fields


def notify_requester(purchase_request, message, category="info"):
    db.session.add(
        Notification(
            user_id=purchase_request.requester_id,
            request_id=purchase_request.id,
            message=message,
            category=category,
        )
    )


@app.context_processor
def notification_context():
    if not current_user.is_authenticated or current_user.role != "requester":
        return {"unread_notification_count": 0}
    count = Notification.query.filter_by(
        user_id=current_user.id, read_at=None
    ).count()
    return {"unread_notification_count": count}


def init_db():
    with app.app_context():
        db.create_all()
        demo_users = [
            ("admin", os.environ.get("PROCUREMENT_ADMIN_PASSWORD", "admin123"), "admin", "Administrator"),
            ("requester1", "pass", "requester", "Requester Demo"),
            ("procurement1", "pass", "procurement", "Procurement Demo"),
            ("approver1", "pass", "approver", "Approver Demo"),
            ("warehouse1", "pass", "warehouse", "Warehouse Demo"),
        ]
        for username, password, role, full_name in demo_users:
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(
                        username=username,
                        password=generate_password_hash(password),
                        role=role,
                        full_name=full_name,
                    )
                )
        if not Supplier.query.first():
            db.session.add(
                Supplier(
                    name="PT Maju Jaya",
                    contact="08123456789",
                    address="Jakarta",
                    active=True,
                )
            )
        db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            next_url = request.args.get("next", "")
            if (
                next_url.startswith("/")
                and not next_url.startswith("//")
                and "\\" not in next_url
                and not urlsplit(next_url).netloc
            ):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("Login gagal. Periksa username dan password.", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Anda berhasil logout.", "info")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    count_query = db.session.query(
        PurchaseRequest.status, func.count(PurchaseRequest.id)
    )
    if current_user.role == "requester":
        count_query = count_query.filter_by(requester_id=current_user.id)
    status_counts = dict(count_query.group_by(PurchaseRequest.status).all())
    if current_user.role == "requester":
        items = (
            PurchaseRequest.query.filter_by(requester_id=current_user.id)
            .order_by(PurchaseRequest.created_at.desc())
            .limit(8)
            .all()
        )
    elif current_user.role == "approver":
        items = PurchaseRequest.query.filter_by(status="pending").order_by(
            PurchaseRequest.created_at.asc()
        ).all()
    elif current_user.role == "procurement":
        items = PurchaseRequest.query.filter_by(status="approved").order_by(
            PurchaseRequest.created_at.asc()
        ).all()
    elif current_user.role == "warehouse":
        items = PurchaseOrder.query.filter(PurchaseOrder.status == "sent").order_by(
            PurchaseOrder.created_at.asc()
        ).all()
    else:
        items = PurchaseRequest.query.order_by(
            PurchaseRequest.created_at.desc()
        ).limit(8).all()
    stock_levels = {
        item.item_name: item.quantity for item in InventoryItem.query.all()
    }
    return render_template(
        "dashboard.html",
        items=items,
        status_counts=status_counts,
        stock_levels=stock_levels,
    )


@app.route("/request/new", methods=["GET", "POST"])
@roles_required("requester")
def create_request():
    if request.method == "POST":
        try:
            item_name, quantity, specification, budget = parse_request_form()
            attachment = save_upload(
                request.files.get("attachment"), ALLOWED_DOCUMENT_EXTENSIONS
            )
            purchase_request = PurchaseRequest(
                requester_id=current_user.id,
                item_name=item_name,
                quantity=quantity,
                specification=specification,
                budget=budget,
                attachment_path=attachment,
            )
            db.session.add(purchase_request)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("request_form.html", prefill=request.form)
        flash("Purchase Request berhasil diajukan untuk approval.", "success")
        return redirect(url_for("request_list"))
    return render_template("request_form.html", prefill=request.args)


@app.route("/request/<int:req_id>/resubmit", methods=["POST"])
@roles_required("requester")
def resubmit_request(req_id):
    purchase_request = PurchaseRequest.query.get_or_404(req_id)
    if (
        purchase_request.requester_id != current_user.id
        or purchase_request.status != "rejected"
    ):
        abort(403)
    try:
        item_name, quantity, specification, budget = parse_request_form()
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("request_list"))
    purchase_request.item_name = item_name
    purchase_request.quantity = quantity
    purchase_request.specification = specification
    purchase_request.budget = budget
    purchase_request.status = "pending"
    purchase_request.approver_note = None
    notify_requester(
        purchase_request,
        f"Request PR-{purchase_request.id:04d} telah dikirim kembali untuk approval.",
    )
    db.session.commit()
    flash("Request telah dikirim kembali untuk approval.", "success")
    return redirect(url_for("request_list"))


@app.route("/requests")
@login_required
def request_list():
    query = PurchaseRequest.query
    if current_user.role == "requester":
        query = query.filter_by(requester_id=current_user.id)
    elif current_user.role not in ("procurement", "approver", "warehouse", "admin"):
        abort(403)
    items = query.order_by(PurchaseRequest.created_at.desc()).all()
    return render_template("request_list.html", items=items)


@app.route("/approval")
@roles_required("approver")
def approval_list():
    items = PurchaseRequest.query.filter_by(status="pending").order_by(
        PurchaseRequest.created_at.asc()
    ).all()
    return render_template("approval_list.html", items=items)


@app.route("/approval/<int:req_id>/<action>", methods=["POST"])
@roles_required("approver")
def approve_request(req_id, action):
    if action not in ("approve", "reject"):
        abort(404)
    purchase_request = PurchaseRequest.query.get_or_404(req_id)
    if purchase_request.status != "pending":
        flash("Request sudah diproses.", "warning")
        return redirect(url_for("approval_list"))
    note = request.form.get("note", "").strip()
    if action == "reject" and not note:
        flash("Catatan wajib diisi saat menolak request.", "danger")
        return redirect(url_for("approval_list"))
    purchase_request.status = "approved" if action == "approve" else "rejected"
    purchase_request.approver_note = note or "Disetujui."
    status_message = (
        f"Request PR-{purchase_request.id:04d} ({purchase_request.item_name}) "
        f"{'disetujui' if action == 'approve' else 'dikembalikan'}."
    )
    if note:
        status_message += f" Catatan: {note}"
    notify_requester(
        purchase_request,
        status_message,
        "success" if action == "approve" else "warning",
    )
    db.session.commit()
    flash(
        "Request berhasil disetujui."
        if action == "approve"
        else "Request dikembalikan kepada requester.",
        "success",
    )
    return redirect(url_for("approval_list"))


@app.route("/inventory")
@roles_required("procurement", "warehouse", "admin")
def inventory_list():
    items = InventoryItem.query.order_by(InventoryItem.item_name.asc()).all()
    return render_template("inventory_list.html", items=items)


@app.route("/inventory/update", methods=["POST"])
@roles_required("warehouse", "admin")
def update_inventory():
    item_name = request.form.get("item_name", "").strip()
    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError:
        flash("Kuantitas stok harus berupa bilangan bulat.", "danger")
        return redirect(url_for("inventory_list"))
    if not item_name or quantity < 0:
        flash("Nama barang wajib diisi dan stok tidak boleh negatif.", "danger")
        return redirect(url_for("inventory_list"))
    item = InventoryItem.query.filter_by(item_name=item_name).first()
    if item is None:
        item = InventoryItem(item_name=item_name, quantity=quantity)
        db.session.add(item)
    else:
        item.quantity = quantity
        item.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Stok berhasil diperbarui.", "success")
    return redirect(url_for("inventory_list"))


@app.route("/request/<int:req_id>/dispatch", methods=["POST"])
@roles_required("procurement")
def dispatch_from_stock(req_id):
    purchase_request = PurchaseRequest.query.get_or_404(req_id)
    if purchase_request.status != "approved":
        flash("Request belum disetujui atau sudah diproses.", "warning")
        return redirect(url_for("dashboard"))
    item = InventoryItem.query.filter_by(item_name=purchase_request.item_name).with_for_update().first()
    if item is None or item.quantity < purchase_request.quantity:
        flash("Stok tidak mencukupi. Buat Purchase Order untuk supplier.", "warning")
        return redirect(url_for("dashboard"))
    item.quantity -= purchase_request.quantity
    item.updated_at = datetime.utcnow()
    purchase_request.status = "received"
    purchase_request.approver_note = "Dipenuhi langsung dari stok gudang."
    notify_requester(
        purchase_request,
        f"Request PR-{purchase_request.id:04d} telah dipenuhi dari stok gudang.",
        "success",
    )
    db.session.commit()
    flash("Dispatch Order berhasil dibuat dan request dipenuhi dari stok.", "success")
    return redirect(url_for("dashboard"))


@app.route("/po")
@roles_required("procurement", "warehouse", "admin")
def po_list():
    orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()
    return render_template("po_list.html", orders=orders)


@app.route("/po/create/<int:req_id>", methods=["GET", "POST"])
@roles_required("procurement")
def create_po(req_id):
    purchase_request = PurchaseRequest.query.get_or_404(req_id)
    if purchase_request.status != "approved":
        flash("Request belum disetujui atau sudah diproses.", "warning")
        return redirect(url_for("dashboard"))
    stock = InventoryItem.query.filter_by(item_name=purchase_request.item_name).first()
    if stock and stock.quantity >= purchase_request.quantity:
        flash("Stok mencukupi. Gunakan aksi Dispatch dari stok.", "info")
        return redirect(url_for("dashboard"))
    suppliers = Supplier.query.filter_by(active=True).order_by(Supplier.name).all()
    if not suppliers:
        flash("Tambahkan supplier aktif sebelum membuat PO.", "warning")
        return redirect(url_for("supplier_list"))
    if request.method == "POST":
        try:
            supplier_id = int(request.form.get("supplier_id", ""))
        except ValueError:
            flash("Supplier tidak valid.", "danger")
            return render_template(
                "po_form.html", pr=purchase_request, suppliers=suppliers
            )
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier or not supplier.active:
            flash("Pilih supplier yang aktif.", "danger")
            return render_template(
                "po_form.html", pr=purchase_request, suppliers=suppliers
            )
        po_number = f"PO-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
        order = PurchaseOrder(
            purchase_request=purchase_request,
            supplier=supplier,
            po_number=po_number,
            payment_terms=request.form.get("payment_terms", "").strip()
            or "Sesuai kesepakatan",
            status="draft",
        )
        db.session.add(order)
        db.session.commit()
        flash(f"PO {po_number} berhasil dibuat sebagai draft.", "success")
        return redirect(url_for("po_list"))
    return render_template("po_form.html", pr=purchase_request, suppliers=suppliers)


@app.route("/po/<int:po_id>/send", methods=["POST"])
@roles_required("procurement")
def send_po(po_id):
    order = PurchaseOrder.query.get_or_404(po_id)
    if order.status != "draft":
        flash("Hanya PO draft yang dapat dikirim.", "warning")
    else:
        order.status = "sent"
        order.purchase_request.status = "po_created"
        notify_requester(
            order.purchase_request,
            f"PO {order.po_number} untuk request PR-{order.request_id:04d} telah dikirim ke supplier.",
        )
        db.session.commit()
        flash(f"PO {order.po_number} ditandai telah dikirim ke supplier.", "success")
    return redirect(url_for("po_list"))


@app.route("/po/<int:po_id>/close", methods=["POST"])
@roles_required("procurement", "admin")
def close_po(po_id):
    order = PurchaseOrder.query.get_or_404(po_id)
    if order.status != "received":
        flash("Hanya PO yang sudah diterima yang dapat ditutup.", "warning")
    else:
        order.status = "closed"
        db.session.commit()
        flash(f"PO {order.po_number} berhasil ditutup.", "success")
    return redirect(url_for("po_list"))


@app.route("/po/<int:po_id>/pdf")
@roles_required("procurement", "warehouse", "admin")
def po_pdf(po_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    order = PurchaseOrder.query.get_or_404(po_id)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle(f"Purchase Order {order.po_number}")
    text = pdf.beginText(50, 790)
    text.setFont("Helvetica-Bold", 16)
    text.textLine("PURCHASE ORDER")
    text.setFont("Helvetica", 11)
    text.textLine("")
    text.textLine(f"Nomor PO: {order.po_number}")
    text.textLine(f"Tanggal: {order.created_at:%d-%m-%Y}")
    text.textLine(f"Supplier: {order.supplier.name}")
    text.textLine(f"Kontak: {order.supplier.contact or '-'}")
    text.textLine(f"Alamat: {order.supplier.address or '-'}")
    text.textLine(f"Termin pembayaran: {order.payment_terms}")
    text.textLine(f"Status: {order.status}")
    text.textLine("")
    text.textLine(f"Barang: {order.purchase_request.item_name}")
    text.textLine(f"Kuantitas: {order.purchase_request.quantity}")
    text.textLine(f"Spesifikasi: {order.purchase_request.specification or '-'}")
    text.textLine(
        f"Anggaran: Rp {order.purchase_request.budget:,.0f}"
        if order.purchase_request.budget is not None
        else "Anggaran: -"
    )
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{order.po_number}.pdf"'
    )
    return response


@app.route("/receivings")
@roles_required("warehouse", "admin")
def receiving_list():
    orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()
    history = Receiving.query.order_by(Receiving.received_at.desc()).limit(30).all()
    return render_template(
        "receiving_list.html", orders=orders, history=history
    )


@app.route("/receiving/<int:po_id>", methods=["GET", "POST"])
@roles_required("warehouse", "admin")
def receiving(po_id):
    order = PurchaseOrder.query.get_or_404(po_id)
    if order.status != "sent":
        flash("PO tidak sedang menunggu penerimaan.", "warning")
        return redirect(url_for("receiving_list"))
    if request.method == "POST":
        try:
            received_qty = int(request.form.get("received_qty", ""))
        except ValueError:
            flash("Kuantitas diterima harus berupa bilangan bulat.", "danger")
            return render_template("receiving_form.html", po=order)
        condition = request.form.get("condition", "").strip()
        compliant = request.form.get("compliant") == "yes"
        note = request.form.get("note", "").strip()
        expected_qty = order.purchase_request.quantity
        if received_qty < 0 or not condition:
            flash("Kuantitas tidak boleh negatif dan kondisi wajib diisi.", "danger")
            return render_template("receiving_form.html", po=order)
        if compliant and received_qty != expected_qty:
            flash("Penerimaan sesuai PO harus memiliki kuantitas yang tepat.", "danger")
            return render_template("receiving_form.html", po=order)
        if not compliant and not note:
            flash("Catatan komplain wajib diisi jika barang tidak sesuai PO.", "danger")
            return render_template("receiving_form.html", po=order)
        receipt = Receiving(
            purchase_order=order,
            received_qty=received_qty,
            condition=condition,
            compliant=compliant,
            note=note,
        )
        db.session.add(receipt)
        if compliant:
            inventory = InventoryItem.query.filter_by(
                item_name=order.purchase_request.item_name
            ).first()
            if inventory is None:
                inventory = InventoryItem(
                    item_name=order.purchase_request.item_name,
                    quantity=received_qty,
                )
                db.session.add(inventory)
            else:
                inventory.quantity += received_qty
                inventory.updated_at = datetime.utcnow()
            order.status = "received"
            order.purchase_request.status = "received"
            notify_requester(
                order.purchase_request,
                f"Barang untuk request PR-{order.request_id:04d} telah diterima dan sesuai PO.",
                "success",
            )
            flash("Barang sesuai PO; stok diperbarui dan penerimaan selesai.", "success")
        else:
            notify_requester(
                order.purchase_request,
                f"Penerimaan untuk request PR-{order.request_id:04d} tidak sesuai PO. "
                f"Komplain: {note}",
                "warning",
            )
            flash("Komplain tercatat. PO tetap terbuka untuk tindak lanjut supplier.", "warning")
        db.session.commit()
        return redirect(url_for("receiving_list"))
    return render_template("receiving_form.html", po=order)


@app.route("/suppliers")
@roles_required("procurement", "admin")
def supplier_list():
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    return render_template("supplier_list.html", suppliers=suppliers)


@app.route("/suppliers/new", methods=["GET", "POST"])
@app.route("/suppliers/<int:supplier_id>/edit", methods=["GET", "POST"])
@roles_required("procurement", "admin")
def supplier_form(supplier_id=None):
    supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
    if supplier_id and supplier is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Nama supplier wajib diisi.", "danger")
        else:
            if supplier is None:
                supplier = Supplier(name=name)
                db.session.add(supplier)
            supplier.name = name
            supplier.contact = request.form.get("contact", "").strip()
            supplier.address = request.form.get("address", "").strip()
            supplier.active = request.form.get("active") == "yes"
            db.session.commit()
            flash("Data supplier berhasil disimpan.", "success")
            return redirect(url_for("supplier_list"))
    return render_template("supplier_form.html", supplier=supplier)


@app.route("/users")
@roles_required("admin")
def user_list():
    users = User.query.order_by(User.username.asc()).all()
    return render_template("user_list.html", users=users, roles=ROLES)


@app.route("/users/new", methods=["GET", "POST"])
@roles_required("admin")
def user_create():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        if not username or len(password) < 8 or role not in ROLES:
            flash("Username wajib diisi, password minimal 8 karakter, dan role valid.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("Username sudah digunakan.", "danger")
        else:
            user = User(
                username=username,
                password=generate_password_hash(password),
                role=role,
                full_name=request.form.get("full_name", "").strip(),
                email=request.form.get("email", "").strip(),
            )
            db.session.add(user)
            db.session.commit()
            flash("Pengguna berhasil dibuat.", "success")
            return redirect(url_for("user_list"))
    return render_template("user_form.html", user=None, roles=ROLES)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@roles_required("admin")
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        if role not in ROLES:
            flash("Role tidak valid.", "danger")
        elif user.id == current_user.id and role != "admin":
            flash("Anda tidak dapat menghapus role admin akun sendiri.", "danger")
        elif password and len(password) < 8:
            flash("Password baru minimal 8 karakter.", "danger")
        else:
            user.role = role
            user.full_name = request.form.get("full_name", "").strip()
            user.email = request.form.get("email", "").strip()
            if password:
                user.password = generate_password_hash(password)
            db.session.commit()
            flash("Pengguna berhasil diperbarui.", "success")
            return redirect(url_for("user_list"))
    return render_template("user_form.html", user=user, roles=ROLES)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if password and len(password) < 8:
            flash("Password baru minimal 8 karakter.", "danger")
        else:
            current_user.full_name = full_name
            current_user.email = email
            if password:
                current_user.password = generate_password_hash(password)
            db.session.commit()
            flash("Profil berhasil diperbarui.", "success")
            return redirect(url_for("profile"))
    return render_template("profile.html")


@app.route("/notifications")
@roles_required("requester")
def notifications():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()
    ).all()
    return render_template("notifications.html", items=items)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@roles_required("requester")
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id, user_id=current_user.id
    ).first_or_404()
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/reports")
@roles_required("procurement", "warehouse", "admin")
def reports():
    supplier_id = request.args.get("supplier_id", type=int)
    orders_query = PurchaseOrder.query
    if supplier_id:
        orders_query = orders_query.filter_by(supplier_id=supplier_id)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    try:
        if start_date:
            orders_query = orders_query.filter(
                PurchaseOrder.created_at >= datetime.combine(
                    date.fromisoformat(start_date), time.min
                )
            )
        if end_date:
            orders_query = orders_query.filter(
                PurchaseOrder.created_at
                < datetime.combine(date.fromisoformat(end_date) + timedelta(days=1), time.min)
            )
    except ValueError:
        flash("Format tanggal laporan harus YYYY-MM-DD.", "warning")
        return redirect(url_for("reports", supplier_id=supplier_id))
    orders = orders_query.order_by(PurchaseOrder.created_at.desc()).all()
    receipts = Receiving.query.order_by(Receiving.received_at.desc()).all()
    status_counts = dict(
        db.session.query(PurchaseRequest.status, func.count(PurchaseRequest.id))
        .group_by(PurchaseRequest.status)
        .all()
    )
    return render_template(
        "reports.html",
        orders=orders,
        receipts=receipts,
        suppliers=Supplier.query.order_by(Supplier.name).all(),
        selected_supplier=supplier_id,
        status_counts=status_counts,
        start_date=start_date,
        end_date=end_date,
    )


@app.route("/ocr", methods=["GET", "POST"])
@roles_required("requester")
def ocr_upload():
    extracted_text = None
    extracted_fields = {}
    if request.method == "POST":
        try:
            stored_name = save_upload(
                request.files.get("image"),
                ALLOWED_IMAGE_EXTENSIONS | {"pdf"},
            )
            if not stored_name:
                raise ValueError("Pilih gambar atau PDF untuk diproses.")
            try:
                from pypdf import PdfReader
                import pypdfium2
                import pytesseract
                from PIL import Image
            except ImportError:
                flash(
                    "Ekstraksi OCR memerlukan Pillow, pypdfium2, pytesseract, "
                    "dan aplikasi Tesseract OCR.",
                    "warning",
                )
                return render_template(
                    "ocr_upload.html",
                    extracted_text=None,
                    extracted_fields={},
                    prefill_url=url_for("create_request"),
                )
            image_path = os.path.join(UPLOAD_FOLDER, stored_name)
            if stored_name.lower().endswith(".pdf"):
                from pypdf.errors import FileNotDecryptedError, PdfReadError

                try:
                    pdf = PdfReader(image_path)
                except (FileNotDecryptedError, PdfReadError) as exc:
                    raise ValueError("PDF tidak dapat dibaca atau dilindungi password.") from exc
                if len(pdf.pages) > 10:
                    raise ValueError("PDF maksimal 10 halaman.")
                extracted_text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                ).strip()
                if not extracted_text:
                    document = pypdfium2.PdfDocument(image_path)
                    extracted_text = "\n".join(
                        pytesseract.image_to_string(
                            document[index].render(scale=2).to_pil()
                        )
                        for index in range(len(document))
                    ).strip()
                    document.close()
            else:
                with Image.open(image_path) as image:
                    extracted_text = pytesseract.image_to_string(image)
            extracted_fields = extract_ocr_fields(extracted_text)
            flash("Teks berhasil diekstrak. Periksa hasil sebelum digunakan.", "info")
        except ValueError as exc:
            flash(str(exc), "danger")
        except (OSError, RuntimeError) as exc:
            flash(f"OCR gagal memproses gambar: {exc}", "danger")
    return render_template(
        "ocr_upload.html",
        extracted_text=extracted_text,
        extracted_fields=extracted_fields,
        prefill_url=url_for("create_request", **extracted_fields),
    )


@app.errorhandler(413)
def file_too_large(_error):
    flash("Ukuran file maksimal 8 MB.", "danger")
    return redirect(request.referrer or url_for("dashboard"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="Akses ditolak."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="Halaman tidak ditemukan."), 404


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
