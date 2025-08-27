
import os
import sqlite3
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from werkzeug.utils import secure_filename
from datetime import datetime

# -------------------------
# Basic Config
# -------------------------
APP_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(APP_DIR, "shop.db")
UPLOAD_FOLDER = os.path.join(APP_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "admin123")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB


# -------------------------
# Database helpers
# -------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price_cents INTEGER NOT NULL DEFAULT 0,
        description TEXT NOT NULL DEFAULT '',
        image TEXT NOT NULL DEFAULT ''
    );
    """)
    # seed if empty
    cur = db.execute("SELECT COUNT(*) as c FROM products")
    if cur.fetchone()["c"] == 0:
        demo = [
            ("Aurvic Tee", 1999, "Premium cotton T-shirt with minimalist logo.", "tee.jpg"),
            ("Aurvic Hoodie", 4999, "Cozy hoodie for everyday adventures.", "hoodie.jpg"),
            ("Aurvic Cap", 1499, "Adjustable cap with embroidered monogram.", "cap.jpg"),
        ]
        for name, price, desc, img in demo:
            db.execute(
                "INSERT INTO products(name, price_cents, description, image) VALUES (?,?,?,?)",
                (name, price, desc, img)
            )
        db.commit()

# -------------------------
# Utilities
# -------------------------
def price_fmt(cents):
    return f"{cents/100:.2f}"

def cart_items():
    cart = session.get("cart", {})
    db = get_db()
    items = []
    total = 0
    for pid, qty in cart.items():
        row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if row:
            subtotal = row["price_cents"] * qty
            total += subtotal
            items.append({"product": row, "qty": qty, "subtotal": subtotal})
    return items, total

# -------------------------
# Routes: Storefront
# -------------------------
@app.route("/")
def index():
    init_db()
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        products = db.execute("SELECT * FROM products WHERE name LIKE ? OR description LIKE ? ORDER BY id DESC",
                              (f"%{q}%", f"%{q}%")).fetchall()
    else:
        products = db.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return render_template("index.html", products=products, q=q, price_fmt=price_fmt)

@app.route("/product/<int:pid>")
def product_detail(pid):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not p:
        abort(404)
    return render_template("product_detail.html", p=p, price_fmt=price_fmt)

@app.route("/cart")
def cart_view():
    items, total = cart_items()
    return render_template("cart.html", items=items, total=total, price_fmt=price_fmt)

@app.route("/cart/add/<int:pid>", methods=["POST"])
def cart_add(pid):
    db = get_db()
    p = db.execute("SELECT id FROM products WHERE id = ?", (pid,)).fetchone()
    if not p:
        abort(404)
    qty = max(1, int(request.form.get("qty", 1)))
    cart = session.get("cart", {})
    cart[str(pid)] = cart.get(str(pid), 0) + qty
    session["cart"] = cart
    flash("تمت إضافة المنتج إلى السلة.")
    return redirect(url_for("cart_view"))

@app.route("/cart/remove/<int:pid>", methods=["POST"])
def cart_remove(pid):
    cart = session.get("cart", {})
    cart.pop(str(pid), None)
    session["cart"] = cart
    flash("تمت إزالة المنتج من السلة.")
    return redirect(url_for("cart_view"))

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total = cart_items()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip()
        address = request.form.get("address","").strip()
        if not (name and email and address):
            flash("يرجى تعبئة جميع الحقول.")
            return redirect(url_for("checkout"))
        # Simulate order creation
        order_id = int(datetime.utcnow().timestamp())
        session["cart"] = {}
        return render_template("order_success.html", order_id=order_id, total=total, price_fmt=price_fmt)
    return render_template("checkout.html", items=items, total=total, price_fmt=price_fmt)

# -------------------------
# Routes: Admin (very simple)
# -------------------------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pwd = request.form.get("password","")
        if pwd == app.config["ADMIN_PASSWORD"]:
            session["is_admin"] = True
            return redirect(url_for("admin_products"))
        flash("كلمة المرور غير صحيحة.")
    return render_template("admin_login.html")

def admin_required():
    if not session.get("is_admin"):
        return False
    return True

@app.route("/admin/products")
def admin_products():
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = get_db()
    products = db.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return render_template("admin_products.html", products=products, price_fmt=price_fmt)

@app.route("/admin/products/add", methods=["POST"])
def admin_products_add():
    if not admin_required():
        return redirect(url_for("admin_login"))
    name = request.form.get("name","").strip()
    price = int(float(request.form.get("price","0")) * 100)
    description = request.form.get("description","").strip()
    image_file = request.files.get("image")
    image_name = ""
    if image_file and image_file.filename:
        image_name = secure_filename(image_file.filename)
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_name)
        image_file.save(image_path)
    db = get_db()
    if not name:
        flash("الاسم مطلوب.")
        return redirect(url_for("admin_products"))
    db.execute("INSERT INTO products(name, price_cents, description, image) VALUES (?,?,?,?)",
               (name, price, description, image_name))
    db.commit()
    flash("تم إضافة المنتج.")
    return redirect(url_for("admin_products"))

@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
def admin_products_delete(pid):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    flash("تم حذف المنتج.")
    return redirect(url_for("admin_products"))

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
