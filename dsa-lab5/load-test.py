# Terminal 1 - Success requests
while true; do curl http://localhost:5000/items; sleep 0.5; done

# Terminal 2 - Error requests
while true; do curl http://localhost:5000/nonexistent; sleep 2; done


#From the Prometheus UI, you can check the targets at:
http://localhost:9090/targets

