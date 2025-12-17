#!/usr/bin/env python3
"""
Dedicated keep-alive script to prevent Render from sleeping
Run this as a separate worker
"""
import os
import time
import requests
import schedule
from datetime import datetime

def ping_services():
    """Ping all services to keep them awake"""
    services = [
        os.getenv('RENDER_EXTERNAL_URL', ''),
        os.getenv('HEALTH_CHECK_URL', ''),
        "https://hc-ping.com/YOUR_UPTIME_ROBOT_KEY"  # For Uptime Robot
    ]
    
    for service in services:
        if service:
            try:
                response = requests.get(service, timeout=10)
                print(f"[{datetime.now()}] ✅ Pinged {service}: {response.status_code}")
            except Exception as e:
                print(f"[{datetime.now()}] ❌ Failed to ping {service}: {e}")

def main():
    print("🚀 Starting keep-alive service...")
    
    # Ping immediately
    ping_services()
    
    # Schedule every 5 minutes
    schedule.every(5).minutes.do(ping_services)
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    main()
