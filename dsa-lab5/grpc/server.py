import grpc
from concurrent import futures
import items_pb2
import items_pb2_grpc
import logging
import os
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from grpc_health.v1 import health_pb2, health_pb2_grpc, health
#from grpc_prometheus import (enable_server_handling_time_histogram,GRPC_SERVER_HANDLING_SECONDS,
#                             enable_server_metrics, enable_client_metrics)
from prometheus_client import start_http_server, Histogram


#---------------------

# 1. Start the HTTP endpoint *before* the gRPC server
start_http_server(9103) # /metrics lives here

# 2. Build the gRPC server
#serv = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

# register your ItemServiceServicer ... (existing code)

# 3. Turn on default histogram metrics
#enable_server_handling_time_histogram(serv)
# serv.add_insecure_port("[::]:50051")
# serv.start()
# serv.wait_for_termination()

GRPC_SERVER_HANDLING_SECONDS = Histogram(
    'grpc_server_handling_seconds',
    'gRPC server handling time in seconds',
    ['method']
)

#---------------------

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# MongoDB connection setup
mongo_host = os.environ.get("MONGO_HOST", "localhost")
mongo_port = int(os.environ.get("MONGO_PORT", "27017"))
mongo_db = os.getenv("MONGO_DB", "itemsdb")
mongo_user = os.getenv("MONGO_USER", "root")
mongo_pass = os.getenv("MONGO_PASSWORD", "example")

try:
    client = MongoClient(
        f"mongodb://{mongo_user}:{mongo_pass}@{mongo_host}:{mongo_port}",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=2000,
        socketTimeoutMS=5000
    )
    client.admin.command('ping')  # Test connection
    db = client[mongo_db]
    collection = db["items"]
    collection.create_index("id", unique=True)
    logging.info(f"Connected to MongoDB at {mongo_host}:{mongo_port}")
except PyMongoError as e:
    logging.error(f"Failed to connect to MongoDB: {e}")
    client = db = collection = None

class HealthServicer(health_pb2_grpc.HealthServicer):
    def Check(self, request, context):
        if client is None:
            return health_pb2.HealthCheckResponse(
                status=health_pb2.HealthCheckResponse.NOT_SERVING)
        try:
            client.admin.command('ping')
            return health_pb2.HealthCheckResponse(
                status=health_pb2.HealthCheckResponse.SERVING)
        except PyMongoError:
            return health_pb2.HealthCheckResponse(
                status=health_pb2.HealthCheckResponse.NOT_SERVING)

class ItemServiceServicer(items_pb2_grpc.ItemServiceServicer):
    def _check_db(self, context):
        if collection is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Database unavailable")
            return False
        return True

    def GetItemById(self, request, context):
        with GRPC_SERVER_HANDLING_SECONDS.labels(method='GetItemById').time():
            if not self._check_db(context):
                return items_pb2.ItemResponse()
            
            try:
                doc = collection.find_one({"id": request.id})
                if not doc:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details("Item not found")
                    return items_pb2.ItemResponse()
                return items_pb2.ItemResponse(id=doc["id"], name=doc["name"])
            except PyMongoError as e:
                logging.error(f"Error retrieving item {request.id}: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Database error")
                return items_pb2.ItemResponse()

    def ListAllItems(self, request, context):
        with GRPC_SERVER_HANDLING_SECONDS.labels(method='ListAllItems').time():
            if not self._check_db(context):
                return
            
            try:
                for doc in collection.find():
                    yield items_pb2.ItemResponse(id=doc["id"], name=doc["name"])
            except PyMongoError as e:
                logging.error(f"Error listing items: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Database error")

    def AddItem(self, request, context):
        with GRPC_SERVER_HANDLING_SECONDS.labels(method='AddItem').time():
            if not self._check_db(context):
                return items_pb2.ItemResponse()
            
            try:
                if request.id > 0 and collection.find_one({"id": request.id}):
                    context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                    context.set_details("Item exists")
                    return items_pb2.ItemResponse()
                
                new_id = request.id if request.id > 0 else self._get_next_id()
                collection.insert_one({"id": new_id, "name": request.name})
                return items_pb2.ItemResponse(id=new_id, name=request.name)
            except PyMongoError as e:
                logging.error(f"Error creating item: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Database error")
                return items_pb2.ItemResponse()

    def _get_next_id(self):
        last_item = collection.find_one(sort=[("id", -1)])
        return (last_item["id"] + 1) if last_item else 1

def serve():
    # Add a small delay to ensure MongoDB is ready
    import time
    time.sleep(5)
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    items_pb2_grpc.add_ItemServiceServicer_to_server(ItemServiceServicer(), server)
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    
    try:
        # ONLY use working directory paths (no /app/)
        cert_files = ["ca.crt", "grpc-service.key", "grpc-service.crt"]
        missing_files = [f for f in cert_files if not os.path.exists(f)]
        
        if missing_files:
            raise FileNotFoundError(f"Missing certificate files: {missing_files}")
            
        # Load certificates from working directory
        with open("ca.crt", "rb") as f:
            root_certificates = f.read()
        with open("grpc-service.key", "rb") as f:
            private_key = f.read()
        with open("grpc-service.crt", "rb") as f:
            certificate_chain = f.read()
            
        # Create SSL server credentials
        creds = grpc.ssl_server_credentials(
            [(private_key, certificate_chain)],
            root_certificates=root_certificates,
            require_client_auth=True
        )
        
        server.add_secure_port('[::]:50051', creds)
        logging.info("✅ gRPC Server started on port 50051 with mutual TLS")
        
    except (FileNotFoundError, Exception) as e:
        logging.warning(f"⚠️  TLS setup failed ({e}), using insecure channel")
        server.add_insecure_port("[::]:50051")
        logging.info("❌ gRPC Server started on port 50051 (insecure)")
        
    server.start()
    logging.info("🚀 gRPC server is listening and ready")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()