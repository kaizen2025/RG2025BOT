import requests
from bs4 import BeautifulSoup
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timedelta
import logging
import telebot
import re
import os
import random
import json
import socket
import ssl
from dotenv import load_dotenv
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import pyautogui  # Pour simulation de souris
import io
import base64
from PIL import Image

# Remplacement de webdriver-manager par chromedriver-autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import chromedriver_autoinstaller  # Nouveau!
from selenium.webdriver.chrome.service import Service
import cloudscraper
from lxml import html
from concurrent.futures import ThreadPoolExecutor, as_completed

# Circuit Breaker pattern
class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=300):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker for {self.name} changed to OPEN")
    
    def record_success(self):
        if self.state == "HALF-OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            logger.info(f"Circuit breaker for {self.name} changed to CLOSED")
        elif self.state == "CLOSED":
            self.failure_count = 0
    
    def allow_request(self):
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            elapsed = datetime.now() - self.last_failure_time
            if elapsed.total_seconds() > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info(f"Circuit breaker for {self.name} changed to HALF-OPEN")
                return True
            return False
        
        if self.state == "HALF-OPEN":
            return True
        
        return False

# Configuration du proxy rotatif
class ProxyManager:
    def __init__(self):
        self.proxy_service = os.getenv("PROXY_SERVICE", "none")  # brightdata, smartproxy, etc.
        self.proxy_username = os.getenv("PROXY_USERNAME", "")
        self.proxy_password = os.getenv("PROXY_PASSWORD", "")
        self.proxy_host = os.getenv("PROXY_HOST", "")
        self.proxy_port = os.getenv("PROXY_PORT", "")
        self.proxy_country = os.getenv("PROXY_COUNTRY", "fr")  # France par défaut
        self.proxies = []
        self.current_proxy_index = 0
        self.load_proxies()
    
    def load_proxies(self):
        """Charge les proxies depuis la configuration ou un fichier."""
        if self.proxy_service.lower() == "none":
            return
        
        if self.proxy_service.lower() == "file":
            # Charger les proxies depuis un fichier
            try:
                with open("proxies.txt", "r") as f:
                    self.proxies = [line.strip() for line in f if line.strip()]
                logger.info(f"Loaded {len(self.proxies)} proxies from file")
            except Exception as e:
                logger.error(f"Failed to load proxies from file: {e}")
        else:
            # Créer une URL de proxy pour BrightData ou SmartProxy
            proxy_url = ""
            if self.proxy_service.lower() == "brightdata":
                proxy_url = f"http://{self.proxy_username}-country-{self.proxy_country}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
            elif self.proxy_service.lower() == "smartproxy":
                proxy_url = f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
            
            if proxy_url:
                self.proxies.append(proxy_url)
                logger.info(f"Configured {self.proxy_service} proxy service")
    
    def get_next_proxy(self):
        """Retourne le prochain proxy à utiliser."""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    def get_proxy_dict(self):
        """Retourne un dictionnaire de proxies pour requests."""
        proxy = self.get_next_proxy()
        if not proxy:
            return {}
        
        return {
            "http": proxy,
            "https": proxy
        }
    
    def get_selenium_proxy(self):
        """Retourne un objet Proxy pour Selenium."""
        proxy_str = self.get_next_proxy()
        if not proxy_str:
            return None
        
        from selenium.webdriver.common.proxy import Proxy, ProxyType
        proxy = Proxy()
        proxy.proxy_type = ProxyType.MANUAL
        if proxy_str.startswith("http://"):
            proxy_str = proxy_str[7:]
        elif proxy_str.startswith("https://"):
            proxy_str = proxy_str[8:]
        
        proxy.http_proxy = proxy_str
        proxy.ssl_proxy = proxy_str
        return proxy

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_roland_garros.log", mode='a')
    ]
)

# Logger personnalisé
logger = logging.getLogger("RolandGarrosBot")

# Récupérer les variables d'environnement avec des valeurs par défaut
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

# Configuration pour Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
UTILISER_TELEGRAM = True if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID else False
TELEPHONE = os.getenv("TELEPHONE", "0608815968")

# Auto-réservation
AUTO_RESERVATION = os.getenv("AUTO_RESERVATION", "False").lower() in ["true", "1", "yes", "oui"]
RESERVATION_EMAIL = os.getenv("RESERVATION_EMAIL", "")
RESERVATION_PASSWORD = os.getenv("RESERVATION_PASSWORD", "")
RESERVATION_NOM = os.getenv("RESERVATION_NOM", "")
RESERVATION_PRENOM = os.getenv("RESERVATION_PRENOM", "")
RESERVATION_TELEPHONE = os.getenv("RESERVATION_TELEPHONE", "")
RESERVATION_MAX_PRIX = float(os.getenv("RESERVATION_MAX_PRIX", "1000"))

# Configuration des temps d'attente et retries
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]
INTERVALLE_VERIFICATION_MIN = int(os.getenv("INTERVALLE_MIN", "540"))  # 9 minutes par défaut
INTERVALLE_VERIFICATION_MAX = int(os.getenv("INTERVALLE_MAX", "660"))  # 11 minutes par défaut
INTERVALLE_RETRY = 30  # 30 secondes entre les tentatives en cas d'erreur

# Rotation des User-Agents pour éviter la détection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36 Edg/92.0.902.55',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
]

# Liste améliorée des sites à surveiller avec des sélecteurs CSS et URLs alternatives
SITES_AMELIORES = [
    {
        "nom": "Site Officiel Roland-Garros",
        "url": "https://www.rolandgarros.com/fr-fr/billetterie",
        "urls_alt": [
            "https://www.rolandgarros.com/en-us/tickets",
            "https://tickets.rolandgarros.com/fr",
            "https://www.rolandgarros.com/fr-fr/programme-et-billetterie"
        ],
        "type": "officiel",
        "priorité": 1,
        "selectors": {
            "calendrier": ".datepicker-days, .calendar, .calendar-container",
            "date_items": ".day, .date-item, [data-date]",
            "achat_buttons": ".btn-purchase, .buy-btn, .booking-btn, a[href*='ticket']",
            "disponibilite": ".available, .green, .bookable, .in-stock"
        },
        "mots_cles_additionnels": ["billets finales", "week-end final", "derniers jours"],
        "deeplinks": [
            "https://www.rolandgarros.com/fr-fr/billetterie?date=2025-05-31",
            "https://tickets.rolandgarros.com/fr/selection/event/seat?perfId=10016663&ot=0"
        ],
        "retry_config": {"max_retries": 5, "backoff_factor": 2}
    },
    {
        "nom": "Fnac Billetterie",
        "url": "https://www.fnacspectacles.com/place-spectacle/sport/tennis/roland-garros/",
        "urls_alt": [
            "https://www.fnacspectacles.com/recherche/?q=roland+garros",
            "https://www.fnacspectacles.com/place-spectacle/manifestation/Tennis-ROLAND-GARROS-2025-RG2025.htm"
        ],
        "type": "revendeur_officiel",
        "priorité": 2,
        "selectors": {
            "liste_events": ".events-list, .event-card, .event-item",
            "date_items": ".event-date, .date, .datetime",
            "prix": ".price, .tarif, .amount",
            "disponibilite": ".availability, .status, .stock-status"
        },
        "anti_bot_protection": True,
        "deeplinks": [
            "https://www.fnacspectacles.com/place-spectacle/manifestation/Tennis-ROLAND-GARROS-31-MAI-2025-RG31MAI.htm"
        ],
        "retry_config": {"max_retries": 3, "backoff_factor": 3}
    },
    {
        "nom": "Viagogo",
        "url": "https://www.viagogo.fr/Billets-Sport/Tennis/Roland-Garros-Internationaux-de-France-de-Tennis-Billets",
        "urls_alt": [
            "https://www.viagogo.fr/Billets-Sport/Tennis/Roland-Garros-Billets",
            "https://www.viagogo.fr/Sport/Tennis/Roland+Garros+Tickets"
        ],
        "type": "revente",
        "priorité": 3,
        "selectors": {
            "liste_billets": ".ticket-list, .listing-items, .search-results",
            "date_items": ".event-date, .date-info, .datetime",
            "prix": ".price, .amount, .ticket-price",
            "disponibilite": ".available-tickets"
        },
        "anti_bot_protection": True,
        "headers_specifiques": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "fr-FR,fr;q=0.8,en-US;q=0.5,en;q=0.3",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        },
        "deeplinks": [
            "https://www.viagogo.fr/Billets-Sport/Tennis/Roland-Garros-Internationaux-de-France-de-Tennis-Billets/E-151246271"
        ],
        "retry_config": {"max_retries": 2, "backoff_factor": 5}
    },
    {
        "nom": "Ticketmaster",
        "url": "https://www.ticketmaster.fr/fr/resultat?ipSearch=roland+garros",
        "urls_alt": [
            "https://www.ticketmaster.fr/fr/manifestation/roland-garros-2025-billet/idmanif/532125",
            "https://www.ticketmaster.fr/fr/manifestation/roland-garros-billet/idmanif/5ROLAND25"
        ],
        "type": "revendeur_officiel",
        "priorité": 2,
        "selectors": {
            "liste_events": ".event-list, .search-results, .events-container",
            "date_items": ".event-date, .date, [data-date]",
            "prix": ".price, .amount, .ticket-price",
            "disponibilite": ".availability, .status, .tickets-available"
        },
        "api_url": "https://www.ticketmaster.fr/api/v1/events/search?q=roland%20garros",
        "deeplinks": [
            "https://www.ticketmaster.fr/fr/manifestation/roland-garros-2025-billet/idmanif/532125/31-mai"
        ],
        "retry_config": {"max_retries": 4, "backoff_factor": 2}
    },
    {
        "nom": "StubHub",
        "url": "https://www.stubhub.fr/roland-garros-billets/ca6873/",
        "urls_alt": [
            "https://www.stubhub.fr/billets-roland-garros/ca6873/",
            "https://www.stubhub.fr/search/?q=roland+garros"
        ],
        "type": "revente",
        "priorité": 3,
        "selectors": {
            "liste_events": ".event-listing, .events-list",
            "date_items": ".event-date, .date-display",
            "prix": ".price, .amount",
            "disponibilite": ".availability, .ticket-count"
        },
        "anti_bot_protection": True,
        "deeplinks": [
            "https://www.stubhub.fr/billets-roland-garros-paris-31-5-2025/ev6873/"
        ],
        "retry_config": {"max_retries": 2, "backoff_factor": 4}
    },
    {
        "nom": "Billetréduc",
        "url": "https://www.billetreduc.com/recherche.htm?q=roland+garros",
        "urls_alt": [
            "https://www.billetreduc.com/sport/",
            "https://www.billetreduc.com/tennis/"
        ],
        "type": "reduction",
        "priorité": 3,
        "retry_config": {"max_retries": 3, "backoff_factor": 2}
    },
    {
        "nom": "FFT Billetterie",
        "url": "https://tickets.fft.fr/catalogue/roland-garros",
        "urls_alt": [
            "https://tickets.fft.fr/fr/",
            "https://tickets.fft.fr/catalogue/roland-garros-2025"
        ],
        "type": "officiel",
        "priorité": 1,
        "selectors": {
            "calendrier": ".calendar, .date-picker, .dates-container",
            "date_items": ".date, .day, [data-date]",
            "achat_buttons": ".buy-button, .add-to-cart, .book-now",
            "disponibilite": ".available, .in-stock, .bookable"
        },
        "ajax_api": "https://tickets.fft.fr/api/availability/dates?event=roland-garros",
        "headers_specifiques": {
            "X-Requested-With": "XMLHttpRequest"
        },
        "deeplinks": [
            "https://tickets.fft.fr/catalogue/roland-garros-2025?date=2025-05-31",
            "https://tickets.fft.fr/selection/event/date?productId=10162665"
        ],
        "retry_config": {"max_retries": 5, "backoff_factor": 2}
    },
    {
        "nom": "Rakuten Billets",
        "url": "https://fr.shopping.rakuten.com/event/roland-garros",
        "urls_alt": [
            "https://fr.shopping.rakuten.com/search/roland+garros+billets",
            "https://fr.shopping.rakuten.com/category/13020102/tennis-tickets"
        ],
        "type": "revente",
        "priorité": 3,
        "selectors": {
            "liste_billets": ".listing, .event-tickets",
            "date_items": ".event-date, .ticket-date",
            "prix": ".price, .ticket-price",
            "disponibilite": ".available, .status"
        },
        "mots_cles_additionnels": ["mai 2025", "31/05", "samedi"],
        "deeplinks": [
            "https://fr.shopping.rakuten.com/offer/buy/9021334815/"
        ],
        "retry_config": {"max_retries": 3, "backoff_factor": 2}
    },
    {
        "nom": "Seetickets",
        "url": "https://www.seetickets.com/fr/search?q=roland+garros",
        "urls_alt": [
            "https://www.seetickets.com/fr/sport/tennis",
            "https://www.seetickets.com/fr/event/roland-garros-2025"
        ],
        "type": "revendeur_officiel",
        "priorité": 3,
        "selectors": {
            "liste_events": ".search-results, .events-list",
            "date_items": ".event-date, .date",
            "prix": ".price, .amount",
            "disponibilite": ".status, .availability"
        },
        "deeplinks": [
            "https://www.seetickets.com/fr/event/roland-garros-2025-samedi-31-mai/123456"
        ],
        "retry_config": {"max_retries": 3, "backoff_factor": 2}
    },
    {
        "nom": "Eventim",
        "url": "https://www.eventim.fr/search/?affiliate=FES&searchterm=roland+garros",
        "urls_alt": [
            "https://www.eventim.fr/event/roland-garros-2025-stade-roland-garros-15265431/",
            "https://www.eventim.fr/sport/tennis/"
        ],
        "type": "revendeur_officiel",
        "priorité": 3,
        "selectors": {
            "liste_events": ".eventlist, .search-results",
            "date_items": ".date, .event-date",
            "prix": ".price, .amount",
            "disponibilite": ".availability, .status"
        },
        "deeplinks": [
            "https://www.eventim.fr/event/roland-garros-2025-31-mai-stade-roland-garros-15265431-31-05/"
        ],
        "retry_config": {"max_retries": 3, "backoff_factor": 2}
    }
]

# Pour la rétrocompatibilité, on conserve la variable SITES originale
SITES = SITES_AMELIORES

DATE_CIBLE = "31 mai 2025"  # La date qui vous intéresse
JOUR_SEMAINE_CIBLE = "samedi"  # Le jour de la semaine correspondant au 31 mai 2025

# Configuration des vérifications
MOTS_CLES = [
    "31 mai", "disponible", "billetterie", "vente", "nouvelle vente", 
    "samedi 31", "31/05", "31/05/2025", "dernier jour", "phase finale",
    "places", "billets disponibles", "court", "tribune", "acheter"
]

# Mots-clés spécifiques pour les sites de revente
MOTS_CLES_REVENTE = [
    "roland garros 31 mai", "31 mai 2025", "samedi 31 mai",
    "roland garros weekend", "derniers jours", "demi-finales",
    "billet disponible", "ticket disponible", "disponibilités"
]

# Circuit breakers pour les sites
circuit_breakers = {}

# Initialiser le gestionnaire de proxy
proxy_manager = ProxyManager()

# Fonction pour retarder l'exécution de manière aléatoire et simuler un comportement humain
def attendre_aleatoire(min_sec=2, max_sec=5):
    """Attend un temps aléatoire et peut simuler une activité de souris."""
    # Attendre un temps aléatoire
    duree = random.uniform(min_sec, max_sec)
    
    # 20% de chance d'exécuter un mouvement de souris (si pyautogui est disponible et en environnement graphique)
    if random.random() < 0.2 and os.getenv("SIMULATE_MOUSE", "False").lower() in ["true", "1", "yes", "oui"]:
        try:
            # Position actuelle
            current_x, current_y = pyautogui.position()
            
            # Nouvelle position aléatoire
            new_x = current_x + random.randint(-100, 100)
            new_y = current_y + random.randint(-100, 100)
            
            # Durée du mouvement
            move_duration = random.uniform(0.2, 0.8)
            
            # Déplacer progressivement la souris
            pyautogui.moveTo(new_x, new_y, duration=move_duration)
            
            # 30% de chance de faire un clic
            if random.random() < 0.3:
                pyautogui.click()
                logger.debug("Clic de souris simulé")
            
            # Revenir à la position initiale
            pyautogui.moveTo(current_x, current_y, duration=move_duration)
            
            logger.debug(f"Mouvement de souris simulé")
        except Exception as e:
            logger.debug(f"Impossible de simuler un mouvement de souris: {e}")
    
    time.sleep(duree)
    return duree

# Créer une session HTTP réutilisable avec retry
def creer_session(site_info=None):
    """Crée une session HTTP avec des paramètres de retry configurables par site."""
    session = requests.Session()
    
    # Utiliser la configuration de retry spécifique au site si disponible
    retry_config = site_info.get("retry_config", {}) if site_info else {}
    max_retries = retry_config.get("max_retries", MAX_RETRIES)
    backoff_factor = retry_config.get("backoff_factor", RETRY_BACKOFF_FACTOR)
    
    # Configurer le retry
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=RETRY_STATUS_FORCELIST,
        allowed_methods=["GET", "HEAD", "OPTIONS"]
    )
    
    # Appliquer la stratégie de retry à la session
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Appliquer le proxy si configuré
    proxies = proxy_manager.get_proxy_dict()
    if proxies:
        session.proxies.update(proxies)
    
    return session

def obtenir_user_agent():
    """Renvoie un User-Agent aléatoire."""
    return random.choice(USER_AGENTS)

def envoyer_email(sujet, message, screenshots=None):
    """Envoie un email de notification avec des screenshots optionnels."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
        logger.warning("Configuration email incomplète, notification email non envoyée")
        return False
    
    try:
        context = ssl.create_default_context()
        
        with smtplib.SMTP('smtp.gmail.com', 587) as serveur:
            serveur.ehlo()
            serveur.starttls(context=context)
            serveur.ehlo()
            serveur.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            
            # Créer un email multipart
            msg = MIMEMultipart()
            msg['Subject'] = sujet
            msg['From'] = EMAIL_ADDRESS
            msg['To'] = EMAIL_RECIPIENT
            
            # Ajouter le message texte
            msg.attach(MIMEText(message, 'html'))
            
            # Ajouter les screenshots si présents
            if screenshots:
                for i, screenshot in enumerate(screenshots):
                    try:
                        img_data = base64.b64decode(screenshot["data"])
                        img = MIMEImage(img_data)
                        img.add_header('Content-Disposition', f'attachment; filename="screenshot_{i+1}.png"')
                        img.add_header('Content-ID', f'<screenshot_{i+1}>')
                        msg.attach(img)
                        
                        # Ajouter une référence à l'image dans le HTML
                        image_ref = f'<p><img src="cid:screenshot_{i+1}" alt="Screenshot {i+1}" style="max-width:100%;border:1px solid #ccc;" /></p>'
                        message += image_ref
                    except Exception as e:
                        logger.error(f"Erreur lors de l'ajout du screenshot {i+1}: {e}")
            
            serveur.send_message(msg)
            
        logger.info(f"Email envoyé avec succès: {sujet}")
        return True
    except socket.gaierror as e:
        logger.error(f"Erreur de résolution DNS lors de l'envoi de l'email: {e}")
        return False
    except ssl.SSLError as e:
        logger.error(f"Erreur SSL lors de l'envoi de l'email: {e}")
        return False
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Erreur d'authentification SMTP: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"Erreur SMTP lors de l'envoi de l'email: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'envoi de l'email: {e}")
        return False

def envoyer_alerte_telegram(message, screenshots=None):
    """Envoie une notification via Telegram avec des screenshots optionnels."""
    if not UTILISER_TELEGRAM:
        logger.warning("Telegram n'est pas configuré, notification non envoyée")
        return False
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Token Telegram ou Chat ID manquant, notification non envoyée")
        return False
    
    try:
        # Réessayer plusieurs fois en cas d'erreur
        for tentative in range(MAX_RETRIES):
            try:
                bot = telebot.TeleBot(TELEGRAM_TOKEN)
                
                # Envoyer d'abord le message texte
                bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='Markdown')
                
                # Puis envoyer les screenshots si présents
                if screenshots:
                    for screenshot in screenshots:
                        try:
                            img_data = base64.b64decode(screenshot["data"])
                            caption = screenshot.get("caption", "Disponibilité détectée")
                            
                            # Créer un fichier temporaire pour l'image
                            with io.BytesIO(img_data) as img_stream:
                                bot.send_photo(TELEGRAM_CHAT_ID, img_stream, caption=caption)
                        except Exception as e:
                            logger.error(f"Erreur lors de l'envoi du screenshot: {e}")
                
                logger.info("Notification Telegram envoyée avec succès")
                return True
            except telebot.apihelper.ApiTelegramException as e:
                if "429" in str(e):  # Too Many Requests
                    if tentative < MAX_RETRIES - 1:
                        attente = (tentative + 1) * 5  # Attente exponentielle
                        logger.warning(f"Rate limit Telegram, nouvel essai dans {attente} secondes...")
                        time.sleep(attente)
                    else:
                        raise
                else:
                    raise
            except Exception as e:
                raise
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"Erreur API Telegram: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification Telegram: {e}")
        return False

def configurer_bot_telegram():
    """Configure le bot Telegram et renvoie des instructions pour le configurer."""
    instructions = f"""
    === CONFIGURATION DU BOT TELEGRAM ===
    
    Pour recevoir des alertes sur votre iPhone, suivez ces étapes:
    
    1. Ouvrez Telegram et recherchez BotFather (@BotFather)
    2. Envoyez la commande /newbot
    3. Suivez les instructions pour créer un nouveau bot
    4. BotFather vous donnera un TOKEN qui ressemble à: 123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
    5. Copiez ce TOKEN et remplacez "votre_token_bot_telegram" dans ce script
    
    6. Ensuite, ouvrez le bot que vous venez de créer et envoyez-lui un message (par exemple "Bonjour")
    7. Visitez https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates dans votre navigateur
       (remplacez <VOTRE_TOKEN> par le token obtenu précédemment)
    8. Cherchez "chat":{"id":XXXXXXXX dans la réponse - ce nombre est votre CHAT_ID
    9. Copiez ce CHAT_ID et remplacez "votre_chat_id" dans ce script
    
    10. Redémarrez le script, et vous recevrez maintenant des notifications sur votre iPhone via Telegram!
    
    Votre bot est configuré pour surveiller Roland-Garros pour le {DATE_CIBLE} et vous alerter dès qu'une disponibilité est détectée.
    """
    
    logger.info("Instructions de configuration du bot Telegram générées")
    return instructions

# Fonction pour prendre une capture d'écran avec Selenium
def prendre_screenshot(driver, highlight_elements=None):
    """
    Prend une capture d'écran avec Selenium et met en évidence des éléments.
    
    Args:
        driver: Instance du navigateur Selenium
        highlight_elements: Liste d'éléments à mettre en évidence
        
    Returns:
        str: Données de l'image encodées en base64
    """
    try:
        # Mettre en évidence les éléments
        original_styles = {}
        if highlight_elements:
            for element in highlight_elements:
                try:
                    # Sauvegarder le style original
                    original_style = element.get_attribute("style")
                    original_styles[element] = original_style
                    
                    # Appliquer une bordure rouge et un fond jaune
                    driver.execute_script(
                        "arguments[0].setAttribute('style', arguments[1]);",
                        element,
                        "border: 3px solid red; background-color: yellow; padding: 5px;"
                    )
                except Exception as e:
                    logger.error(f"Erreur lors de la mise en évidence d'un élément: {e}")
        
        # Prendre la capture d'écran
        screenshot = driver.get_screenshot_as_base64()
        
        # Restaurer les styles originaux
        for element, style in original_styles.items():
            try:
                if style:
                    driver.execute_script(
                        "arguments[0].setAttribute('style', arguments[1]);",
                        element,
                        style
                    )
                else:
                    driver.execute_script(
                        "arguments[0].removeAttribute('style');",
                        element
                    )
            except Exception as e:
                logger.error(f"Erreur lors de la restauration du style d'un élément: {e}")
        
        return screenshot
    except Exception as e:
        logger.error(f"Erreur lors de la prise de capture d'écran: {e}")
        return None

# Fonction pour initialiser le navigateur Chrome headless pour les sites avec protection anti-bot
# MISE À JOUR: Utilisation de chromedriver-autoinstaller et optimisations
def initialiser_navigateur():
    """Initialise et retourne une instance de navigateur Chrome en mode headless."""
    try:
        logger.info("Initialisation du navigateur headless pour les sites protégés")
        
        # Installation automatique du chromedriver
        chromedriver_autoinstaller.install()
        
        options = Options()
        options.add_argument("--headless=new")  # Nouvelle version du headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-automation")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Ajouts pour renforcer l'anti-détection
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--enable-javascript")
        options.add_argument("--lang=fr-FR")
        
        # Masquer que nous utilisons Selenium
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        # Ajouter un proxy si configuré
        proxy = proxy_manager.get_selenium_proxy()
        if proxy:
            options.proxy = proxy
        
        # Utilisation directe du chromedriver installé
        driver = webdriver.Chrome(options=options)
        
        # Modification des propriétés pour éviter la détection
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US', 'en']})")
        
        # Ajouter des délais aléatoires et des mouvements de souris
        attendre_aleatoire(1, 3)
        
        return driver
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du navigateur: {e}")
        return None

# Fonction pour tenter de réserver automatiquement un billet sur le site officiel
def tenter_reservation_automatique(url, driver=None):
    """
    Tente de réserver automatiquement des billets si disponibles.
    
    Args:
        url: URL directe vers la page de réservation
        driver: Instance du navigateur Selenium (optionnel)
        
    Returns:
        tuple: (succès, message)
    """
    if not AUTO_RESERVATION:
        logger.info("Auto-réservation désactivée, ignoré")
        return False, "Auto-réservation désactivée"
    
    if not RESERVATION_EMAIL or not RESERVATION_PASSWORD:
        logger.warning("Informations de connexion pour l'auto-réservation manquantes")
        return False, "Informations de connexion manquantes"
    
    logger.info(f"Tentative de réservation automatique sur {url}")
    
    fermer_driver = False
    try:
        # Initialiser un navigateur si non fourni
        if not driver:
            driver = initialiser_navigateur()
            fermer_driver = True
            
            if not driver:
                return False, "Impossible d'initialiser le navigateur pour la réservation"
        
        # Accéder à l'URL
        driver.get(url)
        attendre_aleatoire(2, 4)
        
        # Rechercher un formulaire de connexion ou des boutons d'achat
        if "rolandgarros.com" in url or "fft.fr" in url:
            # Site officiel Roland-Garros ou FFT
            try:
                # Vérifier si on doit se connecter d'abord
                login_buttons = driver.find_elements(By.CSS_SELECTOR, "a[href*='login'], a[href*='connexion'], button.login, .btn-login")
                
                if login_buttons:
                    logger.info("Tentative de connexion au compte utilisateur")
                    login_buttons[0].click()
                    attendre_aleatoire(2, 4)
                    
                    # Remplir les champs de connexion
                    email_field = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
                    )
                    email_field.send_keys(RESERVATION_EMAIL)
                    attendre_aleatoire(0.5, 1)
                    
                    password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
                    password_field.send_keys(RESERVATION_PASSWORD)
                    attendre_aleatoire(0.5, 1)
                    
                    # Cliquer sur le bouton de connexion
                    submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], .btn-submit, .btn-login")
                    submit_button.click()
                    attendre_aleatoire(3, 5)
                
                # Rechercher la date du 31 mai et cliquer dessus
                date_elements = driver.find_elements(By.CSS_SELECTOR, "[data-date='2025-05-31'], .calendar-day[data-value='2025-05-31'], .calendar-day:contains('31')")
                
                if date_elements:
                    logger.info("Date du 31 mai trouvée, tentative de sélection")
                    date_elements[0].click()
                    attendre_aleatoire(2, 4)
                
                # Rechercher les tickets disponibles
                ticket_elements = driver.find_elements(By.CSS_SELECTOR, ".ticket-item.available, .offer-item[data-available='true'], .category-available")
                
                if ticket_elements:
                    # Trouver le ticket le moins cher
                    best_ticket = None
                    lowest_price = float('inf')
                    
                    for ticket in ticket_elements:
                        try:
                            price_text = ticket.find_element(By.CSS_SELECTOR, ".price, .amount").text
                            price = float(re.search(r'(\d+[.,]?\d*)', price_text.replace(',', '.')).group(1))
                            
                            if price < lowest_price and price <= RESERVATION_MAX_PRIX:
                                lowest_price = price
                                best_ticket = ticket
                        except Exception:
                            continue
                    
                    if best_ticket:
                        logger.info(f"Ticket trouvé au prix de {lowest_price}€, tentative d'ajout au panier")
                        best_ticket.find_element(By.CSS_SELECTOR, "button.add-to-cart, .btn-buy, .btn-book").click()
                        attendre_aleatoire(2, 4)
                        
                        # Passer à la caisse
                        checkout_buttons = driver.find_elements(By.CSS_SELECTOR, ".btn-checkout, .proceed-to-checkout, a[href*='checkout']")
                        if checkout_buttons:
                            checkout_buttons[0].click()
                            attendre_aleatoire(2, 4)
                            
                            # Simuler le processus de paiement (jusqu'à un certain point)
                            logger.info("Procédure d'achat initiée, remplissage des informations")
                            
                            # Prendre une capture d'écran du panier
                            screenshot = prendre_screenshot(driver)
                            
                            # Notifier de la réservation en cours
                            message_notification = f"Réservation automatique initiée sur {url} pour un billet à {lowest_price}€. Veuillez finaliser le paiement manuellement!"
                            
                            envoyer_alerte_telegram(message_notification, [{"data": screenshot, "caption": "Panier de réservation"}])
                            envoyer_email(
                                "RÉSERVATION AUTOMATIQUE EN COURS - Roland-Garros",
                                message_notification,
                                [{"data": screenshot}]
                            )
                            
                            return True, f"Réservation initiée avec succès pour un billet à {lowest_price}€"
                        else:
                            return False, "Impossible de passer à la caisse"
                    else:
                        return False, "Aucun ticket disponible dans la limite de prix"
                else:
                    return False, "Aucun ticket disponible"
            
            except Exception as e:
                logger.error(f"Erreur lors de la tentative de réservation: {e}")
                return False, f"Erreur de réservation: {str(e)}"
        else:
            # Autres sites non supportés pour l'auto-réservation
            return False, "Auto-réservation non supportée pour ce site"
    
    except Exception as e:
        logger.error(f"Erreur générale lors de la tentative de réservation: {e}")
        return False, f"Erreur générale: {str(e)}"
    
    finally:
        # Fermer le navigateur si on l'a créé ici
        if fermer_driver and driver:
            try:
                driver.quit()
            except Exception:
                pass

# Fonction utilisant Selenium pour les sites avec protection anti-bot
def verifier_site_avec_selenium(site_info):
    """
    Vérifie un site à l'aide de Selenium pour contourner les protections anti-bot.
    
    Args:
        site_info (dict): Informations sur le site à vérifier
    
    Returns:
        tuple: (disponible, message, screenshots)
    """
    logger.info(f"Vérification de {site_info['nom']} avec Selenium (protection anti-bot)")
    
    driver = None
    screenshots = []
    elements_a_surligner = []
    
    # Circuit breaker
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    
    if not circuit_breakers[site_nom].allow_request():
        logger.warning(f"Circuit breaker ouvert pour {site_nom}, vérification ignorée")
        return False, f"Circuit breaker ouvert pour {site_nom} (trop d'erreurs récentes)", []
    
    try:
        driver = initialiser_navigateur()
        if not driver:
            circuit_breakers[site_nom].record_failure()
            return False, f"Impossible d'initialiser le navigateur pour {site_info['nom']}", []
        
        # Ajouter des cookies pour ressembler davantage à un utilisateur normal
        driver.get("https://www.google.com")
        attendre_aleatoire(1, 2)
        
        # Configurer les cookies
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        
        for name, value in cookies.items():
            driver.add_cookie({'name': name, 'value': value, 'domain': site_info['url'].split('/')[2]})
        
        # Accéder au site avec un délai aléatoire
        logger.info(f"Accès à {site_info['url']} via Selenium")
        driver.get(site_info['url'])
        
        # Attendre que la page se charge complètement
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Simuler un comportement humain: scroll progressif
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {i * 500});")
            attendre_aleatoire(0.5, 1.5)
        
        # Rechercher les éléments d'intérêt en utilisant les sélecteurs spécifiques au site
        selectors = site_info.get('selectors', {})
        mots_trouves = []
        score = 0
        disponible = False
        
        # Vérifier le contenu de la page pour les mots-clés
        contenu_page = driver.page_source.lower()
        date_trouvee = any(date_format in contenu_page for date_format in 
                           ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        
        # Vérifier les éléments de calendrier
        if 'calendrier' in selectors:
            try:
                calendriers = driver.find_elements(By.CSS_SELECTOR, selectors['calendrier'])
                for cal in calendriers:
                    cal_text = cal.text.lower()
                    if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                        score += 3
                        mots_trouves.append("calendrier avec 31 mai détecté")
                        elements_a_surligner.append(cal)
                        
                        # Vérifier si ce jour est marqué comme disponible
                        classes = cal.get_attribute("class")
                        if classes and any(c for c in ['available', 'bookable', 'in-stock'] if c in classes.lower()):
                            score += 3
                            mots_trouves.append("jour 31 mai marqué comme disponible")
                            disponible = True
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des calendriers: {e}")
        
        # Vérifier les éléments de date individuels
        if 'date_items' in selectors:
            try:
                dates = driver.find_elements(By.CSS_SELECTOR, selectors['date_items'])
                for date_elem in dates:
                    date_text = date_elem.text.lower()
                    if '31' in date_text and ('mai' in date_text or '05' in date_text or 'may' in date_text):
                        score += 2
                        mots_trouves.append("élément de date 31 mai détecté")
                        elements_a_surligner.append(date_elem)
                        
                        # Vérifier si cet élément est associé à une disponibilité
                        parent = date_elem.find_element(By.XPATH, "./..")
                        parent_html = parent.get_attribute('outerHTML').lower()
                        if any(term in parent_html for term in ['disponible', 'available', 'acheter', 'buy']):
                            score += 3
                            mots_trouves.append("date 31 mai associée à une disponibilité")
                            disponible = True
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des éléments de date: {e}")
        
        # Vérifier les boutons d'achat/réservation
        if 'achat_buttons' in selectors:
            try:
                boutons = driver.find_elements(By.CSS_SELECTOR, selectors['achat_buttons'])
                for bouton in boutons:
                    bouton_text = bouton.text.lower()
                    bouton_html = bouton.get_attribute('outerHTML').lower()
                    
                    if any(term in bouton_text for term in ['acheter', 'réserver', 'buy', 'book']):
                        score += 1
                        mots_trouves.append("bouton d'achat détecté")
                        
                        # Vérifier si le bouton est lié à la date cible
                        try:
                            parent = bouton.find_element(By.XPATH, "./ancestor::div[contains(@class, 'event') or contains(@class, 'ticket')]")
                            parent_text = parent.text.lower()
                            if '31 mai' in parent_text or '31/05' in parent_text:
                                score += 4
                                mots_trouves.append("bouton d'achat pour le 31 mai")
                                elements_a_surligner.append(bouton)
                                disponible = True
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des boutons d'achat: {e}")
        
        # Vérifier explicitement les indicateurs de disponibilité
        if 'disponibilite' in selectors:
            try:
                indicateurs = driver.find_elements(By.CSS_SELECTOR, selectors['disponibilite'])
                for ind in indicateurs:
                    ind_text = ind.text.lower()
                    ind_html = ind.get_attribute('outerHTML').lower()
                    
                    if any(term in ind_text for term in ['disponible', 'available', 'en stock']):
                        # Vérifier si cet indicateur est associé à la date cible
                        try:
                            parent = ind.find_element(By.XPATH, "./ancestor::div[contains(@class, 'event') or contains(@class, 'ticket')]")
                            parent_text = parent.text.lower()
                            if '31 mai' in parent_text or '31/05' in parent_text:
                                score += 5
                                mots_trouves.append("indicateur de disponibilité explicite pour le 31 mai")
                                elements_a_surligner.append(ind)
                                disponible = True
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des indicateurs de disponibilité: {e}")
        
        # Prendre une capture d'écran si disponible
        if disponible or score >= 5:
            screenshot_data = prendre_screenshot(driver, elements_a_surligner)
            if screenshot_data:
                caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                screenshots.append({"data": screenshot_data, "caption": caption})
                
                # Tenter une réservation automatique si elle est activée et que c'est un site officiel
                if disponible and AUTO_RESERVATION and site_info['type'] == 'officiel' and 'deeplinks' in site_info and site_info['deeplinks']:
                    # Utiliser un deeplink si disponible
                    deeplink = site_info['deeplinks'][0]
                    tenter_reservation_automatique(deeplink, driver)
        
        # Enregistrer le succès dans le circuit breaker
        circuit_breakers[site_nom].record_success()
        
        # Prendre une décision sur la disponibilité
        if disponible or score >= 7:
            details = ", ".join(mots_trouves)
            return True, f"Disponibilité détectée sur {site_info['nom']} (score: {score}/10) - Éléments trouvés: {details}", screenshots
        else:
            return False, f"Aucune disponibilité détectée sur {site_info['nom']} (score: {score}/10)", []
            
    except TimeoutException:
        circuit_breakers[site_nom].record_failure()
        logger.error(f"Timeout lors de l'accès à {site_info['nom']}")
        return False, f"Timeout lors de l'accès à {site_info['nom']}", []
    except WebDriverException as e:
        circuit_breakers[site_nom].record_failure()
        logger.error(f"Erreur Selenium sur {site_info['nom']}: {e}")
        return False, f"Erreur de navigation sur {site_info['nom']}: {str(e)}", []
    except Exception as e:
        circuit_breakers[site_nom].record_failure()
        logger.error(f"Erreur non gérée lors de la vérification de {site_info['nom']} avec Selenium: {e}")
        return False, f"Erreur lors de la vérification de {site_info['nom']}: {str(e)}", []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

# Fonction pour contourner CloudFlare et autres protections
def verifier_site_avec_cloudscraper(site_info):
    """
    Vérifie un site à l'aide de cloudscraper pour contourner les protections CloudFlare.
    
    Args:
        site_info (dict): Informations sur le site à vérifier
    
    Returns:
        tuple: (disponible, message, screenshots)
    """
    logger.info(f"Vérification de {site_info['nom']} avec CloudScraper")
    
    # Circuit breaker
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    
    if not circuit_breakers[site_nom].allow_request():
        logger.warning(f"Circuit breaker ouvert pour {site_nom}, vérification ignorée")
        return False, f"Circuit breaker ouvert pour {site_nom} (trop d'erreurs récentes)", []
    
    try:
        # Créer une session cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=5
        )
        
        # Ajouter des headers spécifiques si définis
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Referer': 'https://www.google.com/search?q=roland+garros+billets',
        }
        
        # Ajouter des headers spécifiques au site si définis
        if 'headers_specifiques' in site_info:
            headers.update(site_info['headers_specifiques'])
        
        # Ajouter des cookies pour simuler une session utilisateur
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        
        # Ajouter des proxies si configurés
        proxies = proxy_manager.get_proxy_dict()
        
        # Accéder au site
        logger.info(f"Accès à {site_info['url']} via CloudScraper")
        response = scraper.get(site_info['url'], headers=headers, cookies=cookies, proxies=proxies, timeout=30)
        
        # Délai aléatoire pour simuler un comportement humain
        attendre_aleatoire(1, 3)
        
        if response.status_code != 200:
            circuit_breakers[site_nom].record_failure()
            logger.warning(f"Erreur HTTP {response.status_code} sur {site_info['nom']}")
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}", []
        
        # Analyser la page HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        contenu_page = soup.get_text().lower()
        
        # Vérifier le contenu pour les mots-clés
        selectors = site_info.get('selectors', {})
        mots_trouves = []
        score = 0
        screenshots = []
        
        # Vérifier si la date est mentionnée
        date_trouvee = any(date_format in contenu_page for date_format in 
                          ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        
        # Vérifier les mots clés additionnels spécifiques au site
        mots_cles_additionnels = site_info.get('mots_cles_additionnels', [])
        for mot in mots_cles_additionnels:
            if mot.lower() in contenu_page:
                mots_trouves.append(f"mot-clé '{mot}' trouvé")
                score += 1
        
        # Vérifier les éléments de calendrier
        if 'calendrier' in selectors:
            calendriers = soup.select(selectors['calendrier'])
            for cal in calendriers:
                cal_text = cal.get_text().lower()
                if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                    score += 3
                    mots_trouves.append("calendrier avec 31 mai détecté")
                    
                    # Vérifier si ce jour est marqué comme disponible
                    classes = cal.get('class', [])
                    if any(c for c in classes if 'available' in c or 'bookable' in c or 'in-stock' in c):
                        score += 3
                        mots_trouves.append("jour 31 mai marqué comme disponible")
        
        # Vérifier les éléments de disponibilité
        if 'disponibilite' in selectors:
            disponibilites = soup.select(selectors['disponibilite'])
            for disp in disponibilites:
                disp_text = disp.get_text().lower()
                if any(term in disp_text for term in ['disponible', 'available', 'en stock']):
                    # Chercher si cet élément est associé à la date cible
                    parent = disp.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 5
                            mots_trouves.append("disponibilité explicite pour le 31 mai")
        
        # Vérifier les API associées si définies
        if 'ajax_api' in site_info:
            try:
                api_url = site_info['ajax_api']
                api_headers = headers.copy()
                api_headers['X-Requested-With'] = 'XMLHttpRequest'
                
                api_response = scraper.get(api_url, headers=api_headers, cookies=cookies, proxies=proxies, timeout=20)
                
                if api_response.status_code == 200:
                    try:
                        api_data = api_response.json()
                        
                        # Analyser les données JSON pour trouver des disponibilités
                        if isinstance(api_data, dict):
                            for key, value in api_data.items():
                                if '31-05' in key or '31/05' in key or '2025-05-31' in key:
                                    available = value.get('available', value.get('disponible', False))
                                    if available:
                                        score += 7
                                        mots_trouves.append("API indique disponibilité pour le 31 mai")
                        elif isinstance(api_data, list):
                            for item in api_data:
                                if isinstance(item, dict):
                                    date_str = str(item.get('date', ''))
                                    if '31-05' in date_str or '31/05' in date_str or '2025-05-31' in date_str:
                                        available = item.get('available', item.get('disponible', False))
                                        if available:
                                            score += 7
                                            mots_trouves.append("API indique disponibilité pour le 31 mai")
                    except Exception as e:
                        logger.warning(f"Erreur lors de l'analyse des données API: {e}")
            except Exception as e:
                logger.warning(f"Erreur lors de l'accès à l'API: {e}")
        
        # Si on est sur un site officiel et qu'on a détecté une disponibilité,
        # essayer de prendre une capture d'écran avec Selenium
        if score >= 5 and site_info['type'] in ['officiel', 'revendeur_officiel'] and 'deeplinks' in site_info:
            try:
                logger.info(f"Détection potentielle sur {site_info['nom']}, tentative de capture d'écran")
                
                # Utiliser Selenium pour capturer l'écran
                driver = initialiser_navigateur()
                if driver:
                    try:
                        # Accéder directement au deeplink si disponible
                        deeplink = site_info['deeplinks'][0]
                        driver.get(deeplink)
                        
                        # Attendre le chargement
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                        
                        # Prendre une capture d'écran
                        screenshot_data = prendre_screenshot(driver)
                        if screenshot_data:
                            caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                            screenshots.append({"data": screenshot_data, "caption": caption})
                        
                        # Tenter une réservation automatique si activé
                        if AUTO_RESERVATION and site_info['type'] == 'officiel':
                            tenter_reservation_automatique(deeplink, driver)
                    finally:
                        driver.quit()
            except Exception as e:
                logger.error(f"Erreur lors de la capture d'écran: {e}")
        
        # Enregistrer le succès dans le circuit breaker
        circuit_breakers[site_nom].record_success()
        
        # Prendre une décision sur la disponibilité
        seuil_detection = 5
        if score >= seuil_detection:
            details = ", ".join(mots_trouves)
            return True, f"Disponibilité détectée sur {site_info['nom']} (score: {score}/10) - Éléments trouvés: {details}", screenshots
        else:
            return False, f"Aucune disponibilité détectée sur {site_info['nom']} (score: {score}/10)", []
            
    except Exception as e:
        circuit_breakers[site_nom].record_failure()
        logger.error(f"Erreur non gérée lors de la vérification de {site_info['nom']} avec CloudScraper: {e}")
        return False, f"Erreur lors de la vérification de {site_info['nom']}: {str(e)}", []

# Fonction pour analyser un objet JSON à la recherche de disponibilités
def analyser_json_pour_disponibilite(json_data):
    """
    Analyse un objet JSON pour y trouver des indices de disponibilité pour le 31 mai.
    
    Args:
        json_data: Données JSON à analyser
    
    Returns:
        tuple: (score, mots_trouvés)
    """
    score = 0
    mots_trouves = []
    
    # Fonction récursive pour explorer l'objet JSON
    def explorer_json(obj, chemin=""):
        nonlocal score, mots_trouves
        
        if isinstance(obj, dict):
            # Rechercher d'abord si cet objet contient à la fois date et disponibilité
            date_cible_trouvee = False
            disponibilite_trouvee = False
            
            for key, value in obj.items():
                key_lower = str(key).lower()
                
                # Vérifier la date
                if 'date' in key_lower or 'jour' in key_lower or 'day' in key_lower:
                    str_value = str(value).lower()
                    if '31/05' in str_value or '31-05' in str_value or '31 mai' in str_value or '2025-05-31' in str_value:
                        date_cible_trouvee = True
                        mots_trouves.append(f"date 31 mai trouvée dans JSON à {chemin}.{key}")
                
                # Vérifier la disponibilité
                elif ('disponible' in key_lower or 'available' in key_lower or 'status' in key_lower 
                      or 'bookable' in key_lower or 'stock' in key_lower):
                    str_value = str(value).lower()
                    if str_value in ['true', '1', 'yes', 'disponible', 'available', 'en stock', 'in stock']:
                        disponibilite_trouvee = True
                        mots_trouves.append(f"disponibilité trouvée dans JSON à {chemin}.{key}")
            
            # Si les deux sont trouvés dans le même objet, score élevé
            if date_cible_trouvee and disponibilite_trouvee:
                score += 5
                mots_trouves.append(f"date 31 mai ET disponibilité trouvées dans le même objet JSON")
            
            # Explorer récursivement
            for key, value in obj.items():
                explorer_json(value, f"{chemin}.{key}" if chemin else key)
                
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                explorer_json(item, f"{chemin}[{i}]")
    
    explorer_json(json_data)
    return score, mots_trouves

# Nouvelle fonction améliorée qui remplace verifier_site
# MISE À JOUR: Priorité à cloudscraper au lieu de Selenium
def verifier_site_ameliore(site_info):
    """
    Version améliorée de la fonction verifier_site qui utilise principalement cloudscraper.
    
    Args:
        site_info (dict): Informations sur le site à vérifier
    
    Returns:
        tuple: (disponible, message, screenshots)
    """
    # Réessayer avec des URLs alternatives si nécessaire
    urls_a_essayer = [site_info['url']] + site_info.get('urls_alt', [])
    
    # Initialiser les variables de résultat
    disponible = False
    message = ""
    screenshots = []
    
    # Circuit breaker
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    
    if not circuit_breakers[site_nom].allow_request():
        logger.warning(f"Circuit breaker ouvert pour {site_nom}, vérification ignorée")
        return False, f"Circuit breaker ouvert pour {site_nom} (trop d'erreurs récentes)", []
    
    # Déterminer la meilleure méthode pour ce site
    for url_index, url in enumerate(urls_a_essayer):
        if url_index > 0:
            logger.info(f"Tentative avec URL alternative {url_index} pour {site_info['nom']}")
            
            # Mise à jour temporaire de l'URL
            site_info_temp = site_info.copy()
            site_info_temp['url'] = url
        else:
            site_info_temp = site_info
        
        try:
            # CHANGEMENT: Essayer d'abord cloudscraper pour tous les sites avec protection anti-bot
            if site_info.get('anti_bot_protection', False) or any(domain in site_info['url'] for domain in ['viagogo', 'stubhub', 'ticketswap']):
                disponible, message, screenshots = verifier_site_avec_cloudscraper(site_info_temp)
                if disponible or "Erreur" not in message:
                    break
                
                # Si cloudscraper échoue, essayer Selenium en dernier recours
                if "Erreur" in message and url_index == len(urls_a_essayer) - 1:
                    logger.warning(f"Échec avec CloudScraper pour {site_info['nom']}, tentative avec Selenium")
                    disponible, message, selenium_screenshots = verifier_site_avec_selenium(site_info)
                    if selenium_screenshots:
                        screenshots.extend(selenium_screenshots)
                    break
            else:
                # Pour les sites sans protection, utiliser une approche standard
                dispo_tmp, msg_tmp, screenshots_tmp = verifier_site_standard(site_info_temp)
                disponible = dispo_tmp
                message = msg_tmp
                screenshots = screenshots_tmp
                if disponible or "Erreur" not in message:
                    break
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {site_info['nom']} avec l'URL {url}: {e}")
            message = f"Erreur lors de la vérification: {str(e)}"
            # Continuer avec la prochaine URL alternative
    
    if "Erreur" in message:
        circuit_breakers[site_nom].record_failure()
    else:
        circuit_breakers[site_nom].record_success()
    
    return disponible, message, screenshots

# Fonction standard pour les sites sans protection spéciale
def verifier_site_standard(site_info):
    """
    Vérifie un site standard sans protection particulière.
    
    Args:
        site_info (dict): Informations sur le site à vérifier
    
    Returns:
        tuple: (disponible, message, screenshots)
    """
    try:
        logger.info(f"Vérification de {site_info['nom']}...")
        
        # Créer une session avec des headers réalistes
        session = creer_session(site_info)
        
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Referer': 'https://www.google.com/search?q=roland+garros+billets',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'sec-ch-ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Connection': 'keep-alive'
        }
        
        # Ajouter des headers spécifiques au site si définis
        if 'headers_specifiques' in site_info:
            headers.update(site_info['headers_specifiques'])
        
        # Cookies pour simuler une session utilisateur
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        
        # Faire la requête au site avec un délai aléatoire
        logger.info(f"Accès à {site_info['url']}")
        response = session.get(site_info['url'], headers=headers, cookies=cookies, timeout=30)
        attendre_aleatoire(1, 3)
        
        if response.status_code != 200:
            logger.warning(f"Erreur HTTP {response.status_code} sur {site_info['nom']}")
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}", []
        
        # Analyser la page HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        lxml_tree = html.fromstring(response.content)
        contenu_page = soup.get_text().lower()
        
        # Initialiser la détection
        mots_trouves = []
        score = 0
        screenshots = []
        
        # Vérifier si la date est mentionnée
        date_trouvee = any(date_format in contenu_page for date_format in 
                          ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        
        # Vérifier les sélecteurs spécifiques au site
        selectors = site_info.get('selectors', {})
        
        # Vérifier les éléments de calendrier
        if 'calendrier' in selectors:
            calendriers = soup.select(selectors['calendrier'])
            for cal in calendriers:
                cal_text = cal.get_text().lower()
                if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                    score += 3
                    mots_trouves.append("calendrier avec 31 mai détecté")
                    
                    # Vérifier si ce jour est marqué comme disponible
                    classes = cal.get('class', [])
                    if any(c for c in classes if 'available' in c or 'bookable' in c or 'in-stock' in c):
                        score += 3
                        mots_trouves.append("jour 31 mai marqué comme disponible")
        
        # Vérifier les éléments de date
        if 'date_items' in selectors:
            dates = soup.select(selectors['date_items'])
            for date_elem in dates:
                date_text = date_elem.get_text().lower()
                if '31' in date_text and ('mai' in date_text or '05' in date_text):
                    score += 2
                    mots_trouves.append("élément de date 31 mai détecté")
                    
                    # Vérifier si cet élément est associé à une disponibilité
                    parent = date_elem.find_parent()
                    if parent:
                        parent_html = str(parent).lower()
                        if any(term in parent_html for term in ['disponible', 'available', 'acheter', 'buy']):
                            score += 3
                            mots_trouves.append("date 31 mai associée à une disponibilité")
        
        # Vérifier les boutons d'achat
        if 'achat_buttons' in selectors:
            boutons = soup.select(selectors['achat_buttons'])
            for bouton in boutons:
                bouton_text = bouton.get_text().lower()
                
                if any(term in bouton_text for term in ['acheter', 'réserver', 'buy', 'book']):
                    score += 1
                    mots_trouves.append("bouton d'achat détecté")
                    
                    # Vérifier si le bouton est lié à la date cible
                    parent = bouton.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 4
                            mots_trouves.append("bouton d'achat pour le 31 mai")
        
        # Vérifier les indicateurs de disponibilité
        if 'disponibilite' in selectors:
            disponibilites = soup.select(selectors['disponibilite'])
            for disp in disponibilites:
                disp_text = disp.get_text().lower()
                if any(term in disp_text for term in ['disponible', 'available', 'en stock']):
                    # Chercher si cet élément est associé à la date cible
                    parent = disp.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 5
                            mots_trouves.append("disponibilité explicite pour le 31 mai")
        
        # Vérifier les mots clés additionnels
        mots_cles_additionnels = site_info.get('mots_cles_additionnels', [])
        for mot in mots_cles_additionnels:
            if mot.lower() in contenu_page:
                mots_trouves.append(f"mot-clé '{mot}' trouvé")
                score += 1
        
        # Vérifier les API associées si définies
        if 'api_url' in site_info:
            try:
                api_url = site_info['api_url']
                api_headers = headers.copy()
                api_headers['Accept'] = 'application/json'
                
                api_response = session.get(api_url, headers=api_headers, cookies=cookies, timeout=20)
                
                if api_response.status_code == 200:
                    try:
                        api_data = api_response.json()
                        
                        # Analyser les données JSON
                        json_score, json_mots = analyser_json_pour_disponibilite(api_data)
                        score += json_score
                        mots_trouves.extend(json_mots)
                    except Exception as e:
                        logger.warning(f"Erreur lors de l'analyse des données API: {e}")
            except Exception as e:
                logger.warning(f"Erreur lors de l'accès à l'API: {e}")
        
        # Rechercher des données JSON dans le HTML
        scripts = soup.find_all('script')
        for script in scripts:
            script_content = script.string if script.string else ''
            if script_content:
                # Rechercher des objets JSON dans le script
                json_matches = re.findall(r'({[^{]*?"date.*?})', script_content)
                for json_str in json_matches:
                    try:
                        # Nettoyer et parser le JSON
                        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_]+):', r'\1"\2":', json_str)
                        json_data = json.loads(json_str)
                        
                        if isinstance(json_data, dict):
                            date_value = None
                            for k, v in json_data.items():
                                if 'date' in k.lower():
                                    date_value = str(v).lower()
                            
                            if date_value and ('31/05' in date_value or '31-05' in date_value or '31 mai' in date_value):
                                # Vérifier la disponibilité
                                for k, v in json_data.items():
                                    if 'disponible' in k.lower() or 'available' in k.lower() or 'status' in k.lower():
                                        if str(v).lower() in ['true', '1', 'yes', 'disponible', 'available']:
                                            score += 4
                                            mots_trouves.append("données JSON indiquant disponibilité pour le 31 mai")
                    except Exception:
                        pass
        
        # Utiliser XPath pour des sélecteurs plus précis avec lxml
        try:
            # Recherche de disponibilité par XPath
            xpath_disponibilite = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//*[contains(@class, 'available') or contains(@class, 'dispo')]"
            elements_disponibles = lxml_tree.xpath(xpath_disponibilite)
            
            if elements_disponibles:
                score += 4
                mots_trouves.append(f"{len(elements_disponibles)} éléments de disponibilité trouvés par XPath")
            
            # Recherche de boutons d'achat près de la date
            xpath_boutons = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//button[contains(text(), 'Acheter') or contains(text(), 'Réserver') or contains(text(), 'Buy')]"
            boutons_achat = lxml_tree.xpath(xpath_boutons)
            
            if boutons_achat:
                score += 3
                mots_trouves.append(f"{len(boutons_achat)} boutons d'achat trouvés près de la date cible par XPath")
        except Exception as e:
            logger.warning(f"Erreur lors de l'analyse XPath: {e}")
        
        # Si on détecte une disponibilité, essayer de prendre une capture d'écran
        if score >= 5 and site_info['type'] in ['officiel', 'revendeur_officiel'] and 'deeplinks' in site_info:
            try:
                logger.info(f"Détection potentielle sur {site_info['nom']}, tentative de capture d'écran")
                
                # Utiliser Selenium pour capturer l'écran
                driver = initialiser_navigateur()
                if driver:
                    try:
                        # Accéder directement au deeplink si disponible
                        deeplink = site_info['deeplinks'][0]
                        driver.get(deeplink)
                        
                        # Attendre le chargement
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                        
                        # Prendre une capture d'écran
                        screenshot_data = prendre_screenshot(driver)
                        if screenshot_data:
                            caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                            screenshots.append({"data": screenshot_data, "caption": caption})
                        
                        # Tenter une réservation automatique si activé
                        if AUTO_RESERVATION and site_info['type'] == 'officiel':
                            tenter_reservation_automatique(deeplink, driver)
                    finally:
                        driver.quit()
            except Exception as e:
                logger.error(f"Erreur lors de la capture d'écran: {e}")
        
        # Prendre une décision sur la disponibilité
        seuil_detection = 5
        
        # Ajuster le seuil selon le type de site
        if site_info['type'] == 'officiel':
            seuil_detection = 6  # Plus strict pour les sites officiels
        elif site_info['type'] == 'revente':
            seuil_detection = 4  # Plus souple pour les sites de revente
        
        if score >= seuil_detection:
            details = ", ".join(mots_trouves)
            return True, f"Disponibilité détectée sur {site_info['nom']} (score: {score}/10) - Éléments trouvés: {details}", screenshots
        else:
            return False, f"Aucune disponibilité détectée sur {site_info['nom']} (score: {score}/10)", []
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de requête sur {site_info['nom']}: {e}")
        return False, f"Erreur de connexion à {site_info['nom']}: {e}", []
    except Exception as e:
        logger.error(f"Erreur non gérée lors de la vérification de {site_info['nom']}: {e}")
        return False, f"Erreur lors de la vérification de {site_info['nom']}: {str(e)}", []

# Fonction pour vérifier tous les sites en parallèle
def verifier_sites_en_parallele(sites, max_workers=5):
    """
    Vérifie plusieurs sites en parallèle pour améliorer la performance.
    
    Args:
        sites (list): Liste des sites à vérifier
        max_workers (int): Nombre maximal de workers en parallèle
    
    Returns:
        list: Résultats des vérifications
    """
    resultats = []
    
    # Grouper les sites par priorité
    sites_par_priorite = {}
    for site in sites:
        priorite = site.get('priorité', 999)
        if priorite not in sites_par_priorite:
            sites_par_priorite[priorite] = []
        sites_par_priorite[priorite].append(site)
    
    # Vérifier par groupes de priorité, en séquentiel pour les priorités 1
    for priorite in sorted(sites_par_priorite.keys()):
        sites_groupe = sites_par_priorite[priorite]
        
        if priorite == 1:  # Sites de priorité 1 (officiels) - vérification séquentielle
            logger.info(f"Vérification séquentielle des {len(sites_groupe)} sites de priorité 1")
            for site in sites_groupe:
                try:
                    disponible, message, screenshots = verifier_site_ameliore(site)
                    
                    resultats.append({
                        "source": site["nom"],
                        "disponible": disponible,
                        "message": message,
                        "url": site["url"],
                        "timestamp": datetime.now().isoformat(),
                        "screenshots": screenshots
                    })
                    
                    if disponible:
                        logger.info(f"DÉTECTION sur {site['nom']}: {message}")
                    else:
                        logger.info(f"{site['nom']}: {message}")
                    
                except Exception as e:
                    logger.error(f"Erreur lors de la vérification de {site['nom']}: {e}")
                    resultats.append({
                        "source": site["nom"],
                        "disponible": False,
                        "message": f"Erreur: {str(e)}",
                        "url": site["url"],
                        "timestamp": datetime.now().isoformat(),
                        "screenshots": []
                    })
                
                # Pause courte entre chaque site officiel
                attendre_aleatoire(1, 3)
        else:
            # Autres priorités - vérification en parallèle
            logger.info(f"Vérification parallèle des {len(sites_groupe)} sites de priorité {priorite}")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Soumettre les tâches
                future_to_site = {executor.submit(verifier_site_ameliore, site): site for site in sites_groupe}
                
                # Collecter les résultats
                for future in as_completed(future_to_site):
                    site = future_to_site[future]
                    try:
                        disponible, message, screenshots = future.result()
                        
                        resultats.append({
                            "source": site["nom"],
                            "disponible": disponible,
                            "message": message,
                            "url": site["url"],
                            "timestamp": datetime.now().isoformat(),
                            "screenshots": screenshots
                        })
                        
                        if disponible:
                            logger.info(f"DÉTECTION sur {site['nom']}: {message}")
                        else:
                            logger.info(f"{site['nom']}: {message}")
                        
                    except Exception as e:
                        logger.error(f"Erreur lors de la vérification de {site['nom']}: {e}")
                        resultats.append({
                            "source": site["nom"],
                            "disponible": False,
                            "message": f"Erreur: {str(e)}",
                            "url": site["url"],
                            "timestamp": datetime.now().isoformat(),
                            "screenshots": []
                        })
            
            # Pause entre les groupes de priorité
            attendre_aleatoire(2, 5)
    
    return resultats

# Remplacer la fonction verifier_site originale par la nouvelle version améliorée
verifier_site = verifier_site_ameliore

# Envoyer des statistiques vers une webapp
def envoyer_stats_vers_webapp(resultats=None):
    """
    Envoie des statistiques vers une web app pour le monitoring.
    
    Args:
        resultats: Résultats des vérifications
    """
    try:
        webapp_url = os.getenv("WEBAPP_URL", "https://rg2025bot.onrender.com/api/update")
        if not webapp_url:
            return
        
        data = {
            "derniere_verification": datetime.now().isoformat(),
            "resultats": resultats,
            "circuit_breakers": {nom: {"state": cb.state, "failure_count": cb.failure_count} 
                                for nom, cb in circuit_breakers.items()},
            "version": "2.5.0",
            "environment": {
                "proxy_service": os.getenv("PROXY_SERVICE", "none"),
                "auto_reservation": str(AUTO_RESERVATION),
                "telegram_enabled": str(UTILISER_TELEGRAM)
            }
        }
        
        # Envoyer les données avec un timeout court
        session = requests.Session()
        response = session.post(webapp_url, json=data, timeout=5)
        
        if response.status_code == 200:
            logger.debug("Statistiques envoyées avec succès à la webapp")
        else:
            logger.warning(f"Erreur lors de l'envoi des statistiques: {response.status_code}")
    except Exception as e:
        logger.error(f"Erreur d'envoi des stats: {e}")

# Fonction pour vérifier les requêtes XHR potentielles que le site Roland-Garros pourrait utiliser
def verifier_requests_xhr_roland_garros():
    """
    Vérifie les requêtes XHR potentielles que le site Roland-Garros pourrait utiliser.
    Cette fonction tente de simuler les requêtes JavaScript faites par le site officiel.
    """
    try:
        logger.info("Tentative de vérification des requêtes XHR du site Roland-Garros")
        
        # Diverses URLs qui pourraient être utilisées en arrière-plan par le site
        urls_potentielles = [
            "https://www.rolandgarros.com/fr-fr/ajax/calendrier?date=2025-05-31",
            "https://www.rolandgarros.com/fr-fr/billetterie/load-dates",
            "https://tickets.fft.fr/api/availability/dates?event=roland-garros-2025",
            "https://www.rolandgarros.com/fr-fr/billetterie/disponibilites"
        ]
        
        # Simuler des cookies de session
        cookies = {
            'visited': 'true',
            'language': 'fr-fr',
            'session_id': f'session_{random.randint(1000000, 9999999)}',
            'visitor_id': f'visitor_{random.randint(1000000, 9999999)}'
        }
        
        headers = {
            'User-Agent': obtenir_user_agent(),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.rolandgarros.com/fr-fr/billetterie',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/json',
            'Origin': 'https://www.rolandgarros.com'
        }
        
        # Pour les requêtes POST potentielles
        data_potentielles = [
            {'date': '2025-05-31', 'lang': 'fr'},
            {'tournament': 'rg', 'year': '2025', 'day': '31', 'month': '05'},
            {'event': 'roland-garros-2025', 'date': '2025-05-31'}
        ]
        
        session = creer_session()
        
        # Ajouter des proxies si configurés
        proxies = proxy_manager.get_proxy_dict()
        if proxies:
            session.proxies.update(proxies)
        
        screenshots = []
        
        for url in urls_potentielles:
            try:
                # Essayer en GET
                logger.info(f"Tentative de requête GET sur {url}")
                reponse = session.get(url, headers=headers, cookies=cookies, timeout=20)
                
                if reponse.status_code == 200:
                    try:
                        # Tenter de parser comme JSON
                        data = reponse.json()
                        logger.info(f"Réponse JSON obtenue de {url}")
                        
                        # Analyser la réponse pour des indices de disponibilité
                        if isinstance(data, dict):
                            for key, value in data.items():
                                if 'disponible' in str(key).lower() or 'available' in str(key).lower():
                                    if value:
                                        return True, f"Disponibilité détectée via XHR: {url}", screenshots
                        
                        # Pour les tableaux de données
                        if isinstance(data, list) and len(data) > 0:
                            for item in data:
                                if isinstance(item, dict):
                                    date_str = str(item.get('date', ''))
                                    if '31/05' in date_str or '31-05' in date_str or '2025-05-31' in date_str:
                                        available = item.get('available', item.get('disponible', False))
                                        if available:
                                            return True, f"Date du 31 mai disponible détectée via XHR: {url}", screenshots
                    except ValueError:
                        # Si ce n'est pas du JSON, chercher des indices dans le HTML
                        if '31 mai' in reponse.text and ('disponible' in reponse.text.lower() or 'available' in reponse.text.lower()):
                            return True, f"Indices de disponibilité trouvés via XHR: {url}", screenshots
                
                # Pause entre les requêtes
                attendre_aleatoire(1, 3)
                
                # Essayer en POST avec différentes données
                for payload in data_potentielles:
                    try:
                        logger.info(f"Tentative de requête POST sur {url}")
                        reponse = session.post(url, headers=headers, cookies=cookies, json=payload, timeout=20)
                        
                        if reponse.status_code == 200:
                            try:
                                data = reponse.json()
                                logger.info(f"Réponse JSON obtenue de POST {url}")
                                
                                # Analyse similaire à celle du GET
                                if isinstance(data, dict):
                                    for key, value in data.items():
                                        if 'disponible' in str(key).lower() or 'available' in str(key).lower():
                                            if value:
                                                return True, f"Disponibilité détectée via POST XHR: {url}", screenshots
                            except ValueError:
                                pass
                    except requests.exceptions.RequestException:
                        continue
                        
                    # Pause entre les requêtes
                    attendre_aleatoire(1, 3)
                
            except requests.exceptions.RequestException:
                continue
        
        return False, "Aucune information de disponibilité trouvée via les requêtes XHR", []
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des requêtes XHR: {e}")
        return False, f"Erreur lors de la vérification XHR: {e}", []

def verifier_twitter():
    """Vérifie les tweets récents mentionnant Roland-Garros et la vente de billets."""
    try:
        url = "https://nitter.net/search?f=tweets&q=roland+garros+billets+31+mai"
        headers = {
            'User-Agent': obtenir_user_agent()
        }
        
        session = creer_session()
        
        # Ajouter des proxies si configurés
        proxies = proxy_manager.get_proxy_dict()
        if proxies:
            session.proxies.update(proxies)
        
        try:
            reponse = session.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur de requête sur Twitter: {e}")
            return False, f"Erreur de connexion à Twitter: {e}", []
        
        if reponse.status_code != 200:
            logger.warning(f"Erreur HTTP {reponse.status_code} sur Twitter")
            return False, f"Erreur lors de l'accès à Twitter: {reponse.status_code}", []
        
        try:
            soup = BeautifulSoup(reponse.text, 'html.parser')
        except Exception as e:
            logger.error(f"Erreur de parsing HTML sur Twitter: {e}")
            return False, f"Erreur lors de l'analyse de Twitter: {e}", []
        
        # Extraire les tweets récents (des dernières 24h)
        tweets_recents = soup.select('.timeline-item')
        tweets_pertinents = []
        
        for tweet in tweets_recents[:10]:  # Vérifier les 10 premiers tweets
            try:
                texte_tweet = tweet.get_text().lower()
                date_tweet = tweet.select_one('.tweet-date')
                
                # Vérifier si le tweet est récent (moins de 24h)
                if date_tweet and "h" in date_tweet.get_text():
                    # Vérifier si le tweet mentionne des billets disponibles
                    if any(mot in texte_tweet for mot in MOTS_CLES + MOTS_CLES_REVENTE) and "31 mai" in texte_tweet:
                        tweets_pertinents.append(texte_tweet)
            except Exception as e:
                logger.warning(f"Erreur lors de l'analyse d'un tweet: {e}")
                continue
        
        if tweets_pertinents:
            # Tenter de prendre une capture d'écran des tweets pertinents
            screenshots = []
            try:
                driver = initialiser_navigateur()
                if driver:
                    try:
                        driver.get(url)
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, '.timeline-item'))
                        )
                        screenshot_data = prendre_screenshot(driver)
                        if screenshot_data:
                            screenshots.append({
                                "data": screenshot_data,
                                "caption": "Tweets mentionnant des billets pour le 31 mai"
                            })
                    finally:
                        driver.quit()
            except Exception as e:
                logger.error(f"Erreur lors de la capture d'écran Twitter: {e}")
            
            return True, f"Tweets récents mentionnant des billets pour le 31 mai: {len(tweets_pertinents)} trouvés", screenshots
        
        return False, "Aucun tweet récent pertinent trouvé", []
    
    except Exception as e:
        logger.error(f"Erreur non gérée lors de la vérification Twitter: {e}")
        return False, f"Erreur lors de la vérification Twitter: {e}", []

# Fonction améliorée pour vérifier tous les sites
def verifier_tous_les_sites():
    """Vérifie tous les sites configurés et retourne les résultats."""
    logger.info("Démarrage de la vérification de tous les sites")
    
    # Vérifier les sites dans l'ordre de priorité
    sites_tries = sorted(SITES_AMELIORES, key=lambda x: x.get('priorité', 999))
    
    # Utiliser la nouvelle fonction parallèle pour vérifier les sites
    resultats = verifier_sites_en_parallele(sites_tries)
    
    # Vérifier les requêtes XHR (alternative à l'API)
    try:
        disponible_xhr, message_xhr, screenshots_xhr = verifier_requests_xhr_roland_garros()
        
        resultats.append({
            "source": "Requêtes XHR Roland-Garros",
            "disponible": disponible_xhr,
            "message": message_xhr,
            "url": "https://www.rolandgarros.com/fr-fr/billetterie",
            "timestamp": datetime.now().isoformat(),
            "screenshots": screenshots_xhr
        })
        
        if disponible_xhr:
            logger.info(f"DÉTECTION via XHR: {message_xhr}")
        else:
            logger.info(f"Requêtes XHR: {message_xhr}")
            
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des requêtes XHR: {e}")
        resultats.append({
            "source": "Requêtes XHR Roland-Garros",
            "disponible": False,
            "message": f"Erreur: {str(e)}",
            "url": "https://www.rolandgarros.com/fr-fr/billetterie",
            "timestamp": datetime.now().isoformat(),
            "screenshots": []
        })
    
    # Vérifier les canaux officiels sur les réseaux sociaux
    try:
        # Vérifier le compte Twitter officiel de Roland-Garros
        url_social = "https://nitter.net/rolandgarros"
        headers = {'User-Agent': obtenir_user_agent()}
        session = creer_session()
        
        try:
            reponse_social = session.get(url_social, headers=headers, timeout=30)
            if reponse_social.status_code == 200:
                soup_social = BeautifulSoup(reponse_social.text, 'html.parser')
                tweets = soup_social.select('.timeline-item')
                
                for tweet in tweets[:5]:  # Vérifier les 5 premiers tweets
                    texte_tweet = tweet.get_text().lower()
                    
                    # Vérifier si le tweet parle de billetterie et de la date cible
                    if ('billet' in texte_tweet or 'ticket' in texte_tweet) and ('31 mai' in texte_tweet or '31/05' in texte_tweet):
                        # Tenter de capturer l'écran
                        screenshots = []
                        try:
                            driver = initialiser_navigateur()
                            if driver:
                                try:
                                    driver.get(url_social)
                                    WebDriverWait(driver, 10).until(
                                        EC.presence_of_element_located((By.CSS_SELECTOR, '.timeline-item'))
                                    )
                                    screenshot_data = prendre_screenshot(driver)
                                    if screenshot_data:
                                        screenshots.append({
                                            "data": screenshot_data,
                                            "caption": "Tweet officiel Roland-Garros mentionnant des billets 31 mai"
                                        })
                                finally:
                                    driver.quit()
                        except Exception as e:
                            logger.error(f"Erreur lors de la capture d'écran Twitter officiel: {e}")
                        
                        resultats.append({
                            "source": "Twitter Officiel Roland-Garros",
                            "disponible": True,
                            "message": f"Tweet récent concernant les billets pour le 31 mai",
                            "url": "https://twitter.com/rolandgarros",
                            "timestamp": datetime.now().isoformat(),
                            "screenshots": screenshots
                        })
                        logger.info("DÉTECTION sur Twitter Officiel Roland-Garros")
                        break
                else:
                    resultats.append({
                        "source": "Twitter Officiel Roland-Garros",
                        "disponible": False,
                        "message": "Aucun tweet récent concernant les billets du 31 mai",
                        "url": "https://twitter.com/rolandgarros",
                        "timestamp": datetime.now().isoformat(),
                        "screenshots": []
                    })
                    logger.info("Aucune info sur Twitter Officiel Roland-Garros")
            else:
                resultats.append({
                    "source": "Twitter Officiel Roland-Garros",
                    "disponible": False,
                    "message": f"Erreur lors de l'accès: {reponse_social.status_code}",
                    "url": "https://twitter.com/rolandgarros",
                    "timestamp": datetime.now().isoformat(),
                    "screenshots": []
                })
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du Twitter officiel: {e}")
            resultats.append({
                "source": "Twitter Officiel Roland-Garros",
                "disponible": False,
                "message": f"Erreur: {str(e)}",
                "url": "https://twitter.com/rolandgarros",
                "timestamp": datetime.now().isoformat(),
                "screenshots": []
            })
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des réseaux sociaux: {e}")
    
    # Recherche Twitter étendue (optionnel - toutes les X vérifications)
    verification_twitter = random.choice([True, False])  # Vérifier aléatoirement
    if verification_twitter:
        try:
            disponible_twitter, message_twitter, screenshots_twitter = verifier_twitter()
            
            resultats.append({
                "source": "Recherche Twitter",
                "disponible": disponible_twitter,
                "message": message_twitter,
                "url": "https://twitter.com/search?q=roland%20garros%20billets%2031%20mai&src=typed_query&f=live",
                "timestamp": datetime.now().isoformat(),
                "screenshots": screenshots_twitter
            })
            
            if disponible_twitter:
                logger.info(f"DÉTECTION sur Twitter: {message_twitter}")
            else:
                logger.info(f"Twitter: {message_twitter}")
                
        except Exception as e:
            logger.error(f"Erreur lors de la vérification Twitter: {e}")
            resultats.append({
                "source": "Recherche Twitter",
                "disponible": False,
                "message": f"Erreur: {str(e)}",
                "url": "https://twitter.com/search?q=roland%20garros%20billets%2031%20mai&src=typed_query&f=live",
                "timestamp": datetime.now().isoformat(),
                "screenshots": []
            })
    
    # Envoyer les statistiques vers la webapp
    envoyer_stats_vers_webapp(resultats)
    
    return resultats

def envoyer_notifications(sujet, message, alertes=None):
    """Envoie des notifications par email et Telegram."""
    success = False
    
    # Extraire tous les screenshots
    screenshots = []
    if alertes:
        for alerte in alertes:
            if 'screenshots' in alerte and alerte['screenshots']:
                screenshots.extend(alerte['screenshots'])
    
    # 1. Envoyer par email
    if EMAIL_ADDRESS and EMAIL_PASSWORD:
        email_ok = envoyer_email(sujet, message, screenshots)
    else:
        email_ok = False
        logger.warning("Configuration email manquante, notification par email non envoyée")
    
    # 2. Envoyer par Telegram avec un format adapté
    if UTILISER_TELEGRAM and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        # Créer un message formaté pour Telegram (Markdown)
        telegram_message = f"*{sujet}*\n\n"
        
        if alertes:
            telegram_message += "Détails des alertes:\n"
            for idx, alerte in enumerate(alertes, 1):
                telegram_message += f"{idx}. *{alerte['source']}*\n"
                telegram_message += f"   {alerte['message']}\n"
                telegram_message += f"   [Voir ici]({alerte['url']})\n\n"
        else:
            # Supprimer les formatages HTML/email et adapter pour Telegram
            clean_message = re.sub(r'\s+', ' ', message)
            telegram_message += clean_message
        
        # Ajouter deeplinks si disponibles
        if alertes:
            deeplinks = []
            for alerte in alertes:
                site_nom = alerte['source']
                for site in SITES_AMELIORES:
                    if site['nom'] == site_nom and 'deeplinks' in site and site['deeplinks']:
                        deeplinks.append((site_nom, site['deeplinks'][0]))
            
            if deeplinks:
                telegram_message += "\n\n*Liens directs pour réservation:*\n"
                for nom, lien in deeplinks:
                    telegram_message += f"• [{nom}]({lien})\n"
        
        # Ajouter coordonnées téléphoniques
        telegram_message += f"\n\nContactez directement le service client au +33 1 47 43 48 00 si nécessaire."
        
        telegram_ok = envoyer_alerte_telegram(telegram_message, screenshots)
        success = email_ok or telegram_ok
    else:
        telegram_ok = False
        logger.warning("Configuration Telegram manquante, notification Telegram non envoyée")
        success = email_ok
    
    return success

def programme_principal():
    """Fonction principale qui vérifie périodiquement les sites."""
    logger.info(f"Bot démarré - Surveillance des billets pour Roland-Garros le {DATE_CIBLE}")
    
    compteur_verifications = 0
    derniere_alerte = None
    derniere_verif_twitter = datetime.now()
    intervalle_twitter = 3600  # Vérifier Twitter toutes les heures
    
    # Créer un dossier 'logs' s'il n'existe pas
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Garder une trace des sites qui ont déjà déclenché une alerte
    sites_alertes = set()
    
    # Statistiques de performance
    temps_debut_total = datetime.now()
    nombre_alertes = 0
    
    while True:
        try:
            # Déterminer l'intervalle de vérification aléatoire pour éviter la détection de pattern
            intervalle_verification = random.randint(INTERVALLE_VERIFICATION_MIN, INTERVALLE_VERIFICATION_MAX)
            
            maintenant = datetime.now()
            compteur_verifications += 1
            
            logger.info(f"Vérification #{compteur_verifications} - {maintenant.strftime('%d/%m/%Y %H:%M:%S')}")
            
            # Sauvegarder le dernier état dans un fichier
            try:
                with open('logs/last_state.json', 'w') as f:
                    etat = {
                        "derniere_verification": maintenant.isoformat(),
                        "compteur": compteur_verifications,
                        "derniere_alerte": derniere_alerte.isoformat() if derniere_alerte else None,
                        "temps_execution_total": str(maintenant - temps_debut_total),
                        "nombre_alertes": nombre_alertes,
                        "prochaine_verification": (maintenant + timedelta(seconds=intervalle_verification)).isoformat(),
                        "intervalle": intervalle_verification,
                        "circuit_breakers": {nom: {"state": cb.state, "failure_count": cb.failure_count} 
                                            for nom, cb in circuit_breakers.items()}
                    }
                    json.dump(etat, f)
            except Exception as e:
                logger.warning(f"Impossible de sauvegarder l'état: {e}")
            
            # Liste pour collecter toutes les alertes positives
            alertes = []
            
            # Faire toutes les vérifications
            try:
                temps_debut = datetime.now()
                resultats = verifier_tous_les_sites()
                temps_fin = datetime.now()
                duree = (temps_fin - temps_debut).total_seconds()
                logger.info(f"Vérification complète en {duree:.2f} secondes")
                
                # Filtrer les alertes positives
                for resultat in resultats:
                    if resultat["disponible"]:
                        alerte = {
                            "source": resultat["source"],
                            "message": resultat["message"],
                            "url": resultat["url"],
                            "screenshots": resultat.get("screenshots", [])
                        }
                        alertes.append(alerte)
            except Exception as e:
                logger.error(f"Erreur lors de la vérification des sites: {e}")
                # Attendre un peu et recommencer
                time.sleep(INTERVALLE_RETRY)
                continue
            
            # Si des alertes ont été trouvées, envoyer des notifications
            if alertes:
                # Filtrer les alertes pour ne pas envoyer plusieurs fois la même alerte
                alertes_nouvelles = []
                for alerte in alertes:
                    # Clé unique pour cette alerte
                    alerte_key = f"{alerte['source']}_{alerte['url']}"
                    
                    # Si ce site n'a pas encore déclenché d'alerte ou si la dernière alerte était il y a plus de 24h
                    if alerte_key not in sites_alertes or (derniere_alerte and (maintenant - derniere_alerte).total_seconds() > 86400):
                        alertes_nouvelles.append(alerte)
                        sites_alertes.add(alerte_key)
                
                # S'il y a de nouvelles alertes
                if alertes_nouvelles:
                    # Construire l'email avec toutes les alertes
                    sujet = f"ALERTE - Billets Roland-Garros disponibles pour le {DATE_CIBLE}!"
                    
                    # Construire le contenu de l'email en HTML
                    contenu_email = f"""
                    <html>
                    <head>
                        <style>
                            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                            .alert {{ background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin-bottom: 15px; border-radius: 4px; }}
                            .source {{ font-weight: bold; color: #721c24; }}
                            .message {{ margin: 5px 0; }}
                            .url {{ color: #0066cc; }}
                            .screenshot {{ margin-top: 10px; }}
                        </style>
                    </head>
                    <body>
                        <h2>Disponibilités détectées pour Roland-Garros le {DATE_CIBLE}</h2>
                        <p>Des disponibilités potentielles ont été détectées par votre bot de surveillance.</p>
                        
                        <h3>Détails des alertes:</h3>
                    """
                    
                    # Ajouter chaque alerte
                    for idx, alerte in enumerate(alertes_nouvelles, 1):
                        contenu_email += f"""
                        <div class="alert">
                            <div class="source">{idx}. {alerte['source']}</div>
                            <div class="message">{alerte['message']}</div>
                            <div class="url"><a href="{alerte['url']}">Voir ici</a></div>
                        </div>
                        """
                    
                    # Ajouter des informations additionnelles comme les deeplinks
                    contenu_email += """
                        <h3>Liens directs pour réservation:</h3>
                        <ul>
                    """
                    
                    for alerte in alertes_nouvelles:
                        site_nom = alerte['source']
                        for site in SITES_AMELIORES:
                            if site['nom'] == site_nom and 'deeplinks' in site and site['deeplinks']:
                                for deeplink in site['deeplinks']:
                                    contenu_email += f'<li><a href="{deeplink}">{site_nom} - Lien direct</a></li>'
                    
                    contenu_email += """
                        </ul>
                        
                        <p>Veuillez vérifier rapidement ces sites pour confirmer et effectuer votre achat.</p>
                        <p><strong>Date et heure de détection:</strong> """ + maintenant.strftime('%d/%m/%Y %H:%M:%S') + """</p>
                        <p>Ce message a été envoyé automatiquement par votre bot de surveillance Roland-Garros.</p>
                        <p>Si l'option de réservation automatique est activée, votre bot a peut-être déjà initié une réservation sur un des sites officiels.</p>
                    </body>
                    </html>
                    """
                    
                    # Éviter d'envoyer des alertes répétées dans un court laps de temps (4 heures)
                    if derniere_alerte is None or (maintenant - derniere_alerte).total_seconds() > 14400:
                        notification_ok = envoyer_notifications(sujet, contenu_email, alertes_nouvelles)
                        if notification_ok:
                            derniere_alerte = maintenant
                            nombre_alertes += 1
                            logger.info(f"ALERTES ENVOYÉES - {len(alertes_nouvelles)} détections")
                            
                            # Enregistrer l'alerte dans un fichier JSON pour référence
                            try:
                                with open(f'logs/alerte_{maintenant.strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
                                    json.dump({
                                        "timestamp": maintenant.isoformat(),
                                        "alertes": [
                                            {
                                                "source": alerte["source"],
                                                "message": alerte["message"], 
                                                "url": alerte["url"]
                                            } for alerte in alertes_nouvelles
                                        ]
                                    }, f)
                            except Exception as e:
                                logger.warning(f"Impossible d'enregistrer les détails de l'alerte: {e}")
                        else:
                            logger.error("Échec de l'envoi des notifications")
                    else:
                        logger.info(f"Disponibilités détectées mais alerte récente déjà envoyée il y a moins de 4 heures")
            
            # Afficher et enregistrer des statistiques pour cette vérification
            try:
                with open('logs/statistiques.json', 'w') as f:
                    stats = {
                        "verification_actuelle": compteur_verifications,
                        "derniere_verification": maintenant.isoformat(),
                        "temps_total_en_execution": str(maintenant - temps_debut_total),
                        "nombre_alertes_envoyees": nombre_alertes,
                        "sites_surveilles": len(SITES_AMELIORES),
                        "prochaine_verification": (maintenant + timedelta(seconds=intervalle_verification)).isoformat(),
                        "circuit_breakers": {nom: {"state": cb.state, "failure_count": cb.failure_count} 
                                            for nom, cb in circuit_breakers.items()}
                    }
                    json.dump(stats, f)
            except Exception as e:
                logger.warning(f"Impossible d'enregistrer les statistiques: {e}")
            
            # Écrire dans les logs l'heure de la prochaine vérification
            prochaine_verification = maintenant + timedelta(seconds=intervalle_verification)
            logger.info(f"Prochaine vérification: {prochaine_verification.strftime('%H:%M:%S')} (intervalle de {intervalle_verification} secondes)")
            
            # Vérifier si on doit faire une purge des logs (garder seulement les 1000 dernières lignes)
            try:
                log_file = "bot_roland_garros.log"
                if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 1024 * 5:  # 5 MB
                    logger.info("Purge du fichier de log")
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                    
                    with open(log_file, 'w') as f:
                        f.writelines(lines[-1000:])
            except Exception as e:
                logger.warning(f"Erreur lors de la purge du fichier de log: {e}")
            
            # Attendre avant la prochaine vérification
            time.sleep(intervalle_verification)
            
        except KeyboardInterrupt:
            logger.info("Bot arrêté manuellement")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans la boucle principale: {e}")
            # Attendre un peu et recommencer
            time.sleep(INTERVALLE_RETRY)

# Point d'entrée principal
if __name__ == "__main__":
    try:
        # Vérifier que les variables d'environnement sont configurées
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "votre_chat_id":
            logger.error("ERREUR: Configuration Telegram incomplète. Veuillez configurer votre TELEGRAM_TOKEN et TELEGRAM_CHAT_ID")
            print("=== CONFIGURATION INCOMPLÈTE ===")
            print(f"Token actuel: {TELEGRAM_TOKEN}")
            print(f"Chat ID actuel: {TELEGRAM_CHAT_ID}")
            print("Veuillez configurer correctement ces valeurs dans les variables d'environnement.")
            exit(1)
        
        # Afficher les informations de configuration
        logger.info(f"=== Configuration ===")
        logger.info(f"Date cible: {DATE_CIBLE}")
        logger.info(f"Intervalle de vérification: {INTERVALLE_VERIFICATION_MIN}-{INTERVALLE_VERIFICATION_MAX} secondes")
        logger.info(f"Nombre de sites surveillés: {len(SITES_AMELIORES)}")
        logger.info(f"Notifications Telegram: {'Activées' if UTILISER_TELEGRAM else 'Désactivées'}")
        logger.info(f"Notifications Email: {'Activées' if EMAIL_ADDRESS and EMAIL_PASSWORD else 'Désactivées'}")
        logger.info(f"Auto-réservation: {'Activée' if AUTO_RESERVATION else 'Désactivée'}")
        logger.info(f"Service de proxy: {proxy_manager.proxy_service}")
        
        # Vérifier l'accès aux sites avant de démarrer
        logger.info("Vérification de l'accès aux sites...")
        sites_inaccessibles = []
        session_test = creer_session()
        
        for site in SITES_AMELIORES:
            try:
                test_response = session_test.get(site["url"], timeout=10, 
                                              headers={'User-Agent': obtenir_user_agent()})
                if test_response.status_code != 200:
                    sites_inaccessibles.append((site["nom"], test_response.status_code))
            except Exception as e:
                sites_inaccessibles.append((site["nom"], str(e)))
        
        if sites_inaccessibles:
            logger.warning("Certains sites sont actuellement inaccessibles :")
            for nom, erreur in sites_inaccessibles:
                logger.warning(f"  - {nom}: {erreur}")
            
            # Envoyer une notification de démarrage avec avertissement
            envoyer_notifications(
                "Démarrage Bot Roland-Garros avec avertissements", 
                f"Le bot a démarré mais certains sites sont inaccessibles: {', '.join(nom for nom, _ in sites_inaccessibles)}.\n\n"
                f"La surveillance continue pour les autres sites.",
                None
            )
        else:
            logger.info("Tous les sites sont accessibles.")
            
        # Envoyer un message de test pour vérifier la configuration
        test_ok = envoyer_notifications(
            "Test - Bot Roland-Garros Démarré", 
            f"Le bot de surveillance pour Roland-Garros le {DATE_CIBLE} a démarré avec succès. "
            f"Vous recevrez des alertes sur ce canal quand des billets seront disponibles. "
            f"Surveillance pour le numéro {TELEPHONE}."
        )
        
        if test_ok:
            logger.info("Test de notification réussi, démarrage de la surveillance...")
            programme_principal()
        else:
            logger.error("Échec du test de notification, veuillez vérifier votre configuration")
            print("ERREUR: Le test de notification a échoué. Veuillez vérifier votre configuration Telegram.")
            
    except KeyboardInterrupt:
        logger.info("Bot arrêté manuellement")
        
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        # Tenter d'envoyer une notification d'erreur
        try:
            envoyer_notifications(
                "ERREUR - Bot Roland-Garros", 
                f"Le bot s'est arrêté en raison d'une erreur: {e}"
            )
        except:
            logger.error("Impossible d'envoyer la notification d'erreur")
