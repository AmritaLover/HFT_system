import zmq
import time
import json

SERVER_IP = '127.0.0.1'
SERVER_PORT = '5555'
RELAY_HOST = '*'
RELAY_PORT = '5556'

def main():
    print("--- Network Relay Node ---")
    context = zmq.Context()

    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(f"tcp://{SERVER_IP}:{SERVER_PORT}")
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") 
    print(f"Relay connected to Server at tcp://{SERVER_IP}:{SERVER_PORT}")

    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind(f"tcp://{RELAY_HOST}:{RELAY_PORT}")
    print(f"Relay broadcasting for clients on tcp://{RELAY_HOST}:{RELAY_PORT}")

    print("Waiting 1 second for clients to connect...")
    time.sleep(1)

    print("Starting message forwarding loop...")
    msg_count = 0
    
    while True:
        try:
            message = sub_socket.recv_multipart()
            
            relay_arrival_ts = time.perf_counter()
            msg_count += 1
            if msg_count % 5000 == 0:
                payload = json.loads(message[1])
                latency_ms = (relay_arrival_ts - payload['origin_ts']) * 1000
                print(f"Msg {payload.get('seq_num', msg_count)}: Server-to-Relay latency = {latency_ms:.2f} ms")
            
            pub_socket.send_multipart(message)
        except (zmq.ContextTerminated, KeyboardInterrupt):
            break
    
    print("\nRelay shut down.")
    sub_socket.close()
    pub_socket.close()
    context.term()

if __name__ == '__main__':
    main()