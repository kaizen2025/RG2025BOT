from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
import os
import json
from datetime import datetime, timedelta
import threading
import logging
from dotenv import load_dotenv
import time
import sqlite3
from werkzeug.security import generate_password_hash
from functools import wraps
from threading import Thread
from db_persistence import run_db_persistence

# Import modules
from auth import auth_bp, get_user_by_id, get_user_preferences, login_required, admin_required, init_db
import pokemon_scraper

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "pokemon_monitor_secret_key")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')

# Configure log file handler
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = logging.FileHandler('logs/pokemon_bot_activity.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

# Add handler to root logger
root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

def ensure_database_exists():
    """S'assure que la base de données existe et contient les tables nécessaires"""
    try:
        # Initialiser la base de données
        init_db()
        logging.info("Base de données initialisée avec succès")
        
        # Créer le répertoire logs s'il n'existe pas
        if not os.path.exists('logs'):
            os.makedirs('logs')
            logging.info("Répertoire logs créé")
        
        return True
    except Exception as e:
        logging.error(f"Erreur lors de l'initialisation de la base de données: {e}")
        return False

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
            
            # Send personalized notifications to users
            conn = sqlite3.connect('database.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all users with active notification preferences for this product/collection
            query = """
                SELECT u.id, u.username, u.email, u.preferences, n.* 
                FROM users u
                JOIN user_notifications n ON u.id = n.user_id
                WHERE n.active = 1 
                AND (n.collection = ? OR n.collection = 'all')
                AND (n.product = ? OR n.product = '' OR n.product IS NULL)
                AND (n.site = ? OR n.site = '' OR n.site IS NULL)
                AND u.role = 'user'
            """
            
            collection_name = product_info["collection"]
            product_name = product_info["name"]
            site_name = site_info["name"]
            
            users_to_notify = cursor.execute(query, (collection_name, product_name, site_name)).fetchall()
            
            # Send notifications to these users
            for user in users_to_notify:
                # Check user's notification preferences
                preferences = {}
                if user['preferences']:
                    try:
                        preferences = json.loads(user['preferences'])
                    except:
                        pass
                
                # Check if price is within range
                price = product_data.get('price', 0)
                if price and user['min_price'] <= price <= user['max_price']:
                    # Send notification based on user preferences
                    if preferences.get('notifications_email', True):
                        # Send email notification
                        print(f"Sending email to {user['email']} about {product_name}")
                    
                    if preferences.get('notifications_telegram', False):
                        # Send telegram notification
                        print(f"Sending Telegram notification to {user['username']} about {product_name}")
            
            conn.close()
    
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
            
            # Send global notifications
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
                # Create a simplified version without large screenshot data
                save_stats = stats.copy()
                for key, result in save_stats["results"].items():
                    if "screenshots" in result:
                        # Keep screenshot info but remove the data
                        save_stats["results"][key]["screenshots"] = [
                            {"caption": ss.get("caption", "Screenshot")} for ss in result["screenshots"]
                        ]
                
                for alert in save_stats["active_alerts"]:
                    if "screenshots" in alert:
                        # Keep screenshot info but remove the data
                        alert["screenshots"] = [
                            {"caption": ss.get("caption", "Screenshot")} for ss in alert["screenshots"]
                        ]
                
                json.dump(save_stats, f)
        except Exception as e:
            logging.error(f"Error saving stats: {e}")
        
        # Wait before next check
        time.sleep(check_interval)

# Add function for simplified bot (for Render)
def simplified_bot():
    """Simplified version of the bot for Render environment that checks less frequently."""
    stats["total_checks"] = 0
    
    while True:
        try:
            now = datetime.now()
            stats["total_checks"] += 1
            stats["last_check"] = now.strftime("%d/%m/%Y %H:%M:%S")
            
            # Execute a check
            logging.info(f"[RENDER] Check #{stats['total_checks']} - {now.strftime('%d/%m/%Y %H:%M:%S')}")
            
            # List to collect all positive alerts
            alerts = []
            
            # Check highest priority sites only (to save resources on Render)
            high_priority_sites = [site for site in pokemon_scraper.SITES if site.get('priority', 0) >= 2]
            sites_to_check = high_priority_sites if high_priority_sites else pokemon_scraper.SITES[:2]
            
            for site in sites_to_check:
                try:
                    logging.info(f"[RENDER] Checking site: {site['name']}")
                    # Only check a subset of products on Render to save resources
                    products_to_check = site['products'][:3] if len(site['products']) > 3 else site['products']
                    
                    for product in products_to_check:
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
                            logging.info(f"[RENDER] DETECTION on {site['name']} for {product['name']}: {message}")
                        else:
                            logging.info(f"[RENDER] {site['name']} for {product['name']}: {message}")
                        
                        # Longer pause between products on Render
                        time.sleep(5)
                    
                    # Longer pause between sites on Render
                    time.sleep(10)
                except Exception as e:
                    logging.error(f"[RENDER] Error checking {site['name']}: {e}")
            
            # Handle alerts (same as in main program)
            if alerts:
                subject = f"ALERT - Pokemon cards in stock!"
                email_content = """
                Hello,
                
                Stock availability has been detected for Pokemon collections.
                
                Alert details:
                """
                
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
                
                notification_ok = pokemon_scraper.send_notifications(subject, email_content, alerts)
                if notification_ok:
                    stats["last_alert"] = now.strftime("%d/%m/%Y %H:%M:%S")
                    logging.info(f"[RENDER] ALERTS SENT - {len(alerts)} detections")
                else:
                    logging.error("[RENDER] Failed to send notifications")
            
            # Set next check time (longer interval for Render)
            next_check_time = now.timestamp() + 1800  # 30 minutes
            stats["next_check"] = datetime.fromtimestamp(next_check_time).strftime("%d/%m/%Y %H:%M:%S")
            logging.info(f"[RENDER] Next check: {stats['next_check']}")
            
            # Save stats to JSON file
            try:
                with open('logs/stats.json', 'w') as f:
                    save_stats = stats.copy()
                    for key, result in save_stats["results"].items():
                        if "screenshots" in result:
                            save_stats["results"][key]["screenshots"] = [
                                {"caption": ss.get("caption", "Screenshot")} for ss in result["screenshots"]
                            ]
                    
                    for alert in save_stats["active_alerts"]:
                        if "screenshots" in alert:
                            alert["screenshots"] = [
                                {"caption": ss.get("caption", "Screenshot")} for ss in alert["screenshots"]
                            ]
                    
                    json.dump(save_stats, f)
            except Exception as e:
                logging.error(f"[RENDER] Error saving stats: {e}")
            
            # Wait longer between checks on Render
            time.sleep(1800)  # 30 minutes
        except Exception as e:
            logging.error(f"[RENDER] Bot error: {e}")
            time.sleep(300)  # Wait 5 minutes in case of error

# Replace main function
pokemon_scraper.main_program = main_program_wrapper

# Utility function to get user context
def get_user_context():
    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        if user:
            preferences = get_user_preferences(session['user_id'])
            return {
                'user': user,
                'preferences': preferences
            }
    return None

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('auth.login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_context = get_user_context()
    collections = [c["name"] for c in pokemon_scraper.POKEMON_COLLECTIONS]
    return render_template('dashboard.html', 
                          collections=collections, 
                          user=user_context['user'], 
                          preferences=user_context['preferences'])

@app.route('/collections')
@login_required
def collections():
    user_context = get_user_context()
    collections = [c["name"] for c in pokemon_scraper.POKEMON_COLLECTIONS]
    return render_template('collections.html', 
                          collections=collections,
                          user=user_context['user'], 
                          preferences=user_context['preferences'])

@app.route('/sites')
@login_required
def sites():
    user_context = get_user_context()
    return render_template('sites.html',
                          user=user_context['user'], 
                          preferences=user_context['preferences'])

@app.route('/api/stats')
@login_required
def get_stats():
    # Add collection data
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
    
    # Get user's notifications
    if 'user_id' in session:
        user_id = session['user_id']
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        notifications = conn.execute(
            'SELECT * FROM user_notifications WHERE user_id = ? AND active = 1', 
            (user_id,)
        ).fetchall()
        conn.close()
        
        # Convert to list of dicts
        enhanced_stats["user_notifications"] = [dict(notification) for notification in notifications]
    
    return jsonify(enhanced_stats)

@app.route('/api/logs')
@login_required
def get_logs():
    try:
        with open('logs/pokemon_bot_activity.log', 'r') as f:
            logs = f.readlines()
        return jsonify(logs[-100:])  # Return last 100 lines
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/proxy', methods=['GET', 'POST'])
@admin_required
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
@login_required
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
@login_required
def get_circuit_breakers():
    if hasattr(pokemon_scraper, 'circuit_breakers'):
        return jsonify({
            name: {"state": cb.state, "failure_count": cb.failure_count} 
            for name, cb in pokemon_scraper.circuit_breakers.items()
        })
    return jsonify({})

@app.route('/api/collections')
@login_required
def get_collections():
    collections = []
    for collection in pokemon_scraper.POKEMON_COLLECTIONS:
        collections.append({
            "name": collection["name"],
            "keywords": collection["keywords"],
            "image_url": collection["image_url"]
        })
    return jsonify(collections)

@app.route('/api/sites')
@login_required
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

@app.route('/api/user/notifications', methods=['POST'])
@login_required
def save_user_notification():
    """Save a user notification preference."""
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    
    user_id = session['user_id']
    data = request.json
    
    collection = data.get('collection', '')
    product = data.get('product', '')
    site = data.get('site', '')
    min_price = float(data.get('min_price', 0))
    max_price = float(data.get('max_price', 9999))
    
    conn = sqlite3.connect('database.db')
    conn.execute(
        'INSERT INTO user_notifications (user_id, collection, product, site, min_price, max_price) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, collection, product, site, min_price, max_price)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Notification preference saved"})

@app.route('/api/user/notifications/<int:notification_id>', methods=['DELETE'])
@login_required
def delete_user_notification(notification_id):
    """Delete a user notification preference."""
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    
    user_id = session['user_id']
    
    conn = sqlite3.connect('database.db')
    conn.execute(
        'DELETE FROM user_notifications WHERE id = ? AND user_id = ?',
        (notification_id, user_id)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Notification deleted"})

def run_app():
    """Run the Flask app with the appropriate settings."""
    # Initialize database
    init_db()
    
    # Debug mode should be configurable and off in production
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=debug_mode)

def run_bot():
    """Run the stock monitoring bot in a background thread."""
    # Start the bot
    pokemon_scraper.main_program()

if __name__ == "__main__":
    # Initialiser la base de données AVANT toute autre opération
    if not ensure_database_exists():
        logging.error("ERREUR CRITIQUE: Échec de l'initialisation de la base de données")
        exit(1)
    
    # En environnement de production (comme Render), utilisez le port fourni par l'environnement
    port = int(os.environ.get("PORT", 5000))
    
    # Démarrer le thread de persistance de la base de données sur Render
    on_render = os.environ.get('RENDER', 'false').lower() == 'true'
    if on_render:
        # Démarrer la persistence en premier
        persistence_thread = threading.Thread(target=run_db_persistence)
        persistence_thread.daemon = True
        persistence_thread.start()
        logging.info("Thread de persistance de la base de données démarré")
        
        # Attendre 5 secondes pour que la persistence puisse télécharger/initialiser la BD
        import time
        time.sleep(5)
        
        # Vérifier une dernière fois que la BD existe
        ensure_database_exists()
        
        # Sur Render, démarrez le bot simplifié
        bot_thread = Thread(target=simplified_bot)
        bot_thread.daemon = True
        bot_thread.start()
        logging.info("Started simplified bot for Render environment")
    else:
        # Pour le développement local, démarrer normalement
        bot_thread = Thread(target=run_bot)
        bot_thread.daemon = True
        bot_thread.start()
        logging.info("Started regular bot for local environment")
    
    # Démarrer l'application Flask
    # Debug mode should be off in production
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
