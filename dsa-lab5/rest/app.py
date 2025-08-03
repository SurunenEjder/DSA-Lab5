from flask import Flask, request, jsonify, g
import grpc
import items_pb2
import items_pb2_grpc
import os
import time
import logging
from pybreaker import CircuitBreaker, CircuitBreakerError
from functools import wraps
import json as pyjson
import threading
from prometheus_client import Counter, Histogram, generate_latest
import jwt  # Import jwt for decoding tokens

# Configure logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency",
    ["method", "endpoint"])

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"])

# Add this near the top with other configurations
SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')  # Add this line

app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.config['JSON_SORT_KEYS'] = False

def start_timer():
    # returns a stop-function bound to the request
    request._timer = REQUEST_LATENCY.labels(
        request.method, request.path).time()
    
@app.after_request
def after_request(response):
    # Calculate request duration
    request_latency = time.time() - request.start_time
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.path
    ).observe(request_latency)
    
    # Count the request
    REQUEST_COUNTER.labels(
        method=request.method,
        endpoint=request.path,
        status=response.status_code
    ).inc()
    
    return response

@app.route("/metrics")
def metrics():
    # Standard text format understood by Prometheus
    return generate_latest(), 200, {"Content-Type": "text/plain; version=0.0.4"}

# gRPC Configuration with TLS support
GRPC_HOST = os.getenv("GRPC_HOST", "localhost")
GRPC_PORT = os.getenv("GRPC_PORT", "50051")

def create_grpc_channel():
    """Create gRPC channel with mutual TLS support"""
    import os
    
    try:
        # Use current working directory paths (certificates mounted here)
        cert_files = ["ca.crt", "rest-service.key", "rest-service.crt"]
        missing_files = [f for f in cert_files if not os.path.exists(f)]
        
        if missing_files:
            raise FileNotFoundError(f"Missing certificate files: {missing_files}")
            
        # Create secure channel with mutual TLS
        credentials = grpc.ssl_channel_credentials(
            root_certificates=open("ca.crt", "rb").read(),
            private_key=open("rest-service.key", "rb").read(),
            certificate_chain=open("rest-service.crt", "rb").read()
        )
        
        channel = grpc.secure_channel(
            f"{GRPC_HOST}:{GRPC_PORT}",
            credentials,
            options=[
                ('grpc.connect_timeout_ms', 5000),
                ('grpc.enable_retries', 1),
                ('grpc.keepalive_timeout_ms', 10000),
                ('grpc.ssl_target_name_override', 'grpc-service'),
            ]
        )
        logger.info("✅ Created secure gRPC channel with mutual TLS")
        return channel
        
    except (FileNotFoundError, Exception) as e:
        logger.warning(f"⚠️  TLS setup failed ({e}), using insecure channel")
        channel = grpc.insecure_channel(f"{GRPC_HOST}:{GRPC_PORT}")
        return channel  # ✅ FIX: Return the actual channel

# Initialize the gRPC channel
channel = create_grpc_channel()

# Circuit Breaker Configuration
class CircuitBreakerMonitor:
    def state_change(self, cb, old_state, new_state):
        logger.info(f"CircuitBreaker state changed from {old_state} to {new_state}")
        print(f"CircuitBreaker state changed from {old_state} to {new_state}")

    def before_call(self, cb, func, *args, **kwargs):
        pass

    def failure(self, cb, exc):
        pass

    def success(self, cb):
        pass

breaker = CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    exclude=[
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.INVALID_ARGUMENT
    ],
    listeners=[CircuitBreakerMonitor()],
    name="gRPC_Circuit_Breaker"
)

stub = items_pb2_grpc.ItemServiceStub(channel)


# This decorator retries gRPC calls with exponential backoff
def retry_grpc(max_retries=3, initial_delay=0.1):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return f(*args, **kwargs)
                except grpc.RpcError as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                except Exception as e:
                    logger.error(f"Unexpected error: {str(e)}")
                    raise
        return wrapper
    return decorator

# Connection verification
# This function checks if the gRPC connection is active
def verify_grpc_connection():
    try:
        list(stub.ListAllItems(items_pb2.Empty(), timeout=1))
        return True
    except grpc.RpcError as e:
        logger.error(f"gRPC connection failed: {e.code().name}")
        return False

# Health Check Endpoint
@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Test basic Flask app health first
        grpc_status = "checking..."
        
        try:
            # Try to connect to gRPC with timeout
            list(stub.ListAllItems(items_pb2.Empty(), timeout=2))
            grpc_status = "connected"
        except grpc.RpcError as e:
            # gRPC connection issues are expected during testing
            grpc_status = f"disconnected ({e.code().name})"
        except Exception as e:
            grpc_status = f"error ({str(e)[:50]})"
        
        # Return healthy even if gRPC is down (REST service itself is working)
        return jsonify({
            "status": "healthy",  # Always healthy if Flask is responding
            "grpc": grpc_status,
            "authentication": "enabled",
            "breaker": breaker.current_state
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503

# Reset Circuit Breaker
@app.route('/reset-breaker', methods=['POST'])
def reset_breaker():
    try:
        logger.info("Resetting circuit breaker...")
        breaker.close()
        logger.info("Circuit breaker closed")
        logger.info("Circuit breaker fully reset")
        return jsonify({
            "status": "success",
            "breaker_state": "closed",
            "fail_count": 0
        }), 200
    except Exception as e:
        logger.error(f"Reset failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Decorator for token-required endpoints
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            # Get token from header
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                return jsonify({'error': 'Missing authorization header'}), 401
            
            if not auth_header.startswith('Bearer '):
                return jsonify({'error': 'Invalid authorization header format'}), 401
                
            token = auth_header.split(' ')[1]
            
            # Decode and validate token
            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user = payload['username']
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            logging.error(f"Authentication error: {e}")
            return jsonify({'error': 'Authentication failed'}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated

# CRUD Endpoints with Retry and Circuit Breaker
@app.route('/items', methods=['POST'])
@token_required  # Add this decorator
def create_item(current_user):  # Add current_user parameter
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400

        data = request.get_json()
        if not data or 'name' not in data:
            return jsonify({'error': 'Name is required'}), 400

        response = breaker.call(
            stub.AddItem,
            items_pb2.ItemRequest(
                id=data.get('id', 0),
                name=data['name']
            ),
            timeout=3
        )
        return jsonify({'id': response.id, 'name': response.name}), 201

    except pyjson.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON'}), 400
    except grpc.RpcError as e:
        logger.error(f"GRPC error: {e.code().name}")
        return jsonify({'error': f'Service error: {e.details()}'}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/items', methods=['GET'])
@token_required  # Add this decorator
@retry_grpc()
def get_all_items(current_user):  # Add current_user parameter
    try:
        items = list(stub.ListAllItems(items_pb2.Empty(), timeout=1))
        return jsonify([{"id": item.id, "name": item.name} for item in items]), 200
    except grpc.RpcError as e:
        logger.error(f"gRPC error: {e.code().name}")
        return jsonify({'error': 'Service error'}), 500

@app.route('/items/<int:item_id>', methods=['GET'])
@retry_grpc()
def get_item(item_id):
    try:
        item = stub.GetItemById(items_pb2.ItemRequest(id=item_id), timeout=1)
        if item.id == 0:
            return jsonify({'error': 'Item not found'}), 404
        return jsonify({"id": item.id, "name": item.name}), 200
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            return jsonify({'error': 'Item not found'}), 404
        logger.error(f"gRPC error: {e.code().name}")
        return jsonify({'error': 'Service error'}), 500

@app.route('/auth', methods=['POST'])
def authenticate():
    """Generate JWT token for authentication"""
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400

        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        # Simple authentication (in production, verify against database)
        if username == 'admin' and password == 'secret':
            import datetime
            
            # Generate JWT token
            payload = {
                'username': username,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            }
            token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
            
            return jsonify({'token': token}), 200
        else:
            return jsonify({'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/protected', methods=['GET'])
def protected_endpoint():
    """Test endpoint that requires JWT authentication"""
    return jsonify({
        "message": "You are authenticated!",
        "user": g.user,
        "roles": g.claims.get("realm_access", {}).get("roles", []),
        "token_claims": {
            "sub": g.claims.get("sub"),
            "preferred_username": g.claims.get("preferred_username"),
            "email": g.claims.get("email")
        }
    }), 200

@app.before_request
def before_request():
    request.start_time = time.time()

# Background thread to monitor gRPC connection
# This function runs in a separate thread to monitor the gRPC connection
def monitor_grpc_connection():
    while True:
        time.sleep(10)  # Check every 10 seconds
        if not verify_grpc_connection():
            logger.warning("gRPC connection lost, attempting to reconnect...")
            # Re-establish the gRPC channel
            global channel, stub
            channel = create_grpc_channel()
            stub = items_pb2_grpc.ItemServiceStub(channel)

if __name__ == '__main__':
    # Verify connection at startup
    if not verify_grpc_connection():
        logger.error("Initial gRPC connection failed")
    
    logger.info(f"Starting REST service on port 5000, connecting to gRPC at {GRPC_HOST}:{GRPC_PORT}")
    
    # Start the background thread for monitoring gRPC connection
    threading.Thread(target=monitor_grpc_connection, daemon=True).start()
    
    app.run(host="0.0.0.0", port=5000)

