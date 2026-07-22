from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "gaon_delivery.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-hosting")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def now_text() -> str:
    return datetime.now().strftime("%d-%m-%Y %I:%M %p")


def create_database() -> None:
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    connection = db()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            phone TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL CHECK(price > 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
            image_url TEXT DEFAULT '',
            is_available INTEGER NOT NULL DEFAULT 1,
            is_popular INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT NOT NULL UNIQUE,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            subtotal INTEGER NOT NULL,
            delivery_charge INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'COD',
            payment_status TEXT NOT NULL DEFAULT 'Pending',
            coupon_code TEXT DEFAULT '',
            discount INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            shop_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            shop_name TEXT NOT NULL,
            price INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS order_shop_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            shop_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            UNIQUE(order_id, shop_id),
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY(shop_id) REFERENCES shops(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('delivery_charge', '20')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('whatsapp_number', '')"
    )

    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('delivery_percent', '10')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('minimum_delivery_charge', '5')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('free_delivery_above', '500')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('upi_id', '')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('coupon_code', 'SAVE10')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('coupon_percent', '10')"
    )

    if connection.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 0:
        starter_shops = [
            ("Gaon Kirana Store", "kirana", generate_password_hash("1234"), ""),
            ("Dairy Shop", "dairy", generate_password_hash("1234"), ""),
            ("General Store", "general", generate_password_hash("1234"), ""),
        ]
        connection.executemany(
            """
            INSERT INTO shops (name, username, password_hash, phone)
            VALUES (?, ?, ?, ?)
            """,
            starter_shops,
        )

    if connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        shops = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id, name FROM shops").fetchall()
        }
        products = [
            (shops["Gaon Kirana Store"], "Aata 5 KG", 220, 25, 1),
            (shops["Gaon Kirana Store"], "Chawal 5 KG", 300, 20, 1),
            (shops["Gaon Kirana Store"], "Cheeni 1 KG", 50, 30, 0),
            (shops["Gaon Kirana Store"], "Sarson Tel 1 Litre", 150, 18, 1),
            (shops["Dairy Shop"], "Doodh 1 Litre", 65, 40, 1),
            (shops["Dairy Shop"], "Dahi 500 Gram", 40, 20, 0),
            (shops["General Store"], "Biscuit Packet", 20, 50, 1),
            (shops["General Store"], "Bath Soap", 35, 35, 0),
        ]
        connection.executemany(
            """
            INSERT INTO products
            (shop_id, name, price, stock, is_popular, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(*product, now_text()) for product in products],
        )

    connection.commit()
    connection.close()


def get_setting(key: str, default: str = "") -> str:
    connection = db()
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    connection.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    connection = db()
    connection.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    connection.commit()
    connection.close()


def save_image(uploaded_file) -> str:
    if not uploaded_file or not uploaded_file.filename:
        return ""

    filename = secure_filename(uploaded_file.filename)
    if "." not in filename:
        raise ValueError("Photo file sahi select karo.")

    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Sirf PNG JPG JPEG ya WEBP photo upload karo.")

    new_filename = f"{uuid4().hex}.{extension}"
    uploaded_file.save(UPLOAD_FOLDER / new_filename)
    return new_filename


def logged_in() -> bool:
    return bool(session.get("user_id"))


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return function(*args, **kwargs)

    return wrapper


def master_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if session.get("role") != "master":
            abort(403)
        return function(*args, **kwargs)

    return wrapper


def current_shop_id():
    return session.get("shop_id")


@app.context_processor
def global_values():
    return {
        "session_role": session.get("role"),
        "session_shop_name": session.get("shop_name"),
    }


@app.route("/")
def home():
    shop_filter = request.args.get("shop", type=int)
    search = request.args.get("q", "").strip()

    connection = db()
    shops = connection.execute(
        "SELECT * FROM shops WHERE is_active = 1 ORDER BY name"
    ).fetchall()

    query = """
        SELECT p.*, s.name AS shop_name
        FROM products p
        JOIN shops s ON s.id = p.shop_id
        WHERE p.is_available = 1 AND p.stock > 0 AND s.is_active = 1
    """
    params = []

    if shop_filter:
        query += " AND p.shop_id = ?"
        params.append(shop_filter)

    if search:
        query += " AND (LOWER(p.name) LIKE ? OR LOWER(s.name) LIKE ?)"
        search_pattern = f"%{search.lower()}%"
        params.extend([search_pattern, search_pattern])

    query += " ORDER BY p.is_popular DESC, s.name, p.name"
    products = connection.execute(query, params).fetchall()
    connection.close()

    return render_template(
        "index.html",
        products=products,
        shops=shops,
        selected_shop=shop_filter,
        search=search,
        delivery_percent=int(get_setting("delivery_percent", "10")),
        minimum_delivery_charge=int(get_setting("minimum_delivery_charge", "5")),
        free_delivery_above=int(get_setting("free_delivery_above", "500")),
        upi_id=get_setting("upi_id", ""),
        coupon_code=get_setting("coupon_code", "SAVE10"),
    )


@app.route("/checkout", methods=["POST"])
def checkout():
    customer_name = request.form.get("customer_name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    payment_method = request.form.get("payment_method", "COD").strip()
    entered_coupon = request.form.get("coupon_code", "").strip().upper()

    if payment_method not in {"COD", "UPI"}:
        payment_method = "COD"

    if not customer_name or not phone or not address:
        flash("Naam phone aur address bharna zaroori hai.")
        return redirect(url_for("home"))

    if not phone.isdigit() or len(phone) != 10:
        flash("Mobile number 10 digits ka hona chahiye.")
        return redirect(url_for("home"))

    quantities = {}
    for key, value in request.form.items():
        if not key.startswith("quantity_"):
            continue
        try:
            product_id = int(key.split("_", 1)[1])
            quantity = max(0, min(int(value), 20))
        except (ValueError, IndexError):
            continue
        if quantity > 0:
            quantities[product_id] = quantity

    if not quantities:
        flash("Cart me koi product add nahi hai.")
        return redirect(url_for("home"))

    connection = db()
    placeholders = ",".join("?" for _ in quantities)
    products = connection.execute(
        f"""
        SELECT p.*, s.name AS shop_name
        FROM products p
        JOIN shops s ON s.id = p.shop_id
        WHERE p.id IN ({placeholders})
          AND p.is_available = 1
          AND s.is_active = 1
        """,
        tuple(quantities.keys()),
    ).fetchall()

    selected_items = []
    subtotal = 0
    shops_in_order = set()

    for product in products:
        quantity = quantities.get(product["id"], 0)
        if quantity <= 0:
            continue
        if product["stock"] < quantity:
            connection.close()
            flash(f"{product['name']} ka sirf {product['stock']} stock available hai.")
            return redirect(url_for("home"))

        item_subtotal = product["price"] * quantity
        selected_items.append(
            {
                "product_id": product["id"],
                "shop_id": product["shop_id"],
                "product_name": product["name"],
                "shop_name": product["shop_name"],
                "price": product["price"],
                "quantity": quantity,
                "subtotal": item_subtotal,
            }
        )
        subtotal += item_subtotal
        shops_in_order.add(product["shop_id"])

    if not selected_items:
        connection.close()
        flash("Selected products available nahi hain.")
        return redirect(url_for("home"))

    delivery_percent = int(get_setting("delivery_percent", "10"))
    minimum_delivery_charge = int(get_setting("minimum_delivery_charge", "5"))
    free_delivery_above = int(get_setting("free_delivery_above", "500"))

    if subtotal >= free_delivery_above:
        delivery_charge = 0
    else:
        delivery_charge = max(
            minimum_delivery_charge,
            round(subtotal * delivery_percent / 100),
        )

    configured_coupon = get_setting("coupon_code", "SAVE10").upper()
    coupon_percent = int(get_setting("coupon_percent", "10"))
    discount = 0
    applied_coupon = ""
    if entered_coupon and entered_coupon == configured_coupon:
        discount = min(50, round(subtotal * coupon_percent / 100))
        applied_coupon = configured_coupon

    total = max(0, subtotal + delivery_charge - discount)
    payment_status = "Pay on Delivery" if payment_method == "COD" else "Pending UPI"
    tracking_code = f"GD{datetime.now().strftime('%y%m%d')}{uuid4().hex[:5].upper()}"

    try:
        cursor = connection.execute(
            """
            INSERT INTO orders
            (tracking_code, customer_name, phone, address, subtotal,
             delivery_charge, total, payment_method, payment_status,
             coupon_code, discount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tracking_code,
                customer_name,
                phone,
                address,
                subtotal,
                delivery_charge,
                total,
                payment_method,
                payment_status,
                applied_coupon,
                discount,
                now_text(),
            ),
        )
        order_id = cursor.lastrowid

        connection.executemany(
            """
            INSERT INTO order_items
            (order_id, product_id, shop_id, product_name, shop_name,
             price, quantity, subtotal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    item["product_id"],
                    item["shop_id"],
                    item["product_name"],
                    item["shop_name"],
                    item["price"],
                    item["quantity"],
                    item["subtotal"],
                )
                for item in selected_items
            ],
        )

        connection.executemany(
            """
            INSERT INTO order_shop_status (order_id, shop_id, status)
            VALUES (?, ?, 'Pending')
            """,
            [(order_id, shop_id) for shop_id in shops_in_order],
        )

        for item in selected_items:
            connection.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    connection.close()
    return render_template(
        "success.html",
        tracking_code=tracking_code,
        phone=phone,
        total=total,
        payment_method=payment_method,
        upi_id=get_setting("upi_id", ""),
    )


@app.route("/track", methods=["GET", "POST"])
def track_order():
    tracking_code = request.values.get("tracking_code", "").strip().upper()
    phone = request.values.get("phone", "").strip()
    order = None
    statuses = []
    items = []

    if tracking_code and phone:
        connection = db()
        order = connection.execute(
            """
            SELECT * FROM orders
            WHERE tracking_code = ? AND phone = ?
            """,
            (tracking_code, phone),
        ).fetchone()

        if order:
            statuses = connection.execute(
                """
                SELECT oss.status, s.name AS shop_name
                FROM order_shop_status oss
                JOIN shops s ON s.id = oss.shop_id
                WHERE oss.order_id = ?
                ORDER BY s.name
                """,
                (order["id"],),
            ).fetchall()

            items = connection.execute(
                """
                SELECT * FROM order_items
                WHERE order_id = ?
                ORDER BY shop_name, product_name
                """,
                (order["id"],),
            ).fetchall()

        connection.close()

        if not order:
            flash("Order nahi mila. Tracking code aur phone check karo.")

    return render_template(
        "track.html",
        order=order,
        statuses=statuses,
        items=items,
        tracking_code=tracking_code,
        phone=phone,
    )



@app.route("/history", methods=["GET", "POST"])
def order_history():
    phone = request.values.get("phone", "").strip()
    orders = []
    if phone:
        connection = db()
        orders = connection.execute(
            """
            SELECT o.*,
                   GROUP_CONCAT(DISTINCT oss.status) AS statuses
            FROM orders o
            LEFT JOIN order_shop_status oss ON oss.order_id = o.id
            WHERE o.phone = ?
            GROUP BY o.id
            ORDER BY o.id DESC
            """,
            (phone,),
        ).fetchall()
        connection.close()
        if not orders:
            flash("Is phone number par koi order nahi mila.")
    return render_template("history.html", phone=phone, orders=orders)


@app.route("/delivery")
@admin_required
def delivery_panel():
    if session.get("role") not in {"master", "delivery"}:
        abort(403)
    connection = db()
    orders = connection.execute(
        """
        SELECT o.*, GROUP_CONCAT(DISTINCT oss.status) AS statuses
        FROM orders o
        JOIN order_shop_status oss ON oss.order_id = o.id
        WHERE oss.status IN ('Accepted', 'Out for Delivery')
        GROUP BY o.id
        ORDER BY o.id DESC
        """
    ).fetchall()
    connection.close()
    return render_template("delivery.html", orders=orders)


@app.route("/delivery/<int:order_id>/status", methods=["POST"])
@admin_required
def delivery_update(order_id: int):
    if session.get("role") not in {"master", "delivery"}:
        abort(403)
    status = request.form.get("status", "Out for Delivery")
    if status not in {"Out for Delivery", "Delivered"}:
        abort(400)
    connection = db()
    connection.execute(
        "UPDATE order_shop_status SET status = ? WHERE order_id = ?",
        (status, order_id),
    )
    connection.commit()
    connection.close()
    flash("Delivery status update ho gaya.")
    return redirect(url_for("delivery_panel"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        master_username = os.environ.get("MASTER_USERNAME", "admin")
        master_password = os.environ.get("MASTER_PASSWORD", "1234")

        if username == "delivery" and password == "1234":
            session.clear()
            session.update(
                user_id="delivery",
                role="delivery",
                shop_id=None,
                shop_name="Delivery Partner",
            )
            return redirect(url_for("delivery_panel"))

        if username == master_username and password == master_password:
            session.clear()
            session.update(
                user_id="master",
                role="master",
                shop_id=None,
                shop_name="Master Admin",
            )
            return redirect(url_for("dashboard"))

        connection = db()
        shop = connection.execute(
            """
            SELECT * FROM shops
            WHERE LOWER(username) = ? AND is_active = 1
            """,
            (username,),
        ).fetchone()
        connection.close()

        if shop and check_password_hash(shop["password_hash"], password):
            session.clear()
            session.update(
                user_id=shop["id"],
                role="shop",
                shop_id=shop["id"],
                shop_name=shop["name"],
            )
            return redirect(url_for("dashboard"))

        error = "Username ya password galat hai."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@admin_required
def dashboard():
    connection = db()

    if session.get("role") == "master":
        order_filter = ""
        params = ()
        product_filter = ""
        product_params = ()
    else:
        order_filter = """
            WHERE EXISTS (
                SELECT 1 FROM order_shop_status x
                WHERE x.order_id = o.id AND x.shop_id = ?
            )
        """
        params = (current_shop_id(),)
        product_filter = "WHERE shop_id = ?"
        product_params = (current_shop_id(),)

    summary = connection.execute(
        f"""
        SELECT
            COUNT(DISTINCT o.id) AS total_orders,
            COALESCE(SUM(
                CASE WHEN oss.status = 'Delivered' THEN oi.subtotal ELSE 0 END
            ), 0) AS delivered_sales,
            COALESCE(SUM(
                CASE WHEN oss.status IN ('Pending','Accepted','Out for Delivery')
                THEN 1 ELSE 0 END
            ), 0) AS active_shop_orders
        FROM orders o
        JOIN order_shop_status oss ON oss.order_id = o.id
        JOIN order_items oi
          ON oi.order_id = o.id AND oi.shop_id = oss.shop_id
        {order_filter}
        """,
        params,
    ).fetchone()

    products_count = connection.execute(
        f"SELECT COUNT(*) AS count FROM products {product_filter}",
        product_params,
    ).fetchone()["count"]

    low_stock = connection.execute(
        f"""
        SELECT p.*, s.name AS shop_name
        FROM products p
        JOIN shops s ON s.id = p.shop_id
        {"WHERE p.stock <= 5" if session.get("role") == "master" else "WHERE p.stock <= 5 AND p.shop_id = ?"}
        ORDER BY p.stock ASC
        LIMIT 10
        """,
        () if session.get("role") == "master" else (current_shop_id(),),
    ).fetchall()

    connection.close()
    return render_template(
        "dashboard.html",
        summary=summary,
        products_count=products_count,
        low_stock=low_stock,
    )


@app.route("/admin/orders")
@admin_required
def admin_orders():
    connection = db()

    if session.get("role") == "master":
        rows = connection.execute(
            """
            SELECT o.*, oss.status, s.name AS status_shop_name, oss.shop_id
            FROM orders o
            JOIN order_shop_status oss ON oss.order_id = o.id
            JOIN shops s ON s.id = oss.shop_id
            ORDER BY o.id DESC, s.name
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT o.*, oss.status, s.name AS status_shop_name, oss.shop_id
            FROM orders o
            JOIN order_shop_status oss ON oss.order_id = o.id
            JOIN shops s ON s.id = oss.shop_id
            WHERE oss.shop_id = ?
            ORDER BY o.id DESC
            """,
            (current_shop_id(),),
        ).fetchall()

    orders = []
    for row in rows:
        items = connection.execute(
            """
            SELECT * FROM order_items
            WHERE order_id = ? AND shop_id = ?
            ORDER BY product_name
            """,
            (row["id"], row["shop_id"]),
        ).fetchall()
        orders.append({"order": row, "items": items})

    connection.close()
    statuses = ["Pending", "Accepted", "Out for Delivery", "Delivered", "Cancelled"]
    return render_template("orders.html", orders=orders, statuses=statuses)


@app.route("/admin/orders/<int:order_id>/<int:shop_id>/status", methods=["POST"])
@admin_required
def update_order_status(order_id: int, shop_id: int):
    if session.get("role") != "master" and shop_id != current_shop_id():
        abort(403)

    status = request.form.get("status", "Pending")
    allowed = {"Pending", "Accepted", "Out for Delivery", "Delivered", "Cancelled"}
    if status not in allowed:
        abort(400)

    connection = db()
    connection.execute(
        """
        UPDATE order_shop_status
        SET status = ?
        WHERE order_id = ? AND shop_id = ?
        """,
        (status, order_id, shop_id),
    )
    connection.commit()
    connection.close()
    flash("Order status update ho gaya.")
    return redirect(url_for("admin_orders"))


@app.route("/admin/products")
@admin_required
def admin_products():
    connection = db()
    if session.get("role") == "master":
        products = connection.execute(
            """
            SELECT p.*, s.name AS shop_name
            FROM products p JOIN shops s ON s.id = p.shop_id
            ORDER BY p.id DESC
            """
        ).fetchall()
        shops = connection.execute(
            "SELECT * FROM shops WHERE is_active = 1 ORDER BY name"
        ).fetchall()
    else:
        products = connection.execute(
            """
            SELECT p.*, s.name AS shop_name
            FROM products p JOIN shops s ON s.id = p.shop_id
            WHERE p.shop_id = ?
            ORDER BY p.id DESC
            """,
            (current_shop_id(),),
        ).fetchall()
        shops = connection.execute(
            "SELECT * FROM shops WHERE id = ?", (current_shop_id(),)
        ).fetchall()

    connection.close()
    return render_template("products.html", products=products, shops=shops)


@app.route("/admin/products/add", methods=["POST"])
@admin_required
def add_product():
    name = request.form.get("name", "").strip()
    try:
        price = int(request.form.get("price", "0"))
        stock = int(request.form.get("stock", "0"))
        requested_shop_id = int(request.form.get("shop_id", "0"))
    except ValueError:
        flash("Price stock aur shop sahi bharo.")
        return redirect(url_for("admin_products"))

    shop_id = (
        requested_shop_id
        if session.get("role") == "master"
        else current_shop_id()
    )

    if not name or price <= 0 or stock < 0 or not shop_id:
        flash("Product details sahi bharo.")
        return redirect(url_for("admin_products"))

    try:
        image_filename = save_image(request.files.get("image"))
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("admin_products"))

    connection = db()
    connection.execute(
        """
        INSERT INTO products
        (shop_id, name, price, stock, image_url, is_available,
         is_popular, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            shop_id,
            name,
            price,
            stock,
            image_filename,
            1 if request.form.get("is_popular") else 0,
            now_text(),
        ),
    )
    connection.commit()
    connection.close()

    flash("Product add ho gaya.")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_product(product_id: int):
    connection = db()
    product = connection.execute(
        """
        SELECT p.*, s.name AS shop_name
        FROM products p JOIN shops s ON s.id = p.shop_id
        WHERE p.id = ?
        """,
        (product_id,),
    ).fetchone()

    if not product:
        connection.close()
        abort(404)
    if session.get("role") != "master" and product["shop_id"] != current_shop_id():
        connection.close()
        abort(403)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            price = int(request.form.get("price", "0"))
            stock = int(request.form.get("stock", "0"))
        except ValueError:
            connection.close()
            flash("Price aur stock sahi bharo.")
            return redirect(url_for("edit_product", product_id=product_id))

        image_filename = product["image_url"] or ""
        uploaded_file = request.files.get("image")
        if uploaded_file and uploaded_file.filename:
            try:
                image_filename = save_image(uploaded_file)
            except ValueError as error:
                connection.close()
                flash(str(error))
                return redirect(url_for("edit_product", product_id=product_id))

        connection.execute(
            """
            UPDATE products
            SET name = ?, price = ?, stock = ?, image_url = ?,
                is_available = ?, is_popular = ?
            WHERE id = ?
            """,
            (
                name,
                price,
                max(stock, 0),
                image_filename,
                1 if request.form.get("is_available") else 0,
                1 if request.form.get("is_popular") else 0,
                product_id,
            ),
        )
        connection.commit()
        connection.close()
        flash("Product update ho gaya.")
        return redirect(url_for("admin_products"))

    connection.close()
    return render_template("edit_product.html", product=product)


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id: int):
    connection = db()
    product = connection.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if not product:
        connection.close()
        abort(404)
    if session.get("role") != "master" and product["shop_id"] != current_shop_id():
        connection.close()
        abort(403)

    connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
    connection.commit()
    connection.close()
    flash("Product delete ho gaya.")
    return redirect(url_for("admin_products"))


@app.route("/admin/shops")
@admin_required
@master_required
def shops():
    connection = db()
    shop_rows = connection.execute("SELECT * FROM shops ORDER BY id DESC").fetchall()
    connection.close()
    return render_template("shops.html", shops=shop_rows)


@app.route("/admin/shops/add", methods=["POST"])
@admin_required
@master_required
def add_shop():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    phone = request.form.get("phone", "").strip()

    if not name or not username or len(password) < 4:
        flash("Shop name username aur minimum 4 digit password zaroori hai.")
        return redirect(url_for("shops"))

    connection = db()
    try:
        connection.execute(
            """
            INSERT INTO shops (name, username, password_hash, phone)
            VALUES (?, ?, ?, ?)
            """,
            (name, username, generate_password_hash(password), phone),
        )
        connection.commit()
        flash("Nayi shop add ho gayi.")
    except sqlite3.IntegrityError:
        flash("Shop name ya username pehle se use ho raha hai.")
    finally:
        connection.close()

    return redirect(url_for("shops"))


@app.route("/admin/shops/<int:shop_id>/toggle", methods=["POST"])
@admin_required
@master_required
def toggle_shop(shop_id: int):
    connection = db()
    connection.execute(
        """
        UPDATE shops
        SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
        WHERE id = ?
        """,
        (shop_id,),
    )
    connection.commit()
    connection.close()
    flash("Shop status update ho gaya.")
    return redirect(url_for("shops"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
@master_required
def settings():
    if request.method == "POST":
        delivery_charge = request.form.get("delivery_charge", "20").strip()
        whatsapp_number = request.form.get("whatsapp_number", "").strip()
        delivery_percent = request.form.get("delivery_percent", "10").strip()
        minimum_delivery_charge = request.form.get("minimum_delivery_charge", "5").strip()
        free_delivery_above = request.form.get("free_delivery_above", "500").strip()
        upi_id = request.form.get("upi_id", "").strip()
        coupon_code = request.form.get("coupon_code", "SAVE10").strip().upper()
        coupon_percent = request.form.get("coupon_percent", "10").strip()

        try:
            charge = max(0, int(delivery_charge))
            percent = max(0, min(100, int(delivery_percent)))
            minimum_charge = max(0, int(minimum_delivery_charge))
            free_above = max(0, int(free_delivery_above))
            coupon_pct = max(0, min(100, int(coupon_percent)))
        except ValueError:
            flash("Delivery charge number me bharo.")
            return redirect(url_for("settings"))

        if whatsapp_number and not whatsapp_number.isdigit():
            flash("WhatsApp number sirf digits me bharo, country code ke saath.")
            return redirect(url_for("settings"))

        set_setting("delivery_charge", str(charge))
        set_setting("whatsapp_number", whatsapp_number)
        set_setting("delivery_percent", str(percent))
        set_setting("minimum_delivery_charge", str(minimum_charge))
        set_setting("free_delivery_above", str(free_above))
        set_setting("upi_id", upi_id)
        set_setting("coupon_code", coupon_code or "SAVE10")
        set_setting("coupon_percent", str(coupon_pct))
        flash("Settings save ho gayi.")
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        delivery_charge=get_setting("delivery_charge", "20"),
        whatsapp_number=get_setting("whatsapp_number", ""),
        delivery_percent=get_setting("delivery_percent", "10"),
        minimum_delivery_charge=get_setting("minimum_delivery_charge", "5"),
        free_delivery_above=get_setting("free_delivery_above", "500"),
        upi_id=get_setting("upi_id", ""),
        coupon_code=get_setting("coupon_code", "SAVE10"),
        coupon_percent=get_setting("coupon_percent", "10"),
    )


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", message="Aapko is page ki permission nahi hai."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="Page nahi mila."), 404


if __name__ == "__main__":
    create_database()
    print("GAON DELIVERY PRO STARTED")
    print("Master login: admin / 1234")
    print("Starter shop logins: kirana / 1234, dairy / 1234, general / 1234")
    app.run(host="0.0.0.0", port=5000, debug=True)
