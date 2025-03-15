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
import io
import base64
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import chromedriver_autoinstaller
from selenium.webdriver.chrome.service import Service
import cloudscraper
from lxml import html
from concurrent.futures import ThreadPoolExecutor, as_completed

###############################################################################
#                          GESTION DU CIRCUIT BREAKER                          #
###############################################################################
class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=300):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"

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


###############################################################################
#                         GESTION DU PROXY (OPTIONNEL)                         #
###############################################################################
class ProxyManager:
    def __init__(self):
        self.proxy_service = os.getenv("PROXY_SERVICE", "none")
        self.proxy_username = os.getenv("PROXY_USERNAME", "")
        self.proxy_password = os.getenv("PROXY_PASSWORD", "")
        self.proxy_host = os.getenv("PROXY_HOST", "")
        self.proxy_port = os.getenv("PROXY_PORT", "")
        self.proxy_country = os.getenv("PROXY_COUNTRY", "fr")
        self.proxies = []
        self.current_proxy_index = 0
        self.load_proxies()

    def load_proxies(self):
        if self.proxy_service.lower() == "none":
            return
        if self.proxy_service.lower() == "file":
            try:
                with open("proxies.txt", "r") as f:
                    self.proxies = [line.strip() for line in f if line.strip()]
                logger.info(f"Loaded {len(self.proxies)} proxies from file")
            except Exception as e:
                logger.error(f"Failed to load proxies from file: {e}")
        else:
            proxy_url = ""
            if self.proxy_service.lower() == "brightdata":
                proxy_url = (
                    f"http://{self.proxy_username}-country-"
                    f"{self.proxy_country}:{self.proxy_password}@"
                    f"{self.proxy_host}:{self.proxy_port}"
                )
            elif self.proxy_service.lower() == "smartproxy":
                proxy_url = (
                    f"http://{self.proxy_username}:"
                    f"{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
                )
            if proxy_url:
                self.proxies.append(proxy_url)
                logger.info(f"Configured {self.proxy_service} proxy service")

    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy

    def get_proxy_dict(self):
        proxy = self.get_next_proxy()
        if not proxy:
            return {}
        return {"http": proxy, "https": proxy}

    def get_selenium_proxy(self):
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


###############################################################################
#                  CHARGEMENT DES VARIABLES D'ENVIRONNEMENT                   #
###############################################################################
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_roland_garros.log", mode='a')
    ]
)
logger = logging.getLogger("RolandGarrosBot")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
UTILISER_TELEGRAM = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
TELEPHONE = os.getenv("TELEPHONE", "0000000000")

AUTO_RESERVATION = os.getenv("AUTO_RESERVATION", "False").lower() in ["true", "1", "yes", "oui"]
RESERVATION_EMAIL = os.getenv("RESERVATION_EMAIL", "")
RESERVATION_PASSWORD = os.getenv("RESERVATION_PASSWORD", "")
RESERVATION_NOM = os.getenv("RESERVATION_NOM", "")
RESERVATION_PRENOM = os.getenv("RESERVATION_PRENOM", "")
RESERVATION_TELEPHONE = os.getenv("RESERVATION_TELEPHONE", "")
RESERVATION_MAX_PRIX = float(os.getenv("RESERVATION_MAX_PRIX", "1000"))

# Pour limiter la fréquence d'accès
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]

# Intervalle de vérification aléatoire
INTERVALLE_VERIFICATION_MIN = int(os.getenv("INTERVALLE_MIN", "540"))
INTERVALLE_VERIFICATION_MAX = int(os.getenv("INTERVALLE_MAX", "660"))
INTERVALLE_RETRY = 30  # en secondes

# Liste d'User-Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]

###############################################################################
#            DÉFINITION DE LA LISTE DES SITES À SURVEILLER (EXTRAIT)          #
###############################################################################
SITES_AMELIORES = [
    {
        "nom": "Site Officiel Roland-Garros",
        "url": "https://www.rolandgarros.com/fr-fr/billetterie",
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
            "https://www.rolandgarros.com/fr-fr/billetterie?date=2025-05-31"
        ],
        "retry_config": {"max_retries": 3, "backoff_factor": 2}
    },
    {
        "nom": "FFT Billetterie",
        "url": "https://tickets.fft.fr/catalogue/roland-garros",
        "type": "officiel",
        "priorité": 1,
        "selectors": {
            "calendrier": ".calendar, .date-picker, .dates-container",
            "date_items": ".date, .day, [data-date]",
            "achat_buttons": ".buy-button, .add-to-cart, .book-now",
            "disponibilite": ".available, .in-stock, .bookable"
        },
        "ajax_api": "https://tickets.fft.fr/api/availability/dates?event=roland-garros-2025",
        "deeplinks": [
            "https://tickets.fft.fr/catalogue/roland-garros-2025?date=2025-05-31"
        ],
        "retry_config": {"max_retries": 2, "backoff_factor": 2}
    },
    # ... AJOUTEZ ICI LES AUTRES SITES ...
]

SITES = SITES_AMELIORES
DATE_CIBLE = "31 mai 2025"
JOUR_SEMAINE_CIBLE = "samedi"
MOTS_CLES = [
    "31 mai", "disponible", "billetterie", "vente", "nouvelle vente",
    "samedi 31", "31/05", "31/05/2025", "dernier jour", "phase finale",
    "places", "billets disponibles", "court", "tribune", "acheter"
]
MOTS_CLES_REVENTE = [
    "roland garros 31 mai", "31 mai 2025", "samedi 31 mai",
    "roland garros weekend", "demi-finales", "ticket disponible"
]

circuit_breakers = {}
proxy_manager = ProxyManager()

###############################################################################
#        FONCTION D'ATTENTE AVEC TEMPS ALÉATOIRE (SANS pyautogui)             #
###############################################################################
def attendre_aleatoire(min_sec=2, max_sec=5):
    """Attend un temps aléatoire pour simuler un comportement humain minimal."""
    duree = random.uniform(min_sec, max_sec)
    time.sleep(duree)
    return duree


###############################################################################
#           CRÉATION DE SESSION HTTP AVEC RÉESSAIS ET SUPPORT PROXY           #
###############################################################################
def creer_session(site_info=None):
    session = requests.Session()
    retry_config = site_info.get("retry_config", {}) if site_info else {}
    max_retries = retry_config.get("max_retries", MAX_RETRIES)
    backoff_factor = retry_config.get("backoff_factor", RETRY_BACKOFF_FACTOR)
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=RETRY_STATUS_FORCELIST,
        allowed_methods=["GET", "HEAD", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    proxies = proxy_manager.get_proxy_dict()
    if proxies:
        session.proxies.update(proxies)
    return session


def obtenir_user_agent():
    return random.choice(USER_AGENTS)


###############################################################################
#         FONCTIONS D'ENVOI DE NOTIFICATIONS (EMAIL ET TELEGRAM)             #
###############################################################################
def envoyer_email(sujet, message, screenshots=None):
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
            msg = MIMEMultipart()
            msg['Subject'] = sujet
            msg['From'] = EMAIL_ADDRESS
            msg['To'] = EMAIL_RECIPIENT
            msg.attach(MIMEText(message, 'html'))
            if screenshots:
                for i, screenshot in enumerate(screenshots):
                    try:
                        img_data = base64.b64decode(screenshot["data"])
                        img = MIMEImage(img_data)
                        img.add_header('Content-Disposition', f'attachment; filename="screenshot_{i+1}.png"')
                        img.add_header('Content-ID', f'<screenshot_{i+1}>')
                        msg.attach(img)
                    except Exception as e:
                        logger.error(f"Erreur lors de l'ajout du screenshot {i+1}: {e}")
            serveur.send_message(msg)
        logger.info(f"Email envoyé avec succès: {sujet}")
        return True
    except (socket.gaierror, ssl.SSLError, smtplib.SMTPException) as e:
        logger.error(f"Erreur SMTP/SSL lors de l'envoi de l'email: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'envoi de l'email: {e}")
        return False


def envoyer_alerte_telegram(message, screenshots=None):
    if not UTILISER_TELEGRAM:
        logger.warning("Telegram n'est pas configuré, notification non envoyée")
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Token Telegram ou Chat ID manquant, notification non envoyée")
        return False
    try:
        for tentative in range(MAX_RETRIES):
            try:
                bot = telebot.TeleBot(TELEGRAM_TOKEN)
                bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='Markdown')
                if screenshots:
                    for screenshot in screenshots:
                        try:
                            img_data = base64.b64decode(screenshot["data"])
                            caption = screenshot.get("caption", "Disponibilité détectée")
                            with io.BytesIO(img_data) as img_stream:
                                bot.send_photo(TELEGRAM_CHAT_ID, img_stream, caption=caption)
                        except Exception as e:
                            logger.error(f"Erreur lors de l'envoi du screenshot Telegram: {e}")
                logger.info("Notification Telegram envoyée avec succès")
                return True
            except telebot.apihelper.ApiTelegramException as e:
                if "429" in str(e):
                    # Limite de rate
                    if tentative < MAX_RETRIES - 1:
                        attente = (tentative + 1) * 5
                        logger.warning(f"Rate limit Telegram, nouvel essai dans {attente} secondes...")
                        time.sleep(attente)
                    else:
                        raise
                else:
                    raise
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification Telegram: {e}")
    return False


def envoyer_notifications(sujet, message, alertes=None):
    success = False
    screenshots = []
    if alertes:
        for alerte in alertes:
            if alerte.get('screenshots'):
                screenshots.extend(alerte['screenshots'])
    email_ok = envoyer_email(sujet, message, screenshots)
    telegram_ok = False
    if UTILISER_TELEGRAM:
        telegram_message = f"*{sujet}*\n\n"
        if alertes:
            for idx, alerte in enumerate(alertes, 1):
                telegram_message += f"{idx}. *{alerte['source']}*\n"
                telegram_message += f"   {alerte['message']}\n"
                telegram_message += f"   [Voir ici]({alerte['url']})\n\n"
        else:
            telegram_message += re.sub(r'\s+', ' ', message)
        telegram_ok = envoyer_alerte_telegram(telegram_message, screenshots)
    return email_ok or telegram_ok


###############################################################################
#          INITIALISATION DU NAVIGATEUR SELENIUM POUR LES SITES COMPLEXES     #
###############################################################################
def initialiser_navigateur(force_stable_chrome_version="113"):
    """
    Initialise et retourne une instance de navigateur Chrome en mode headless.
    force_stable_chrome_version : Ex. "113", "114"...
    """
    try:
        logger.info("Initialisation du navigateur headless (Selenium)")

        # FORCER une version stable (si possible) pour éviter les erreurs
        # "no such driver by url"
        try:
            chromedriver_autoinstaller.install(True, force_stable_chrome_version)
        except Exception as e:
            logger.warning(f"chromedriver-autoinstaller n'a pas pu installer la version {force_stable_chrome_version}: {e}")
            # On tente quand même un install() par défaut
            chromedriver_autoinstaller.install()

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--enable-javascript")
        options.add_argument("--lang=fr-FR")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Fix anti-detection
        user_agent = random.choice(USER_AGENTS)
        options.add_argument(f"user-agent={user_agent}")

        # Ajouter un proxy si configuré
        proxy = proxy_manager.get_selenium_proxy()
        if proxy:
            options.proxy = proxy

        service = Service()  # chrome driver
        driver = webdriver.Chrome(service=service, options=options)

        # Petits patchs anti-bot
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]})")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US']})")

        attendre_aleatoire(1, 3)
        return driver

    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du navigateur: {e}")
        return None


###############################################################################
#     FONCTION DE CAPTURE D'ÉCRAN AVEC SELENIUM (OPTIONNEL - SI DISPONIBLE)   #
###############################################################################
def prendre_screenshot(driver, highlight_elements=None):
    """Prend une capture d'écran avec Selenium."""
    try:
        if not driver:
            return None
        if highlight_elements:
            # Surligner éventuellement
            pass
        screenshot = driver.get_screenshot_as_base64()
        return screenshot
    except Exception as e:
        logger.error(f"Erreur lors de la prise de capture d'écran: {e}")
        return None


###############################################################################
#  FONCTION POUR TENTER UNE RÉSERVATION AUTOMATIQUE (SI AUTO_RESERVATION=TRUE)#
###############################################################################
def tenter_reservation_automatique(url, driver=None):
    if not AUTO_RESERVATION:
        logger.info("Auto-réservation désactivée.")
        return False, "Auto-réservation désactivée"
    if not RESERVATION_EMAIL or not RESERVATION_PASSWORD:
        logger.warning("Informations de connexion manquantes pour l'auto-réservation")
        return False, "Informations de connexion manquantes"

    logger.info(f"Tentative de réservation sur {url}")
    fermer_driver = False
    try:
        if not driver:
            driver = initialiser_navigateur()
            fermer_driver = True
            if not driver:
                return False, "Impossible d'initialiser le navigateur pour la réservation"
        driver.get(url)
        attendre_aleatoire(2, 4)
        # ...votre logique de réservation...
        return False, "Fonction de réservation à implémenter"

    except Exception as e:
        logger.error(f"Erreur lors de la tentative de réservation: {e}")
        return False, f"Erreur: {str(e)}"
    finally:
        if fermer_driver and driver:
            try:
                driver.quit()
            except:
                pass


###############################################################################
#                     VERIFICATION STANDARD (SANS SELENIUM)                   #
###############################################################################
def verifier_site_standard(site_info):
    try:
        session = creer_session(site_info)
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://www.google.com/search?q=roland+garros+billets",
        }
        if 'headers_specifiques' in site_info:
            headers.update(site_info['headers_specifiques'])

        cookies = {
            "visited": "true",
            "cookie_consent": "accepted",
            "session": f"session_{random.randint(10000, 99999)}",
            "language": "fr"
        }

        logger.info(f"Accès à {site_info['url']}")
        response = session.get(site_info['url'], headers=headers, cookies=cookies, timeout=30)
        attendre_aleatoire(1, 2)

        if response.status_code != 200:
            msg = f"Erreur HTTP {response.status_code} sur {site_info['nom']}"
            logger.warning(msg)
            return False, msg, []

        # Exemple simplifié: recherche "31 mai" dans le HTML
        contenu = response.text.lower()
        score = 0
        screenshots = []
        if "31 mai" in contenu:
            score += 3

        # Autres vérifications (selectors, etc.) ...
        # On simplifie ici pour l'exemple
        if score >= 3:
            return True, f"Disponibilité potentielle sur {site_info['nom']}", screenshots
        else:
            return False, f"Aucune disponibilité sur {site_info['nom']}", []

    except requests.exceptions.RequestException as e:
        err_msg = f"Erreur de connexion à {site_info['nom']}: {e}"
        logger.error(err_msg)
        return False, err_msg, []
    except Exception as e:
        err_msg = f"Erreur lors de la vérification de {site_info['nom']}: {e}"
        logger.error(err_msg)
        return False, err_msg, []


###############################################################################
#           VERIFICATION AVEC CLOUDSCRAPER (SITES AVEC CLOUDFLARE)            #
###############################################################################
def verifier_site_avec_cloudscraper(site_info):
    logger.info(f"Vérification de {site_info['nom']} avec CloudScraper")
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    if not circuit_breakers[site_nom].allow_request():
        return False, f"Circuit breaker ouvert pour {site_nom}", []

    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True},
            delay=5
        )
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/search?q=roland+garros+billets",
        }
        cookies = {
            "visited": "true",
            "session": f"session_{random.randint(10000, 99999)}",
            "language": "fr"
        }
        proxies = proxy_manager.get_proxy_dict()
        response = scraper.get(site_info['url'], headers=headers, cookies=cookies, proxies=proxies, timeout=30)
        attendre_aleatoire(1, 2)

        if response.status_code != 200:
            circuit_breakers[site_nom].record_failure()
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}", []

        contenu = response.text.lower()
        score = 0
        if "31 mai" in contenu:
            score += 3
        screenshots = []
        if score >= 3:
            circuit_breakers[site_nom].record_success()
            return True, f"Disponibilité détectée sur {site_info['nom']}", screenshots

        circuit_breakers[site_nom].record_success()
        return False, f"Aucune disponibilité sur {site_info['nom']}", []
    except Exception as e:
        circuit_breakers[site_nom].record_failure()
        return False, f"Erreur Cloudscraper {site_info['nom']}: {e}", []


###############################################################################
#          VERIFICATION AVEC SELENIUM (SITES AVEC FORTES PROTECTIONS)         #
###############################################################################
def verifier_site_avec_selenium(site_info):
    logger.info(f"Vérification de {site_info['nom']} avec Selenium")
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    if not circuit_breakers[site_nom].allow_request():
        return False, f"Circuit breaker ouvert pour {site_nom}", []

    driver = None
    try:
        driver = initialiser_navigateur()
        if not driver:
            circuit_breakers[site_nom].record_failure()
            return False, f"Impossible d'initialiser le navigateur pour {site_nom}", []

        driver.get(site_info['url'])
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        attendre_aleatoire(1, 2)

        contenu = driver.page_source.lower()
        score = 0
        screenshots = []
        if "31 mai" in contenu:
            score += 3

        if score >= 3:
            screenshot_data = prendre_screenshot(driver)
            if screenshot_data:
                screenshots.append({"data": screenshot_data, "caption": f"Sélénium - {site_info['nom']}"})
            circuit_breakers[site_nom].record_success()
            return True, f"Disponibilité détectée sur {site_info['nom']}", screenshots

        circuit_breakers[site_nom].record_success()
        return False, f"Aucune disponibilité sur {site_info['nom']}", []
    except TimeoutException:
        circuit_breakers[site_nom].record_failure()
        return False, f"Timeout sur {site_nom}", []
    except WebDriverException as e:
        circuit_breakers[site_nom].record_failure()
        return False, f"Erreur WebDriver {site_nom}: {e}", []
    except Exception as e:
        circuit_breakers[site_nom].record_failure()
        return False, f"Erreur Selenium {site_nom}: {e}", []
    finally:
        if driver:
            driver.quit()


###############################################################################
#                   FONCTION GLOBALE DE VERIFICATION DE SITE                  #
###############################################################################
def verifier_site(site_info):
    # Détecter si le site a une protection anti-bot + priority usage
    if site_info.get('anti_bot_protection'):
        # Tenter cloudscraper, si échec on fait Selenium
        dispo, msg, sc = verifier_site_avec_cloudscraper(site_info)
        if "Erreur" in msg or not dispo:
            dispo2, msg2, sc2 = verifier_site_avec_selenium(site_info)
            sc.extend(sc2)
            return dispo2, msg2, sc
        else:
            return dispo, msg, sc
    else:
        # Sinon on tente la version standard
        # (ou Selenium si site_info indique un usage Selenium)
        if site_info.get('type') in ['officiel', 'revendeur_officiel'] and site_info.get('priorité', 999) <= 2:
            # Ex: on peut tenter d'abord site standard, sinon selenium
            dispo, msg, sc = verifier_site_standard(site_info)
            if not dispo and "Erreur" not in msg:
                # en dernier recours
                dispo2, msg2, sc2 = verifier_site_avec_selenium(site_info)
                sc.extend(sc2)
                return dispo2, msg2, sc
            return dispo, msg, sc
        else:
            # Simple
            return verifier_site_standard(site_info)


###############################################################################
#                        FONCTION PRINCIPALE DU PROGRAMME                     #
###############################################################################
def programme_principal():
    logger.info(f"Bot démarré - Surveillance RG {DATE_CIBLE}")
    compteur = 0
    while True:
        try:
            compteur += 1
            maintenant = datetime.now()
            logger.info(f"Vérification #{compteur} - {maintenant}")
            intervalle_verification = random.randint(INTERVALLE_VERIFICATION_MIN, INTERVALLE_VERIFICATION_MAX)

            alertes = []
            for site in SITES:
                disponible, message, screenshots = verifier_site(site)
                if disponible:
                    alertes.append({
                        "source": site["nom"],
                        "message": message,
                        "url": site["url"],
                        "screenshots": screenshots
                    })
                    logger.info(f"DÉTECTION - {site['nom']}: {message}")
                else:
                    logger.info(f"{site['nom']}: {message}")

                time.sleep(1)  # Petite pause entre les sites

            if alertes:
                sujet = f"ALERTE - Billets RG disponibles {DATE_CIBLE} !"
                texte = f"Des disponibilités ont été détectées pour {DATE_CIBLE}.\n\n"
                for idx, al in enumerate(alertes, 1):
                    texte += f"{idx}. {al['source']} -> {al['message']}\nUrl: {al['url']}\n\n"
                envoyer_notifications(sujet, texte, alertes)

            prochaine_verif = maintenant + timedelta(seconds=intervalle_verification)
            logger.info(f"Prochaine vérification: {prochaine_verif.strftime('%H:%M:%S')} (dans {intervalle_verification} s)")
            time.sleep(intervalle_verification)

        except KeyboardInterrupt:
            logger.info("Bot arrêté manuellement.")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue: {e}")
            time.sleep(INTERVALLE_RETRY)


###############################################################################
#                POINT D'ENTRÉE SI ON EXÉCUTE CE FICHIER DIRECTEMENT          #
###############################################################################
if __name__ == "__main__":
    try:
        # Vérifications basiques
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Configuration Telegram incomplète ou absente.")
        programme_principal()
    except KeyboardInterrupt:
        logger.info("Arrêt manuel.")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
