from flask import Flask, render_template, jsonify, request
import os
import json
from datetime import datetime
import threading
import logging
from dotenv import load_dotenv
import time
import chromedriver_autoinstaller
from PIL import Image
import base64
import io
import requests

# Import the main monitoring script
import pokemon_scraper

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Data storage for web interface
stats = {
    "last_check": None,
    "next_check": None,
    "total_checks": 0,
    "last_alert": None,
    "monitored_sites": pokemon_scraper.SITES,
    "results": {},
    "active_alerts": [],
    "collections_data": {
        collection["name"]: {
            "image_url": collection["image_url"],
            "keywords": collection["keywords"]
        } for collection in pokemon_scraper.POKEMON_COLLECTIONS
    }
}

# Create logs folder if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Configure log file handler
file_handler = logging.FileHandler('logs/pokemon_bot_activity.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

# Add handler to root logger
root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

# Override check function to update stats
original_check_site_product = pokemon_scraper.check_site_product

def check_site_product_wrapper(site_info, product_info):
    """Wrap the check function to update statistics."""
    available, message, screenshots, product_data = original_check_site_product(site_info, product_info)
    
    # Update stats
    result_key = f"{site_info['name']}_{product_info['name']}"
    stats["results"][result_key] = {
        "available": available,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "date": datetime.now().strftime("%d/%m/%Y"),
        "screenshots": screenshots,
        "product_data": product_data,
        "site_name": site_info["name"],
        "product_name": product_info["name"],
        "collection": product_info["collection"],
        "url": product_info["url"]
    }
    
    # If available, add to active alerts
    if available:
        # Check if alert already exists
        existing_alert = False
        for alert in stats["active_alerts"]:
            if alert["source"] == site_info["name"] and alert["product_name"] == product_info["name"]:
                existing_alert = True
                # Update existing alert
                alert["message"] = message
                alert["timestamp"] = datetime.now().strftime("%H:%M:%S")
                alert["date"] = datetime.now().strftime("%d/%m/%Y")
                alert["screenshots"] = screenshots
                alert["product_data"] = product_data
                break
        
        if not existing_alert:
            stats["active_alerts"].append({
                "source": site_info["name"],
                "product_name": product_info["name"],
                "collection": product_info["collection"],
                "message": message,
                "url": product_info["url"],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "date": datetime.now().strftime("%d/%m/%Y"),
                "screenshots": screenshots,
                "product_data": product_data
            })
    
    return available, message, screenshots, product_data

# Replace original function
pokemon_scraper.check_site_product = check_site_product_wrapper

# Adapt main function to update stats
original_main_program = pokemon_scraper.main_program

def main_program_wrapper():
    """Wrap the main function to update statistics."""
    stats["total_checks"] = 0
    
    while True:
        now = datetime.now()
        stats["total_checks"] += 1
        stats["last_check"] = now.strftime("%d/%m/%Y %H:%M:%S")
        
        # Execute a check
        logging.info(f"Check #{stats['total_checks']} - {now.strftime('%d/%m/%Y %H:%M:%S')}")
        
        # List to collect all positive alerts
        alerts = []
        
        # 1. Check all configured sites
        for site in pokemon_scraper.SITES:
            try:
                logging.info(f"Checking site: {site['name']}")
                for product in site['products']:
                    available, message, screenshots, product_data = pokemon_scraper.check_site_product(site, product)
                    if available:
                        alerts.append({
                            "source": site["name"],
                            "product_name": product["name"],
                            "collection": product["collection"],
                            "message": message,
                            "url": product["url"],
                            "screenshots": screenshots,
                            "product_data": product_data
                        })
                        logging.info(f"DETECTION on {site['name']} for {product['name']}: {message}")
                    else:
                        logging.info(f"{site['name']} for {product['name']}: {message}")
                    
                    # Short pause between products
                    time.sleep(1)
                
                # Short pause between sites
                time.sleep(2)
            except Exception as e:
                logging.error(f"Error checking {site['name']}: {e}")
        
        # If alerts were found, send notifications
        if alerts:
            # Build email with all alerts
            subject = f"ALERT - Pokemon cards in stock!"
            
            # Build email content
            email_content = """
            Hello,
            
            Stock availability has been detected for Pokemon collections.
            
            Alert details:
            """
            
            # Add each alert
            for idx, alert in enumerate(alerts, 1):
                email_content += f"""
            {idx}. {alert['source']} - {alert['product_name']}
               {alert['message']}
               URL: {alert['url']}
            """
            
            email_content += """
            Please check these sites quickly to confirm and make your purchase.
            
            This message was automatically sent by your monitoring bot.
            """
            
            # Send notifications
            notification_ok = pokemon_scraper.send_notifications(subject, email_content, alerts)
            if notification_ok:
                stats["last_alert"] = now.strftime("%d/%m/%Y %H:%M:%S")
                logging.info(f"ALERTS SENT - {len(alerts)} detections")
            else:
                logging.error("Failed to send notifications")
        
        # Calculate next check
        check_interval = pokemon_scraper.random.randint(
            pokemon_scraper.CHECK_INTERVAL_MIN, 
            pokemon_scraper.CHECK_INTERVAL_MAX
        )
        next_check_time = now.timestamp() + check_interval
        stats["next_check"] = datetime.fromtimestamp(next_check_time).strftime("%d/%m/%Y %H:%M:%S")
        
        # Log next check time
        logging.info(f"Next check: {stats['next_check']}")
        
        # Save stats to JSON file for persistence
        try:
            with open('logs/stats.json', 'w') as f:
                json.dump(stats, f)
        except Exception as e:
            logging.error(f"Error saving stats: {e}")
        
        # Wait before next check
        time.sleep(check_interval)

# Replace main function
pokemon_scraper.main_program = main_program_wrapper

# Fetch product image from URL and convert to base64
def fetch_image_as_base64(image_url):
    try:
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            image_data = base64.b64encode(response.content).decode('utf-8')
            return image_data
        return None
    except Exception as e:
        logging.error(f"Error fetching image {image_url}: {e}")
        return None

# Flask routes
@app.route('/')
def index():
    collections = [c["name"] for c in pokemon_scraper.POKEMON_COLLECTIONS]
    return render_template('index.html', collections=collections)

@app.route('/api/stats')
def get_stats():
    # Enhance stats with collection data
    enhanced_stats = stats.copy()
    
    # Group results by collection
    collection_results = {}
    for collection in pokemon_scraper.POKEMON_COLLECTIONS:
        collection_name = collection["name"]
        collection_results[collection_name] = {
            "name": collection_name,
            "image_url": collection["image_url"],
            "products": [],
            "in_stock_count": 0
        }
    
    # Add products to their collections
    for result_key, result in stats["results"].items():
        if "collection" in result:
            collection_name = result["collection"]
            if collection_name in collection_results:
                product_info = {
                    "name": result["product_name"],
                    "site": result["site_name"],
                    "url": result["url"],
                    "available": result["available"],
                    "price": result["product_data"].get("price", "N/A"),
                    "message": result["message"],
                    "timestamp": result["timestamp"],
                    "date": result["date"]
                }
                collection_results[collection_name]["products"].append(product_info)
                if result["available"]:
                    collection_results[collection_name]["in_stock_count"] += 1
    
    enhanced_stats["collection_results"] = collection_results
    
    return jsonify(enhanced_stats)

@app.route('/api/logs')
def get_logs():
    try:
        with open('logs/pokemon_bot_activity.log', 'r') as f:
            logs = f.readlines()
        return jsonify(logs[-100:])  # Return last 100 lines
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/proxy', methods=['GET', 'POST'])
def handle_proxy():
    if request.method == 'POST':
        data = request.json
        # Update proxy settings in the bot
        os.environ["PROXY_SERVICE"] = data.get("service", "none")
        os.environ["PROXY_USERNAME"] = data.get("username", "")
        os.environ["PROXY_PASSWORD"] = data.get("password", "")
        os.environ["PROXY_HOST"] = data.get("host", "")
        os.environ["PROXY_PORT"] = data.get("port", "")
        os.environ["PROXY_COUNTRY"] = data.get("country", "fr")
        
        # Reload proxy manager
        pokemon_scraper.proxy_manager = pokemon_scraper.ProxyManager()
        
        return jsonify({"status": "success"})
    else:
        return jsonify({
            "service": os.getenv("PROXY_SERVICE", "none"),
            "username": os.getenv("PROXY_USERNAME", ""),
            "host": os.getenv("PROXY_HOST", ""),
            "port": os.getenv("PROXY_PORT", ""),
            "country": os.getenv("PROXY_COUNTRY", "fr")
        })

@app.route('/api/refresh/<site_name>/<product_name>', methods=['POST'])
def refresh_product(site_name, product_name):
    """Manually check a specific product."""
    try:
        for site in pokemon_scraper.SITES:
            if site["name"] == site_name:
                for product in site["products"]:
                    if product["name"] == product_name:
                        available, message, screenshots, product_data = pokemon_scraper.check_site_product(site, product)
                        return jsonify({
                            "status": "success",
                            "available": available,
                            "message": message,
                            "product_data": product_data
                        })
        return jsonify({"status": "error", "message": "Product or site not found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/circuit-breakers')
def get_circuit_breakers():
    if hasattr(pokemon_scraper, 'circuit_breakers'):
        return jsonify({
            name: {"state": cb.state, "failure_count": cb.failure_count} 
            for name, cb in pokemon_scraper.circuit_breakers.items()
        })
    return jsonify({})

@app.route('/api/collections')
def get_collections():
    collections = []
    for collection in pokemon_scraper.POKEMON_COLLECTIONS:
        # Fetch image as base64 if not already cached
        image_data = None
        if collection["image_url"]:
            image_data = fetch_image_as_base64(collection["image_url"])
        
        collections.append({
            "name": collection["name"],
            "keywords": collection["keywords"],
            "image_data": image_data,
            "image_url": collection["image_url"]
        })
    return jsonify(collections)

@app.route('/api/sites')
def get_sites():
    """Get information about monitored sites."""
    sites_info = []
    for site in pokemon_scraper.SITES:
        sites_info.append({
            "name": site["name"],
            "base_url": site["base_url"],
            "type": site["type"],
            "country": site["country"],
            "priority": site["priority"],
            "product_count": len(site["products"])
        })
    return jsonify(sites_info)

def run_app():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

def run_bot():
    # Start the bot
    pokemon_scraper.main_program()

if __name__ == "__main__":
    # Start the bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Run Flask application
    run_app()
