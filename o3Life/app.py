from flask import Flask, request, jsonify, send_from_directory, session
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
from datetime import datetime

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("O3LIFE_SECRET_KEY", "CHANGE_THIS_SECRET_KEY")

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": os.environ.get("O3LIFE_DB_PASSWORD", "12345678"),
    "database": "o3life"
}

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 8 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE



BEACHES = [
    {"name": "Marina Beach", "latitude": 13.0500, "longitude": 80.2824},
    {"name": "Besant Nagar / Elliot's Beach", "latitude": 13.0007, "longitude": 80.2668},
    {"name": "Thiruvanmiyur Beach", "latitude": 12.9827, "longitude": 80.2707},
    {"name": "Palavakkam Beach", "latitude": 12.9582, "longitude": 80.2574},
    {"name": "Neelankarai Beach", "latitude": 12.9481, "longitude": 80.2540},
    {"name": "Kottivakkam Beach", "latitude": 12.9637, "longitude": 80.2560},
    {"name": "Injambakkam Beach", "latitude": 12.9154, "longitude": 80.2505},
    {"name": "Kovalam Beach", "latitude": 12.7910, "longitude": 80.2507},
]


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, email, role FROM users WHERE id = %s",
        (user_id,)
    )
    user = cursor.fetchone()
    cursor.close()
    db.close()
    return user


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_report_image(file):
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename):
        raise ValueError("Only JPG, JPEG, PNG and WEBP images are allowed.")

    # secure_filename removes unsafe path characters.
    original = secure_filename(file.filename)
    extension = original.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    return f"/uploads/{filename}"


def normalise_report(row):
    report_id = row["id"]
    return {
        "id": f"O3L-2026-{report_id:05d}",
        "numeric_id": report_id,
        "category": row.get("category") or "Other",
        "beach_name": row.get("beach_name") or row.get("location") or "",
        "location": row.get("location") or "",
        "date": row["report_date"].strftime("%Y-%m-%d") if row.get("report_date") else "",
        "description": row.get("issue") or "",
        "severity": row.get("severity") or "Medium",
        "status": row.get("status") or "Submitted",
        "verification_status": row.get("verification_status") or "Pending",
        "reporter": row.get("name") or "Anonymous",
        "image_url": row.get("image_url") or "",
        "latitude": float(row["latitude"]) if row.get("latitude") is not None else None,
        "longitude": float(row["longitude"]) if row.get("longitude") is not None else None,
        "true_votes": int(row.get("true_votes") or 0),
        "false_votes": int(row.get("false_votes") or 0),
        "total_votes": int(row.get("total_votes") or 0),
        "community_verdict": (
            "Mostly true" if int(row.get("true_votes") or 0) > int(row.get("false_votes") or 0)
            else "Mostly false" if int(row.get("false_votes") or 0) > int(row.get("true_votes") or 0)
            else "No clear public verdict"
        )
    }


def report_select_sql(extra_where=""):
    return f"""
        SELECT r.id, r.category, r.beach_name, r.location, r.report_date, r.issue,
               r.severity, r.status, r.name, r.image_url, r.latitude, r.longitude,
               r.verification_status,
               COALESCE(SUM(CASE WHEN rv.vote = 'true' THEN 1 ELSE 0 END), 0) AS true_votes,
               COALESCE(SUM(CASE WHEN rv.vote = 'false' THEN 1 ELSE 0 END), 0) AS false_votes,
               COUNT(rv.id) AS total_votes
        FROM reports r
        LEFT JOIN report_votes rv ON rv.report_id = r.id
        {extra_where}
        GROUP BY r.id, r.category, r.beach_name, r.location, r.report_date, r.issue,
                 r.severity, r.status, r.name, r.image_url, r.latitude, r.longitude,
                 r.verification_status
        ORDER BY r.id DESC
    """


@app.route("/")
def home():
    return send_from_directory("frontend", "index.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/api/beaches", methods=["GET"])
def beaches():
    return jsonify(BEACHES)


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cursor.fetchone():
        cursor.close()
        db.close()
        return jsonify({"error": "An account with this email already exists."}), 409

    password_hash = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'user')",
        (name, email, password_hash)
    )
    db.commit()
    user_id = cursor.lastrowid

    session["user_id"] = user_id
    cursor.execute(
        "SELECT id, name, email, role FROM users WHERE id = %s",
        (user_id,)
    )
    user = cursor.fetchone()
    cursor.close()
    db.close()

    return jsonify({"success": True, "user": user}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = %s",
        (email,)
    )
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_id"] = user["id"]
    user.pop("password_hash", None)
    return jsonify({"success": True, "user": user})


@app.route("/api/auth/me", methods=["GET"])
def me():
    return jsonify({"user": current_user()})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/reports", methods=["POST"])
def create_report():
    user = current_user()
    if not user:
        return jsonify({"error": "Please login before submitting a report."}), 401

    category = request.form.get("category", "").strip()
    beach_name = request.form.get("beach_name", "").strip()
    location = request.form.get("location", "").strip()
    date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    description = request.form.get("description", "").strip()
    severity = request.form.get("severity", "").strip()

    try:
        latitude = float(request.form["latitude"]) if request.form.get("latitude") else None
        longitude = float(request.form["longitude"]) if request.form.get("longitude") else None
    except ValueError:
        return jsonify({"error": "Latitude and longitude must be valid numbers."}), 400

    if not category or not beach_name or not location or not description or not severity:
        return jsonify({"error": "Please complete all required report fields."}), 400

    image_url = ""
    try:
        image_url = save_report_image(request.files.get("photo")) or ""
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """
        INSERT INTO reports
        (user_id, name, location, issue, report_date, category, severity, status,
         beach_name, latitude, longitude, image_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Submitted',
                %s, %s, %s, %s)
        """,
        (
            user["id"], user["name"], location, description, date,
            category, severity, beach_name, latitude, longitude, image_url
        )
    )
    db.commit()
    report_id = cursor.lastrowid
    cursor.close()
    db.close()

    return jsonify({
        "success": True,
        "id": f"O3L-2026-{report_id:05d}",
        "category": category,
        "beach_name": beach_name,
        "location": location,
        "date": date,
        "description": description,
        "severity": severity,
        "status": "Submitted",
        "reporter": user["name"],
        "image_url": image_url,
        "latitude": latitude,
        "longitude": longitude
    }), 201


@app.route("/api/reports", methods=["GET"])
def get_reports():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(report_select_sql())
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify([normalise_report(row) for row in rows])


@app.route("/api/reports/<report_id>", methods=["GET"])
def get_report(report_id):
    raw_id = report_id.replace("O3L-2026-", "", 1) if report_id.startswith("O3L-2026-") else report_id
    try:
        numeric_id = int(raw_id)
    except ValueError:
        return jsonify({"error": "Invalid report ID."}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(report_select_sql("WHERE r.id = %s"), (numeric_id,))
    row = cursor.fetchone()
    cursor.close()
    db.close()

    if not row:
        return jsonify({"error": "Report not found."}), 404

    return jsonify(normalise_report(row))


@app.route("/api/reports/<report_id>/vote", methods=["POST"])
def vote_report(report_id):
    user = current_user()
    if not user:
        return jsonify({"error": "Please login to vote."}), 401

    raw_id = report_id.replace("O3L-2026-", "", 1) if report_id.startswith("O3L-2026-") else report_id
    try:
        numeric_id = int(raw_id)
    except ValueError:
        return jsonify({"error": "Invalid report ID."}), 400

    data = request.get_json() or {}
    vote = str(data.get("vote", "")).lower()
    if vote not in ("true", "false"):
        return jsonify({"error": "Vote must be true or false."}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, user_id FROM reports WHERE id = %s", (numeric_id,))
    report = cursor.fetchone()
    if not report:
        cursor.close(); db.close()
        return jsonify({"error": "Report not found."}), 404
    if int(report["user_id"]) == int(user["id"]):
        cursor.close(); db.close()
        return jsonify({"error": "You cannot vote on your own report."}), 400

    cursor.execute("""
        INSERT INTO report_votes (report_id, user_id, vote) VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE vote = VALUES(vote), updated_at = CURRENT_TIMESTAMP
    """, (numeric_id, user["id"], vote))
    db.commit()
    cursor.close()
    db.close()
    return jsonify({"success": True, "vote": vote})


@app.route("/api/employee/reports/<report_id>/verify", methods=["PUT"])
def employee_verify_report(report_id):
    user = current_user()
    if not user or user["role"] not in ("employee", "admin"):
        return jsonify({"error": "Employee access required."}), 403

    raw_id = report_id.replace("O3L-2026-", "", 1) if report_id.startswith("O3L-2026-") else report_id
    try:
        numeric_id = int(raw_id)
    except ValueError:
        return jsonify({"error": "Invalid report ID."}), 400

    data = request.get_json() or {}
    decision = str(data.get("decision", "")).lower()
    if decision not in ("true", "false"):
        return jsonify({"error": "Decision must be true or false."}), 400

    verification_status = "Verified" if decision == "true" else "Rejected"
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE reports
        SET verification_status = %s, verified_by = %s, verified_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (verification_status, user["id"], numeric_id))
    db.commit()
    changed = cursor.rowcount
    cursor.close()
    db.close()
    if not changed:
        return jsonify({"error": "Report not found."}), 404
    return jsonify({"success": True, "verification_status": verification_status})


@app.route("/api/reports/<report_id>", methods=["PUT"])
def update_report(report_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"error": "Admin login required."}), 403

    raw_id = report_id.replace("O3L-2026-", "", 1) if report_id.startswith("O3L-2026-") else report_id
    try:
        numeric_id = int(raw_id)
    except ValueError:
        return jsonify({"error": "Invalid report ID."}), 400

    data = request.get_json() or {}
    status = data.get("status")
    if status not in ["Submitted", "Verified", "Assigned", "Resolved"]:
        return jsonify({"error": "Invalid status."}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE reports SET status = %s WHERE id = %s", (status, numeric_id))
    db.commit()
    cursor.close()
    db.close()

    return jsonify({
        "success": True,
        "id": f"O3L-2026-{numeric_id:05d}",
        "status": status
    })


@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM reports")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS resolved FROM reports WHERE status = 'Resolved'")
    resolved = cursor.fetchone()["resolved"]

    cursor.execute("SELECT COUNT(DISTINCT beach_name) AS locations FROM reports")
    locations = cursor.fetchone()["locations"]

    cursor.execute("SELECT COUNT(*) AS contributors FROM users")
    contributors = cursor.fetchone()["contributors"]

    cursor.close()
    db.close()

    return jsonify({
        "total": total,
        "resolved": resolved,
        "active": total - resolved,
        "locations": locations,
        "contributors": contributors
    })


@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"error": "Admin login required."}), 403

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT u.id, u.name, u.email, u.role, u.created_at,
               COUNT(r.id) AS reports_filed
        FROM users u
        LEFT JOIN reports r ON r.user_id = u.id
        GROUP BY u.id, u.name, u.email, u.role, u.created_at
        ORDER BY u.id DESC
        """
    )
    users = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(users)


@app.route("/api/admin/users/<int:user_id>/role", methods=["PUT"])
def update_user_role(user_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"error": "Admin access required."}), 403

    data = request.get_json() or {}
    role = str(data.get("role", "")).lower()
    if role not in ("user", "employee", "admin"):
        return jsonify({"error": "Role must be user, employee or admin."}), 400

    if int(user_id) == int(user["id"]) and role != "admin":
        return jsonify({"error": "You cannot remove your own admin role here."}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
    db.commit()
    changed = cursor.rowcount
    cursor.close()
    db.close()
    if not changed:
        return jsonify({"error": "User not found."}), 404
    return jsonify({"success": True, "role": role})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Image is too large. Maximum size is 8 MB."}), 413


if __name__ == "__main__":
    print("O3Life backend starting...")
    print("Uploads folder:", UPLOAD_FOLDER)
    app.run(host="0.0.0.0", port=5000, debug=True)
