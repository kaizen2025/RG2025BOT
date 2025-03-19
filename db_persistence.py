# db_persistence.py - Version corrigée
import os
import subprocess
import time
import shutil
import logging
import sqlite3
import requests
import base64
import hashlib
from datetime import datetime
import json

# Configuration
GITHUB_REPO = os.environ.get("GITHUB_REPO", "kaizen2025/database")  # Format: username/repo
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
DB_PATH = "database.db"
BACKUP_INTERVAL = 900  # 15 minutes

# Configurer le logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("DB-Persistence")

def calculate_file_hash(filepath):
    """Calcule le hash MD5 d'un fichier"""
    if not os.path.exists(filepath):
        return None
    
    md5_hash = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

def get_file_from_github():
    """Récupère le fichier DB depuis GitHub"""
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN non configuré")
        return False
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # Vérifier si le fichier existe sur GitHub
        response = requests.get(f"{GITHUB_API}/{DB_PATH}", headers=headers)
        
        if response.status_code == 200:
            # Fichier trouvé, télécharger
            content = response.json()
            file_content = base64.b64decode(content['content'])
            
            # Sauvegarder le fichier local actuel si existant
            if os.path.exists(DB_PATH):
                backup_path = f"{DB_PATH}.backup"
                shutil.copy2(DB_PATH, backup_path)
                logger.info(f"Sauvegarde locale créée: {backup_path}")
            
            # Écrire le fichier téléchargé
            with open(DB_PATH, "wb") as f:
                f.write(file_content)
            
            logger.info(f"Base de données téléchargée depuis GitHub")
            return True
        elif response.status_code == 404:
            logger.warning("Base de données non trouvée sur GitHub, une nouvelle sera créée")
            return False
        else:
            logger.error(f"Erreur lors de la récupération: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Erreur lors de la récupération depuis GitHub: {e}")
        return False

def upload_file_to_github():
    """Pousse la base de données vers GitHub"""
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN non configuré")
        return False
    
    if not os.path.exists(DB_PATH):
        logger.error(f"Le fichier {DB_PATH} n'existe pas")
        return False
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # Vérifier si le fichier existe déjà
        response = requests.get(f"{GITHUB_API}/{DB_PATH}", headers=headers)
        
        # Lire le contenu du fichier
        with open(DB_PATH, "rb") as f:
            file_content = f.read()
        
        encoded_content = base64.b64encode(file_content).decode()
        commit_message = f"Update database - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        data = {
            "message": commit_message,
            "content": encoded_content,
        }
        
        # Si le fichier existe déjà, inclure son SHA
        if response.status_code == 200:
            data["sha"] = response.json()["sha"]
        
        # Envoyer le fichier
        upload_response = requests.put(
            f"{GITHUB_API}/{DB_PATH}",
            headers=headers,
            json=data
        )
        
        if upload_response.status_code in [200, 201]:
            logger.info(f"Base de données sauvegardée sur GitHub")
            return True
        else:
            logger.error(f"Erreur lors de l'envoi: {upload_response.status_code} - {upload_response.text}")
            return False
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi vers GitHub: {e}")
        return False

def verify_db_integrity():
    """Vérifie que la base de données est utilisable"""
    if not os.path.exists(DB_PATH):
        logger.warning("Base de données non trouvée localement")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        # Vérifier que les tables essentielles existent
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        
        table_names = [table[0] for table in tables]
        
        if 'users' in table_names and 'user_notifications' in table_names:
            logger.info(f"Base de données vérifiée: {len(tables)} tables trouvées")
            return True
        else:
            logger.warning(f"Base de données incomplète. Tables trouvées: {table_names}")
            return False
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de la vérification de la base de données: {e}")
        return False

def create_db_schema():
    """Crée le schéma de la base de données si nécessaire"""
    try:
        logger.info("Initialisation du schéma de la base de données...")
        from auth import init_db
        init_db()
        logger.info("Schéma de la base de données créé avec succès.")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la création du schéma: {e}")
        return False

def run_db_persistence():
    """Fonction principale de persistance de la base de données"""
    logger.info("Démarrage du service de persistance de la base de données")
    
    # 1. Tenter de récupérer la DB depuis GitHub
    db_downloaded = get_file_from_github()
    
    # 2. Vérifier l'intégrité
    db_valid = False
    if db_downloaded:
        db_valid = verify_db_integrity()
        logger.info(f"Base de données téléchargée et vérifiée: {'Valide' if db_valid else 'Invalide'}")
    else:
        logger.warning("Échec du téléchargement depuis GitHub")
    
    # 3. Si la base de données n'est pas valide, initialiser localement
    if not db_valid:
        logger.info("Initialisation locale de la base de données...")
        from auth import init_db
        init_db()
        db_valid = verify_db_integrity()
        logger.info(f"Base de données initialisée localement: {'Succès' if db_valid else 'Échec'}")
    
    # Boucle principale
    try:
        while True:
            time.sleep(60)  # Check toutes les minutes
            if os.path.exists(DB_PATH):
                current_hash = calculate_file_hash(DB_PATH)
                logger.info(f"Vérification périodique de la base de données: {current_hash}")
            else:
                logger.error("Base de données absente lors de la vérification périodique")
    except Exception as e:
        logger.error(f"Erreur dans la boucle principale: {e}")
    
    # 4. Vérifier si une sauvegarde est disponible en cas d'échec
    if not db_valid and os.path.exists(f"{DB_PATH}.backup"):
        logger.warning("Restauration depuis la sauvegarde locale...")
        shutil.copy2(f"{DB_PATH}.backup", DB_PATH)
        if verify_db_integrity():
            logger.info("Restauration depuis la sauvegarde réussie.")
            upload_file_to_github()
    
    # Boucle de surveillance et sauvegarde
    last_upload_time = time.time()
    last_db_hash = calculate_file_hash(DB_PATH)
    
    while True:
        try:
            current_time = time.time()
            current_hash = calculate_file_hash(DB_PATH)
            
            # Vérifier si la DB a été modifiée et si l'intervalle de temps est écoulé
            time_elapsed = current_time - last_upload_time > BACKUP_INTERVAL
            hash_changed = current_hash != last_db_hash
            
            if (hash_changed or time_elapsed) and verify_db_integrity():
                logger.info("Modifications détectées ou délai écoulé, sauvegarde en cours...")
                if upload_file_to_github():
                    last_upload_time = current_time
                    last_db_hash = current_hash
            
            # Attendre avant la prochaine vérification
            time.sleep(60)  # Vérifier toutes les minutes
            
        except Exception as e:
            logger.error(f"Erreur dans la boucle de persistance: {e}")
            time.sleep(300)  # En cas d'erreur, attendre 5 minutes
