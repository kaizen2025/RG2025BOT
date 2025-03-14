from flask import Flask, render_template, jsonify
import os
import json
from datetime import datetime
import threading
import logging
from dotenv import load_dotenv
import time

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
    disponible, message = original_verifier_site(site_info)
    
    # Mettre à jour les stats
    stats["resultats"][site_info["nom"]] = {
        "disponible": disponible,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "date": datetime.now().strftime("%d/%m/%Y")
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
                break
        
        if not alerte_existante:
            stats["alertes_actives"].append({
                "source": site_info["nom"],
                "message": message,
                "url": site_info["url"],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "date": datetime.now().strftime("%d/%m/%Y")
            })
    
    return disponible, message

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
                disponible, message = roland_garros_bot.verifier_site(site)
                if disponible:
                    alertes.append({
                        "source": site["nom"],
                        "message": message,
                        "url": site["url"]
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