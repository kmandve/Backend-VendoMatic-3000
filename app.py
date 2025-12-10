from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from flask_cors import CORS

cred = credentials.Certificate("firebase_secret.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "OPTIONS"]}})

purchase_queue = []

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "pass"

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return jsonify({"ok": True, "message": "Login successful"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401


def get_user_points(user_id):
    doc = db.collection('users').document(user_id).get()
    if not doc.exists:
        return None
    return doc.to_dict().get('points', 0)


def set_user_points(user_id, points):
    db.collection('users').document(user_id).update({
        'points': points
    })


@app.route("/users", methods=["GET"])
def list_users():
    users_ref = db.collection("users")
    docs = users_ref.stream()

    result = []
    for doc in docs:
        data = doc.to_dict()
        result.append({
            "user_id": doc.id,
            "points": data.get("points", 0)
        })

    return jsonify(result)


@app.route("/user/<user_id>/points", methods=["PUT"])
def update_points(user_id):
    data = request.get_json()
    new_points = data.get("points")
    set_user_points(user_id, new_points)
    return jsonify({"ok": True, "points": new_points})


@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    points = get_user_points(user_id)
    if points is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify({"user_id": user_id, "points": points})


@app.route("/buy", methods=["POST"])
def buy():
    data = request.get_json()
    user_id = data.get("user_id")
    item_name = data.get("item_name")
    cost = data.get("cost")

    if not user_id or not item_name or cost is None:
        return jsonify({"error": "missing fields"}), 400

    points = get_user_points(user_id)
    if points is None:
        return jsonify({"error": "user not found"}), 404

    if points < cost:
        return jsonify({"error": "not enough points"}), 400

    new_points = points - cost
    set_user_points(user_id, new_points)

    # Only queue if NOT an admin adjustment
    if item_name != "ADMIN_ADJUSTMENT":
        purchase_queue.append({
            "user": user_id,
            "item": item_name,
            "cost": cost
        })

    return jsonify({"ok": True, "new_points": new_points})


@app.route("/queue/next", methods=["GET"])
def queue_next():
    if not purchase_queue:
        return jsonify({"command": "none"})
    return jsonify(purchase_queue[0])


@app.route("/queue/ack", methods=["POST"])
def queue_ack():
    if purchase_queue:
        purchase_item = purchase_queue.pop(0)
        return jsonify({"ok": True, "processed": purchase_item})
    return jsonify({"ok": False, "error": "queue empty"}), 400


@app.route("/user/create", methods=["POST"])
def create_user():
    data = request.get_json()
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    # Check if user exists
    doc = db.collection('users').document(user_id).get()
    if doc.exists:
        return jsonify({"error": "user already exists"}), 400
    
    # Create user with 0 points
    db.collection('users').document(user_id).set({
        'points': 0
    })
    
    return jsonify({"ok": True, "user_id": user_id, "points": 0})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
