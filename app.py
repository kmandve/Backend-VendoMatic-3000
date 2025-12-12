from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask_cors import CORS
from functools import wraps
from flask_socketio import SocketIO, emit
import os

#/etc/secrets/firebase_secret.json
cred = credentials.Certificate("/etc/secrets/firebase_secret.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": "*", 
        "methods": ["GET", "POST", "PUT", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# List of admin emails - add your admin email addresses here
ADMIN_EMAILS = [
    "kautikmandve@gmail.com",
    "adam.lueken@d128.org"
]

def verify_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"error": "No token provided"}), 401
        
        try:
            # Remove 'Bearer ' prefix if present
            if token.startswith('Bearer '):
                token = token.split('Bearer ')[1]
            
            decoded_token = auth.verify_id_token(token)
            request.user_email = decoded_token.get('email')
            request.user_uid = decoded_token.get('uid')
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({"error": "Invalid token", "details": str(e)}), 401
    
    return decorated_function

def is_admin(email):
    """Check if email is in the admin list"""
    return email in ADMIN_EMAILS

def get_user_points(user_id):
    doc = db.collection('users').document(user_id).get()
    if not doc.exists:
        return None
    return doc.to_dict().get('points', 0)

def set_user_points(user_id, points):
    db.collection('users').document(user_id).update({
        'points': points
    })

def get_or_create_user(user_id, email):
    """Get user or create if doesn't exist"""
    doc = db.collection('users').document(user_id).get()
    
    if not doc.exists:
        # Create new user with 0 points
        db.collection('users').document(user_id).set({
            'points': 0,
            'email': email,
            'is_admin': is_admin(email)
        })
        return 0, is_admin(email)
    
    data = doc.to_dict()
    return data.get('points', 0), data.get('is_admin', False)

# ======================
# SOCKET.IO EVENTS
# ======================
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f'Client connected: {request.sid}')
    emit('connection_response', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f'Client disconnected: {request.sid}')

@socketio.on('ping')
def handle_ping():
    """Handle ping from client"""
    emit('pong')

# ======================
# HTTP ROUTES
# ======================
@app.route("/auth/google", methods=["POST"])
def google_auth():
    """Authenticate with Google and get/create user"""
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"error": "No token provided"}), 401
    
    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token.split('Bearer ')[1]
        
        # Verify the token
        decoded_token = auth.verify_id_token(token)
        user_email = decoded_token.get('email')
        user_uid = decoded_token.get('uid')
        
        if not user_email:
            return jsonify({"error": "Email not found in token"}), 400
        
        # Get or create user
        points, admin_status = get_or_create_user(user_uid, user_email)
        
        return jsonify({
            "ok": True,
            "user_id": user_uid,
            "email": user_email,
            "points": points,
            "is_admin": admin_status
        })
    
    except Exception as e:
        return jsonify({"error": "Authentication failed", "details": str(e)}), 401

@app.route("/users", methods=["GET"])
@verify_token
def list_users():
    """List all users (admin only)"""
    if not is_admin(request.user_email):
        return jsonify({"error": "Admin access required"}), 403
    
    users_ref = db.collection("users")
    docs = users_ref.stream()
    result = []
    for doc in docs:
        data = doc.to_dict()
        result.append({
            "user_id": doc.id,
            "email": data.get("email", ""),
            "points": data.get("points", 0),
            "is_admin": data.get("is_admin", False)
        })
    return jsonify(result)

@app.route("/user/<user_id>", methods=["GET"])
@verify_token
def get_user(user_id):
    """Get user info"""
    # Users can only get their own info unless they're admin
    if user_id != request.user_uid and not is_admin(request.user_email):
        return jsonify({"error": "Unauthorized"}), 403
    
    doc = db.collection('users').document(user_id).get()
    if not doc.exists:
        return jsonify({"error": "User not found"}), 404
    
    data = doc.to_dict()
    return jsonify({
        "user_id": user_id,
        "email": data.get("email", ""),
        "points": data.get("points", 0)
    })

@app.route("/buy", methods=["POST"])
@verify_token
def buy():
    """Make a purchase"""
    data = request.get_json()
    user_id = data.get("user_id")
    item_name = data.get("item_name")
    cost = data.get("cost")
    
    if not user_id or not item_name or cost is None:
        return jsonify({"error": "Missing fields"}), 400
    
    # Users can only buy for themselves unless they're admin
    if user_id != request.user_uid and not is_admin(request.user_email):
        return jsonify({"error": "Unauthorized"}), 403
    
    points = get_user_points(user_id)
    if points is None:
        return jsonify({"error": "User not found"}), 404
    
    if points < cost:
        return jsonify({"error": "Not enough points"}), 400
    
    new_points = points - cost
    set_user_points(user_id, new_points)
    
    # Only queue if NOT an admin adjustment
    if item_name != "ADMIN_ADJUSTMENT":
        purchase_item = {
            "user": user_id,
            "item": item_name,
            "cost": cost
        }
        # Emit to all connected clients
        print(f"Emitting task_update: {purchase_item}")
        socketio.emit("task_update", purchase_item, broadcast=True)
    
    return jsonify({"ok": True, "new_points": new_points})

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
