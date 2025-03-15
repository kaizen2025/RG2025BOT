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

# Importer le script principal de surveillance
import roland_garros_bot

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__)

# Stockage des données pour l'interface web
stats = {
    "derniere_verification": None,
    "prochaine_verification": None,
    "nombre_verifications": 0,
    "derniere_alerte": None,
    "sites_surveilles": roland_garros_bot.SITES,
    "resultats": {},
    "alertes_actives": []
}

# Créer un dossier logs s'il n'existe pas
if not os.path.exists('logs'):
    os.makedirs('logs')

# Configure log file handler
file_handler = logging.FileHandler('logs/bot_activity.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

# Ajouter le handler au logger root
root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

# Surcharger les fonctions pour mettre à jour les stats
original_verifier_site = roland_garros_bot.verifier_site

def verifier_site_wrapper(site_info):
    """Enveloppe la fonction de vérification pour mettre à jour les statistiques."""
    disponible, message, screenshots = original_verifier_site(site_info)
    
    # Mettre à jour les stats
    stats["resultats"][site_info["nom"]] = {
        "disponible": disponible,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "date": datetime.now().strftime("%d/%m/%Y"),
        "screenshots": screenshots  # Ajouter les screenshots
    }
    
    # Si disponible, ajouter aux alertes actives
    if disponible:
        # Vérifier si l'alerte existe déjà
        alerte_existante = False
        for alerte in stats["alertes_actives"]:
            if alerte["source"] == site_info["nom"]:
                alerte_existante = True
                # Mettre à jour l'alerte existante
                alerte["message"] = message
                alerte["timestamp"] = datetime.now().strftime("%H:%M:%S")
                alerte["date"] = datetime.now().strftime("%d/%m/%Y")
                alerte["screenshots"] = screenshots  # Ajouter les screenshots
                break
        
        if not alerte_existante:
            stats["alertes_actives"].append({
                "source": site_info["nom"],
                "message": message,
                "url": site_info["url"],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "date": datetime.now().strftime("%d/%m/%Y"),
                "screenshots": screenshots  # Ajouter les screenshots
            })
    
    return disponible, message, screenshots  # Retourner screenshots aussi

# Remplacer la fonction originale
roland_garros_bot.verifier_site = verifier_site_wrapper

# Adapter la fonction principale pour mettre à jour les stats
original_programme_principal = roland_garros_bot.programme_principal

def programme_principal_wrapper():
    """Enveloppe la fonction principale pour mettre à jour les statistiques."""
    stats["nombre_verifications"] = 0
    
    while True:
        maintenant = datetime.now()
        stats["nombre_verifications"] += 1
        stats["derniere_verification"] = maintenant.strftime("%d/%m/%Y %H:%M:%S")
        
        # Exécuter une vérification
        logging.info(f"Vérification #{stats['nombre_verifications']} - {maintenant.strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Liste pour collecter toutes les alertes positives
        alertes = []
        
        # 1. Vérifier tous les sites configurés
        for site in roland_garros_bot.SITES:
            try:
                disponible, message, screenshots = roland_garros_bot.verifier_site(site)
                if disponible:
                    alertes.append({
                        "source": site["nom"],
                        "message": message,
                        "url": site["url"],
                        "screenshots": screenshots
                    })
                    logging.info(f"DÉTECTION sur {site['nom']}: {message}")
                else:
                    logging.info(f"{site['nom']}: {message}")
                
                # Pause courte entre chaque site pour éviter d'être bloqué
                time.sleep(1)  # Réduit à 1 seconde pour l'interface web
            except Exception as e:
                logging.error(f"Erreur lors de la vérification de {site['nom']}: {e}")
        
        # Si des alertes ont été trouvées, envoyer des notifications
        if alertes:
            # Construire l'email avec toutes les alertes
            sujet = f"ALERTE - Billets Roland-Garros disponibles pour le {roland_garros_bot.DATE_CIBLE}!"
            
            # Construire le contenu de l'email
            contenu_email = f"""
            Bonjour,
            
            Des disponibilités potentielles ont été détectées pour Roland-Garros le {roland_garros_bot.DATE_CIBLE}.
            
            Détails des alertes:
            """
            
            # Ajouter chaque alerte
            for idx, alerte in enumerate(alertes, 1):
                contenu_email += f"""
            {idx}. {alerte['source']}
               {alerte['message']}
               URL: {alerte['url']}
            """
            
            contenu_email += """
            Veuillez vérifier rapidement ces sites pour confirmer et effectuer votre achat.
            
            Ce message a été envoyé automatiquement par votre bot de surveillance.
            """
            
            # Envoyer les notifications
            notification_ok = roland_garros_bot.envoyer_notifications(sujet, contenu_email, alertes)
            if notification_ok:
                stats["derniere_alerte"] = maintenant.strftime("%d/%m/%Y %H:%M:%S")
                logging.info(f"ALERTES ENVOYÉES - {len(alertes)} détections")
            else:
                logging.error("Échec de l'envoi des notifications")
        
        # Calculer la prochaine vérification
        prochaine_verification = maintenant.timestamp() + roland_garros_bot.INTERVALLE_VERIFICATION
        stats["prochaine_verification"] = datetime.fromtimestamp(prochaine_verification).strftime("%d/%m/%Y %H:%M:%S")
        
        # Écrire dans les logs l'heure de la prochaine vérification
        logging.info(f"Prochaine vérification: {stats['prochaine_verification']}")
        
        # Sauvegarder les stats dans un fichier JSON pour persistance
        try:
            with open('logs/stats.json', 'w') as f:
                json.dump(stats, f)
        except Exception as e:
            logging.error(f"Erreur lors de la sauvegarde des stats: {e}")
        
        # Attendre avant la prochaine vérification
        time.sleep(roland_garros_bot.INTERVALLE_VERIFICATION)

# Remplacer la fonction principale
roland_garros_bot.programme_principal = programme_principal_wrapper

# Routes Flask
@app.route('/')
def index():
    return render_template('index.html', date_cible=roland_garros_bot.DATE_CIBLE)

@app.route('/api/stats')
def get_stats():
    return jsonify(stats)

@app.route('/api/logs')
def get_logs():
    try:
        with open('logs/bot_activity.log', 'r') as f:
            logs = f.readlines()
        return jsonify(logs[-100:])  # Renvoyer les 100 dernières lignes
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
        return jsonify({"status": "success"})
    else:
        return jsonify({
            "service": os.getenv("PROXY_SERVICE", "none"),
            "username": os.getenv("PROXY_USERNAME", ""),
            "host": os.getenv("PROXY_HOST", ""),
            "port": os.getenv("PROXY_PORT", ""),
            "country": os.getenv("PROXY_COUNTRY", "fr")
        })

@app.route('/api/auto-reservation', methods=['GET', 'POST'])
def handle_auto_reservation():
    if request.method == 'POST':
        data = request.json
        # Update auto-reservation settings
        os.environ["AUTO_RESERVATION"] = str(data.get("enabled", False)).lower()
        os.environ["RESERVATION_EMAIL"] = data.get("email", "")
        os.environ["RESERVATION_PASSWORD"] = data.get("password", "")
        os.environ["RESERVATION_MAX_PRIX"] = str(data.get("max_price", 1000))
        return jsonify({"status": "success"})
    else:
        return jsonify({
            "enabled": os.getenv("AUTO_RESERVATION", "False").lower() in ["true", "1", "yes", "oui"],
            "email": os.getenv("RESERVATION_EMAIL", ""),
            "max_price": float(os.getenv("RESERVATION_MAX_PRIX", "1000"))
        })

@app.route('/api/circuit-breakers')
def get_circuit_breakers():
    if hasattr(roland_garros_bot, 'circuit_breakers'):
        return jsonify({
            nom: {"state": cb.state, "failure_count": cb.failure_count} 
            for nom, cb in roland_garros_bot.circuit_breakers.items()
        })
    return jsonify({})

def run_app():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

def run_bot():
    # Lancer le bot
    roland_garros_bot.programme_principal()

if __name__ == "__main__":
    # Démarrer le bot dans un thread séparé
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Exécuter l'application Flask
    run_app()
