from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram Bot Hosting",
        "version": "1.0.0",
        "endpoints": ["/health", "/ping", "/stats"]
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/ping')
def ping():
    return "pong"

@app.route('/stats')
def stats():
    import psutil
    from datetime import datetime
    
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
