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
import pyautogui
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
                proxy_url = f"http://{self.proxy_username}-country-{self.proxy_country}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
            elif self.proxy_service.lower() == "smartproxy":
                proxy_url = f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
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
        return {
            "http": proxy,
            "https": proxy
        }

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
UTILISER_TELEGRAM = True if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID else False
TELEPHONE = os.getenv("TELEPHONE", "0600000000")

AUTO_RESERVATION = os.getenv("AUTO_RESERVATION", "False").lower() in ["true", "1", "yes", "oui"]
RESERVATION_EMAIL = os.getenv("RESERVATION_EMAIL", "")
RESERVATION_PASSWORD = os.getenv("RESERVATION_PASSWORD", "")
RESERVATION_NOM = os.getenv("RESERVATION_NOM", "")
RESERVATION_PRENOM = os.getenv("RESERVATION_PRENOM", "")
RESERVATION_TELEPHONE = os.getenv("RESERVATION_TELEPHONE", "")
RESERVATION_MAX_PRIX = float(os.getenv("RESERVATION_MAX_PRIX", "1000"))

MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]
INTERVALLE_VERIFICATION_MIN = int(os.getenv("INTERVALLE_MIN", "540"))
INTERVALLE_VERIFICATION_MAX = int(os.getenv("INTERVALLE_MAX", "660"))
INTERVALLE_RETRY = 30

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
    "roland garros weekend", "derniers jours", "demi-finales",
    "billet disponible", "ticket disponible", "disponibilités"
]
circuit_breakers = {}
proxy_manager = ProxyManager()

def attendre_aleatoire(min_sec=2, max_sec=5):
    duree = random.uniform(min_sec, max_sec)
    if random.random() < 0.2 and os.getenv("SIMULATE_MOUSE", "False").lower() in ["true", "1", "yes", "oui"]:
        try:
            current_x, current_y = pyautogui.position()
            new_x = current_x + random.randint(-100, 100)
            new_y = current_y + random.randint(-100, 100)
            move_duration = random.uniform(0.2, 0.8)
            pyautogui.moveTo(new_x, new_y, duration=move_duration)
            if random.random() < 0.3:
                pyautogui.click()
            pyautogui.moveTo(current_x, current_y, duration=move_duration)
        except:
            pass
    time.sleep(duree)
    return duree

def creer_session(site_info=None):
    session = requests.Session()
    retry_config = site_info.get("retry_config", {}) if site_info else {}
    max_retries = retry_config.get("max_retries", MAX_RETRIES)
    backoff_factor = retry_config.get("backoff_factor", RETRY_BACKOFF_FACTOR)
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=RETRY_STATUS_FORCELIST,
        allowed_methods=["GET", "HEAD", "OPTIONS"]
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
                            logger.error(f"Erreur lors de l'envoi du screenshot: {e}")
                logger.info("Notification Telegram envoyée avec succès")
                return True
            except telebot.apihelper.ApiTelegramException as e:
                if "429" in str(e):
                    if tentative < MAX_RETRIES - 1:
                        attente = (tentative + 1) * 5
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
    """
    Configure le bot Telegram et renvoie des instructions pour le configurer.
    """
    instructions = f"""
    1. Ouvrez votre application Telegram et cherchez @BotFather
    2. Suivez les instructions pour créer un nouveau bot et obtenir votre token
    3. Configurez la variable d'environnement TELEGRAM_TOKEN avec ce token
    4. Configurez la variable d'environnement TELEGRAM_CHAT_ID avec l'ID du chat où envoyer les messages
    """
    logger.info("Instructions de configuration du bot Telegram générées")
    return instructions

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
        original_styles = {}
        if highlight_elements:
            for element in highlight_elements:
                try:
                    original_style = element.get_attribute("style")
                    original_styles[element] = original_style
                    driver.execute_script(
                        "arguments[0].setAttribute('style', arguments[1]);",
                        element,
                        "border: 3px solid red; background-color: yellow; padding: 5px;"
                    )
                except Exception as e:
                    logger.error(f"Erreur lors de la mise en évidence d'un élément: {e}")
        screenshot = driver.get_screenshot_as_base64()
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
            except:
                pass
        return screenshot
    except Exception as e:
        logger.error(f"Erreur lors de la prise de capture d'écran: {e}")
        return None

def initialiser_navigateur():
    """
    Initialise et retourne une instance de navigateur Chrome en mode headless.
    """
    try:
        logger.info("Initialisation du navigateur headless pour les sites protégés")
        chromedriver_autoinstaller.install()
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-automation")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--enable-javascript")
        options.add_argument("--lang=fr-FR")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        proxy = proxy_manager.get_selenium_proxy()
        if proxy:
            options.proxy = proxy
        driver = webdriver.Chrome(options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US', 'en']})")
        attendre_aleatoire(1, 3)
        return driver
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du navigateur: {e}")
        return None

def tenter_reservation_automatique(url, driver=None):
    """
    Tente de réserver automatiquement des billets si disponibles.
    Returns: tuple (succès, message)
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
        if not driver:
            driver = initialiser_navigateur()
            fermer_driver = True
            if not driver:
                return False, "Impossible d'initialiser le navigateur pour la réservation"
        driver.get(url)
        attendre_aleatoire(2, 4)
        if "rolandgarros.com" in url or "fft.fr" in url:
            try:
                login_buttons = driver.find_elements(By.CSS_SELECTOR, "a[href*='login'], a[href*='connexion'], button.login, .btn-login")
                if login_buttons:
                    logger.info("Tentative de connexion au compte utilisateur")
                    login_buttons[0].click()
                    attendre_aleatoire(2, 4)
                    email_field = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
                    )
                    email_field.send_keys(RESERVATION_EMAIL)
                    attendre_aleatoire(0.5, 1)
                    password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
                    password_field.send_keys(RESERVATION_PASSWORD)
                    attendre_aleatoire(0.5, 1)
                    submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], .btn-submit, .btn-login")
                    submit_button.click()
                    attendre_aleatoire(3, 5)
                date_elements = driver.find_elements(By.CSS_SELECTOR, "[data-date='2025-05-31'], .calendar-day[data-value='2025-05-31'], .calendar-day:contains('31')")
                if date_elements:
                    logger.info("Date du 31 mai trouvée, tentative de sélection")
                    date_elements[0].click()
                    attendre_aleatoire(2, 4)
                ticket_elements = driver.find_elements(By.CSS_SELECTOR, ".ticket-item.available, .offer-item[data-available='true'], .category-available")
                if ticket_elements:
                    best_ticket = None
                    lowest_price = float('inf')
                    for ticket in ticket_elements:
                        try:
                            price_text = ticket.find_element(By.CSS_SELECTOR, ".price, .amount").text
                            price = float(re.search(r'(\d+[.,]?\d*)', price_text.replace(',', '.')).group(1))
                            if price < lowest_price and price <= RESERVATION_MAX_PRIX:
                                lowest_price = price
                                best_ticket = ticket
                        except:
                            continue
                    if best_ticket:
                        logger.info(f"Ticket trouvé au prix de {lowest_price}€, tentative d'ajout au panier")
                        best_ticket.find_element(By.CSS_SELECTOR, "button.add-to-cart, .btn-buy, .btn-book").click()
                        attendre_aleatoire(2, 4)
                        checkout_buttons = driver.find_elements(By.CSS_SELECTOR, ".btn-checkout, .proceed-to-checkout, a[href*='checkout']")
                        if checkout_buttons:
                            checkout_buttons[0].click()
                            attendre_aleatoire(2, 4)
                            logger.info("Procédure d'achat initiée, remplissage des informations")
                            screenshot = prendre_screenshot(driver)
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
            return False, "Auto-réservation non supportée pour ce site"
    except Exception as e:
        logger.error(f"Erreur générale lors de la tentative de réservation: {e}")
        return False, f"Erreur générale: {str(e)}"
    finally:
        if fermer_driver and driver:
            try:
                driver.quit()
            except:
                pass

def verifier_site_avec_selenium(site_info):
    """
    Vérifie un site à l'aide de Selenium pour contourner les protections anti-bot.
    Returns: (disponible, message, screenshots)
    """
    logger.info(f"Vérification de {site_info['nom']} avec Selenium (protection anti-bot)")
    driver = None
    screenshots = []
    elements_a_surligner = []
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
        driver.get("https://www.google.com")
        attendre_aleatoire(1, 2)
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        for name, value in cookies.items():
            driver.add_cookie({'name': name, 'value': value, 'domain': site_info['url'].split('/')[2]})
        logger.info(f"Accès à {site_info['url']} via Selenium")
        driver.get(site_info['url'])
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {i * 500});")
            attendre_aleatoire(0.5, 1.5)
        selectors = site_info.get('selectors', {})
        mots_trouves = []
        score = 0
        disponible = False
        contenu_page = driver.page_source.lower()
        date_trouvee = any(date_format in contenu_page for date_format in ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        if 'calendrier' in selectors:
            try:
                calendriers = driver.find_elements(By.CSS_SELECTOR, selectors['calendrier'])
                for cal in calendriers:
                    cal_text = cal.text.lower()
                    if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                        score += 3
                        mots_trouves.append("calendrier avec 31 mai détecté")
                        elements_a_surligner.append(cal)
                        classes = cal.get_attribute("class")
                        if classes and any(c for c in ['available', 'bookable', 'in-stock'] if c in classes.lower()):
                            score += 3
                            mots_trouves.append("jour 31 mai marqué comme disponible")
                            disponible = True
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des calendriers: {e}")
        if 'date_items' in selectors:
            try:
                dates = driver.find_elements(By.CSS_SELECTOR, selectors['date_items'])
                for date_elem in dates:
                    date_text = date_elem.text.lower()
                    if '31' in date_text and ('mai' in date_text or '05' in date_text or 'may' in date_text):
                        score += 2
                        mots_trouves.append("élément de date 31 mai détecté")
                        elements_a_surligner.append(date_elem)
                        parent = date_elem.find_element(By.XPATH, "./..")
                        parent_html = parent.get_attribute('outerHTML').lower()
                        if any(term in parent_html for term in ['disponible', 'available', 'acheter', 'buy']):
                            score += 3
                            mots_trouves.append("date 31 mai associée à une disponibilité")
                            disponible = True
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des éléments de date: {e}")
        if 'achat_buttons' in selectors:
            try:
                boutons = driver.find_elements(By.CSS_SELECTOR, selectors['achat_buttons'])
                for bouton in boutons:
                    bouton_text = bouton.text.lower()
                    bouton_html = bouton.get_attribute('outerHTML').lower()
                    if any(term in bouton_text for term in ['acheter', 'réserver', 'buy', 'book']):
                        score += 1
                        mots_trouves.append("bouton d'achat détecté")
                        try:
                            parent = bouton.find_element(By.XPATH, "./ancestor::div[contains(@class, 'event') or contains(@class, 'ticket')]")
                            parent_text = parent.text.lower()
                            if '31 mai' in parent_text or '31/05' in parent_text:
                                score += 4
                                mots_trouves.append("bouton d'achat pour le 31 mai")
                                elements_a_surligner.append(bouton)
                                disponible = True
                        except:
                            pass
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des boutons d'achat: {e}")
        if 'disponibilite' in selectors:
            try:
                indicateurs = driver.find_elements(By.CSS_SELECTOR, selectors['disponibilite'])
                for ind in indicateurs:
                    ind_text = ind.text.lower()
                    ind_html = ind.get_attribute('outerHTML').lower()
                    if any(term in ind_text for term in ['disponible', 'available', 'en stock']):
                        try:
                            parent = ind.find_element(By.XPATH, "./ancestor::div[contains(@class, 'event') or contains(@class, 'ticket')]")
                            parent_text = parent.text.lower()
                            if '31 mai' in parent_text or '31/05' in parent_text:
                                score += 5
                                mots_trouves.append("indicateur de disponibilité explicite pour le 31 mai")
                                elements_a_surligner.append(ind)
                                disponible = True
                        except:
                            pass
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification des indicateurs de disponibilité: {e}")
        if disponible or score >= 5:
            screenshot_data = prendre_screenshot(driver, elements_a_surligner)
            if screenshot_data:
                caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                screenshots.append({"data": screenshot_data, "caption": caption})
                if disponible and AUTO_RESERVATION and site_info['type'] == 'officiel' and 'deeplinks' in site_info and site_info['deeplinks']:
                    deeplink = site_info['deeplinks'][0]
                    tenter_reservation_automatique(deeplink, driver)
        circuit_breakers[site_nom].record_success()
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
            except:
                pass

def verifier_site_avec_cloudscraper(site_info):
    """
    Vérifie un site à l'aide de cloudscraper pour contourner les protections CloudFlare.
    Returns: (disponible, message, screenshots)
    """
    logger.info(f"Vérification de {site_info['nom']} avec CloudScraper")
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    if not circuit_breakers[site_nom].allow_request():
        logger.warning(f"Circuit breaker ouvert pour {site_nom}, vérification ignorée")
        return False, f"Circuit breaker ouvert pour {site_nom} (trop d'erreurs récentes)", []
    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=5
        )
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Referer': 'https://www.google.com/search?q=roland+garros+billets',
        }
        if 'headers_specifiques' in site_info:
            headers.update(site_info['headers_specifiques'])
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        proxies = proxy_manager.get_proxy_dict()
        logger.info(f"Accès à {site_info['url']} via CloudScraper")
        response = scraper.get(site_info['url'], headers=headers, cookies=cookies, proxies=proxies, timeout=30)
        attendre_aleatoire(1, 3)
        if response.status_code != 200:
            circuit_breakers[site_nom].record_failure()
            logger.warning(f"Erreur HTTP {response.status_code} sur {site_info['nom']}")
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}", []
        soup = BeautifulSoup(response.text, 'html.parser')
        contenu_page = soup.get_text().lower()
        selectors = site_info.get('selectors', {})
        mots_trouves = []
        score = 0
        screenshots = []
        date_trouvee = any(date_format in contenu_page for date_format in ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        mots_cles_additionnels = site_info.get('mots_cles_additionnels', [])
        for mot in mots_cles_additionnels:
            if mot.lower() in contenu_page:
                mots_trouves.append(f"mot-clé '{mot}' trouvé")
                score += 1
        if 'calendrier' in selectors:
            calendriers = soup.select(selectors['calendrier'])
            for cal in calendriers:
                cal_text = cal.get_text().lower()
                if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                    score += 3
                    mots_trouves.append("calendrier avec 31 mai détecté")
                    classes = cal.get('class', [])
                    if any(c for c in classes if 'available' in c or 'bookable' in c or 'in-stock' in c):
                        score += 3
                        mots_trouves.append("jour 31 mai marqué comme disponible")
        if 'disponibilite' in selectors:
            disponibilites = soup.select(selectors['disponibilite'])
            for disp in disponibilites:
                disp_text = disp.get_text().lower()
                if any(term in disp_text for term in ['disponible', 'available', 'en stock']):
                    parent = disp.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 5
                            mots_trouves.append("disponibilité explicite pour le 31 mai")
        if 'ajax_api' in site_info:
            try:
                api_url = site_info['ajax_api']
                api_headers = headers.copy()
                api_headers['X-Requested-With'] = 'XMLHttpRequest'
                api_response = scraper.get(api_url, headers=api_headers, cookies=cookies, proxies=proxies, timeout=20)
                if api_response.status_code == 200:
                    try:
                        api_data = api_response.json()
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
        if score >= 5 and site_info['type'] in ['officiel', 'revendeur_officiel'] and 'deeplinks' in site_info:
            try:
                logger.info(f"Détection potentielle sur {site_info['nom']}, tentative de capture d'écran")
                driver = initialiser_navigateur()
                if driver:
                    try:
                        deeplink = site_info['deeplinks'][0]
                        driver.get(deeplink)
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                        screenshot_data = prendre_screenshot(driver)
                        if screenshot_data:
                            caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                            screenshots.append({"data": screenshot_data, "caption": caption})
                        if AUTO_RESERVATION and site_info['type'] == 'officiel':
                            tenter_reservation_automatique(deeplink, driver)
                    finally:
                        driver.quit()
            except Exception as e:
                logger.error(f"Erreur lors de la capture d'écran: {e}")
        circuit_breakers[site_nom].record_success()
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

def analyser_json_pour_disponibilite(json_data):
    score = 0
    mots_trouves = []

    def explorer_json(obj, chemin=""):
        nonlocal score, mots_trouves
        if isinstance(obj, dict):
            date_cible_trouvee = False
            disponibilite_trouvee = False
            for key, value in obj.items():
                key_lower = str(key).lower()
                if 'date' in key_lower or 'jour' in key_lower or 'day' in key_lower:
                    str_value = str(value).lower()
                    if '31/05' in str_value or '31-05' in str_value or '31 mai' in str_value or '2025-05-31' in str_value:
                        date_cible_trouvee = True
                        mots_trouves.append(f"date 31 mai trouvée dans JSON à {chemin}.{key}")
                elif ('disponible' in key_lower or 'available' in key_lower or 'status' in key_lower or 'bookable' in key_lower or 'stock' in key_lower):
                    str_value = str(value).lower()
                    if str_value in ['true', '1', 'yes', 'disponible', 'available', 'en stock', 'in stock']:
                        disponibilite_trouvee = True
                        mots_trouves.append(f"disponibilité trouvée dans JSON à {chemin}.{key}")
            if date_cible_trouvee and disponibilite_trouvee:
                score += 5
                mots_trouves.append(f"date 31 mai ET disponibilité trouvées dans le même objet JSON")
            for key, value in obj.items():
                explorer_json(value, f"{chemin}.{key}" if chemin else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                explorer_json(item, f"{chemin}[{i}]")

    explorer_json(json_data)
    return score, mots_trouves

def verifier_site_standard(site_info):
    """
    Vérifie un site standard sans protection particulière.
    Returns: (disponible, message, screenshots)
    """
    try:
        logger.info(f"Vérification de {site_info['nom']}...")
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
        if 'headers_specifiques' in site_info:
            headers.update(site_info['headers_specifiques'])
        cookies = {
            'visited': 'true',
            'cookie_consent': 'accepted',
            'session': f'session_{random.randint(10000, 99999)}',
            'language': 'fr'
        }
        logger.info(f"Accès à {site_info['url']}")
        response = session.get(site_info['url'], headers=headers, cookies=cookies, timeout=30)
        attendre_aleatoire(1, 3)
        if response.status_code != 200:
            logger.warning(f"Erreur HTTP {response.status_code} sur {site_info['nom']}")
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}", []
        soup = BeautifulSoup(response.text, 'html.parser')
        lxml_tree = html.fromstring(response.content)
        contenu_page = soup.get_text().lower()
        mots_trouves = []
        score = 0
        screenshots = []
        date_trouvee = any(date_format in contenu_page for date_format in ["31 mai", "31/05/2025", "31/05", "samedi 31"])
        if date_trouvee:
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        selectors = site_info.get('selectors', {})
        if 'calendrier' in selectors:
            calendriers = soup.select(selectors['calendrier'])
            for cal in calendriers:
                cal_text = cal.get_text().lower()
                if '31' in cal_text and ('mai' in cal_text or '05' in cal_text):
                    score += 3
                    mots_trouves.append("calendrier avec 31 mai détecté")
                    classes = cal.get('class', [])
                    if any(c for c in classes if 'available' in c or 'bookable' in c or 'in-stock' in c):
                        score += 3
                        mots_trouves.append("jour 31 mai marqué comme disponible")
        if 'date_items' in selectors:
            dates = soup.select(selectors['date_items'])
            for date_elem in dates:
                date_text = date_elem.get_text().lower()
                if '31' in date_text and ('mai' in date_text or '05' in date_text):
                    score += 2
                    mots_trouves.append("élément de date 31 mai détecté")
                    parent = date_elem.find_parent()
                    if parent:
                        parent_html = str(parent).lower()
                        if any(term in parent_html for term in ['disponible', 'available', 'acheter', 'buy']):
                            score += 3
                            mots_trouves.append("date 31 mai associée à une disponibilité")
        if 'achat_buttons' in selectors:
            boutons = soup.select(selectors['achat_buttons'])
            for bouton in boutons:
                bouton_text = bouton.get_text().lower()
                if any(term in bouton_text for term in ['acheter', 'réserver', 'buy', 'book']):
                    score += 1
                    mots_trouves.append("bouton d'achat détecté")
                    parent = bouton.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 4
                            mots_trouves.append("bouton d'achat pour le 31 mai")
        if 'disponibilite' in selectors:
            disponibilites = soup.select(selectors['disponibilite'])
            for disp in disponibilites:
                disp_text = disp.get_text().lower()
                if any(term in disp_text for term in ['disponible', 'available', 'en stock']):
                    parent = disp.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent:
                        parent_text = parent.get_text().lower()
                        if '31 mai' in parent_text or '31/05' in parent_text:
                            score += 5
                            mots_trouves.append("disponibilité explicite pour le 31 mai")
        mots_cles_additionnels = site_info.get('mots_cles_additionnels', [])
        for mot in mots_cles_additionnels:
            if mot.lower() in contenu_page:
                mots_trouves.append(f"mot-clé '{mot}' trouvé")
                score += 1
        if 'api_url' in site_info:
            try:
                api_url = site_info['api_url']
                api_headers = headers.copy()
                api_headers['Accept'] = 'application/json'
                api_response = session.get(api_url, headers=api_headers, cookies=cookies, timeout=20)
                if api_response.status_code == 200:
                    try:
                        api_data = api_response.json()
                        json_score, json_mots = analyser_json_pour_disponibilite(api_data)
                        score += json_score
                        mots_trouves.extend(json_mots)
                    except Exception as e:
                        logger.warning(f"Erreur lors de l'analyse des données API: {e}")
            except Exception as e:
                logger.warning(f"Erreur lors de l'accès à l'API: {e}")
        scripts = soup.find_all('script')
        for script in scripts:
            script_content = script.string if script.string else ''
            if script_content:
                json_matches = re.findall(r'({[^{]*?"date.*?})', script_content)
                for json_str in json_matches:
                    try:
                        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_]+):', r'\1"\2":', json_str)
                        json_data = json.loads(json_str)
                        if isinstance(json_data, dict):
                            date_value = None
                            for k, v in json_data.items():
                                if 'date' in k.lower():
                                    date_value = str(v).lower()
                            if date_value and ('31/05' in date_value or '31-05' in date_value or '31 mai' in date_value):
                                for k, v in json_data.items():
                                    if 'disponible' in k.lower() or 'available' in k.lower() or 'status' in k.lower():
                                        if str(v).lower() in ['true', '1', 'yes', 'disponible', 'available']:
                                            score += 4
                                            mots_trouves.append("données JSON indiquant disponibilité pour le 31 mai")
                    except:
                        pass
        try:
            xpath_disponibilite = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//*[contains(@class, 'available') or contains(@class, 'dispo')]"
            elements_disponibles = lxml_tree.xpath(xpath_disponibilite)
            if elements_disponibles:
                score += 4
                mots_trouves.append(f"{len(elements_disponibles)} éléments de disponibilité trouvés par XPath")
            xpath_boutons = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//button[contains(text(), 'Acheter') or contains(text(), 'Réserver') or contains(text(), 'Buy')]"
            boutons_achat = lxml_tree.xpath(xpath_boutons)
            if boutons_achat:
                score += 3
                mots_trouves.append(f"{len(boutons_achat)} boutons d'achat trouvés près de la date cible par XPath")
        except Exception as e:
            logger.warning(f"Erreur lors de l'analyse XPath: {e}")
        if score >= 5 and site_info['type'] in ['officiel', 'revendeur_officiel'] and 'deeplinks' in site_info:
            try:
                logger.info(f"Détection potentielle sur {site_info['nom']}, tentative de capture d'écran")
                driver = initialiser_navigateur()
                if driver:
                    try:
                        deeplink = site_info['deeplinks'][0]
                        driver.get(deeplink)
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                        screenshot_data = prendre_screenshot(driver)
                        if screenshot_data:
                            caption = f"Disponibilité sur {site_info['nom']} (score: {score}/10)"
                            screenshots.append({"data": screenshot_data, "caption": caption})
                        if AUTO_RESERVATION and site_info['type'] == 'officiel':
                            tenter_reservation_automatique(deeplink, driver)
                    finally:
                        driver.quit()
            except Exception as e:
                logger.error(f"Erreur lors de la capture d'écran: {e}")
        seuil_detection = 5
        if site_info['type'] == 'officiel':
            seuil_detection = 6
        elif site_info['type'] == 'revente':
            seuil_detection = 4
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

def verifier_site_ameliore(site_info):
    urls_a_essayer = [site_info['url']] + site_info.get('urls_alt', [])
    disponible = False
    message = ""
    screenshots = []
    site_nom = site_info['nom']
    if site_nom not in circuit_breakers:
        circuit_breakers[site_nom] = CircuitBreaker(site_nom)
    if not circuit_breakers[site_nom].allow_request():
        logger.warning(f"Circuit breaker ouvert pour {site_nom}, vérification ignorée")
        return False, f"Circuit breaker ouvert pour {site_nom} (trop d'erreurs récentes)", []
    for url_index, url in enumerate(urls_a_essayer):
        if url_index > 0:
            logger.info(f"Tentative avec URL alternative {url_index} pour {site_info['nom']}")
            site_info_temp = site_info.copy()
            site_info_temp['url'] = url
        else:
            site_info_temp = site_info
        try:
            if site_info.get('anti_bot_protection', False) or any(domain in site_info['url'] for domain in ['viagogo', 'stubhub', 'ticketswap']):
                disponible, message, screenshots = verifier_site_avec_cloudscraper(site_info_temp)
                if disponible or "Erreur" not in message:
                    break
                if "Erreur" in message and url_index == len(urls_a_essayer) - 1:
                    logger.warning(f"Échec avec CloudScraper pour {site_info['nom']}, tentative avec Selenium")
                    disponible, message, selenium_screenshots = verifier_site_avec_selenium(site_info)
                    if selenium_screenshots:
                        screenshots.extend(selenium_screenshots)
                    break
            else:
                dispo_tmp, msg_tmp, screenshots_tmp = verifier_site_standard(site_info_temp)
                disponible = dispo_tmp
                message = msg_tmp
                screenshots = screenshots_tmp
                if disponible or "Erreur" not in message:
                    break
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {site_info['nom']} avec l'URL {url}: {e}")
            message = f"Erreur lors de la vérification: {str(e)}"
    if "Erreur" in message:
        circuit_breakers[site_nom].record_failure()
    else:
        circuit_breakers[site_nom].record_success()
    return disponible, message, screenshots

def verifier_sites_en_parallele(sites, max_workers=5):
    resultats = []
    sites_par_priorite = {}
    for site in sites:
        priorite = site.get('priorité', 999)
        if priorite not in sites_par_priorite:
            sites_par_priorite[priorite] = []
        sites_par_priorite[priorite].append(site)
    for priorite in sorted(sites_par_priorite.keys()):
        sites_groupe = sites_par_priorite[priorite]
        if priorite == 1:
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
                attendre_aleatoire(1, 3)
        else:
            logger.info(f"Vérification parallèle des {len(sites_groupe)} sites de priorité {priorite}")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_site = {executor.submit(verifier_site_ameliore, site): site for site in sites_groupe}
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
            attendre_aleatoire(2, 5)
    return resultats

verifier_site = verifier_site_ameliore

def envoyer_stats_vers_webapp(resultats=None):
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
        session = requests.Session()
        response = session.post(webapp_url, json=data, timeout=5)
        if response.status_code == 200:
            logger.debug("Statistiques envoyées avec succès à la webapp")
        else:
            logger.warning(f"Erreur lors de l'envoi des statistiques: {response.status_code}")
    except Exception as e:
        logger.error(f"Erreur d'envoi des stats: {e}")

def verifier_requests_xhr_roland_garros():
    try:
        logger.info("Tentative de vérification des requêtes XHR du site Roland-Garros")
        urls_potentielles = [
            "https://www.rolandgarros.com/fr-fr/ajax/calendrier?date=2025-05-31",
            "https://www.rolandgarros.com/fr-fr/billetterie/load-dates",
            "https://tickets.fft.fr/api/availability/dates?event=roland-garros-2025",
            "https://www.rolandgarros.com/fr-fr/billetterie/disponibilites"
        ]
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
        data_potentielles = [
            {'date': '2025-05-31', 'lang': 'fr'},
            {'tournament': 'rg', 'year': '2025', 'day': '31', 'month': '05'},
            {'event': 'roland-garros-2025', 'date': '2025-05-31'}
        ]
        session = creer_session()
        proxies = proxy_manager.get_proxy_dict()
        if proxies:
            session.proxies.update(proxies)
        screenshots = []
        for url in urls_potentielles:
            try:
                logger.info(f"Tentative de requête GET sur {url}")
                reponse = session.get(url, headers=headers, cookies=cookies, timeout=20)
                if reponse.status_code == 200:
                    try:
                        data = reponse.json()
                        logger.info(f"Réponse JSON obtenue de {url}")
                        if isinstance(data, dict):
                            for key, value in data.items():
                                if 'disponible' in str(key).lower() or 'available' in str(key).lower():
                                    if value:
                                        return True, f"Disponibilité détectée via XHR: {url}", screenshots
                        if isinstance(data, list) and len(data) > 0:
                            for item in data:
                                if isinstance(item, dict):
                                    date_str = str(item.get('date', ''))
                                    if '31/05' in date_str or '31-05' in date_str or '2025-05-31' in date_str:
                                        available = item.get('available', item.get('disponible', False))
                                        if available:
                                            return True, f"Date du 31 mai disponible détectée via XHR: {url}", screenshots
                    except ValueError:
                        if '31 mai' in reponse.text and ('disponible' in reponse.text.lower() or 'available' in reponse.text.lower()):
                            return True, f"Indices de disponibilité trouvés via XHR: {url}", screenshots
                attendre_aleatoire(1, 3)
                for payload in data_potentielles:
                    try:
                        logger.info(f"Tentative de requête POST sur {url}")
                        reponse = session.post(url, headers=headers, cookies=cookies, json=payload, timeout=20)
                        if reponse.status_code == 200:
                            try:
                                data = reponse.json()
                                logger.info(f"Réponse JSON obtenue de POST {url}")
                                if isinstance(data, dict):
                                    for key, value in data.items():
                                        if 'disponible' in str(key).lower() or 'available' in str(key).lower():
                                            if value:
                                                return True, f"Disponibilité détectée via POST XHR: {url}", screenshots
                            except ValueError:
                                pass
                    except:
                        continue
                    attendre_aleatoire(1, 3)
            except:
                continue
        return False, "Aucune information de disponibilité trouvée via les requêtes XHR", []
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des requêtes XHR: {e}")
        return False, f"Erreur lors de la vérification XHR: {e}", []

def verifier_twitter():
    """
    Vérifie les tweets récents mentionnant Roland-Garros et la vente de billets.
    Returns: (disponible, message, screenshots)
    """
    try:
        url = "https://nitter.net/search?f=tweets&q=roland+garros+billets+31+mai"
        headers = {
            'User-Agent': obtenir_user_agent()
        }
        session = creer_session()
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
        tweets_recents = soup.select('.timeline-item')
        tweets_pertinents = []
        for tweet in tweets_recents[:10]:
            try:
                texte_tweet = tweet.get_text().lower()
                date_tweet = tweet.select_one('.tweet-date')
                if date_tweet and "h" in date_tweet.get_text():
                    if any(mot in texte_tweet for mot in MOTS_CLES + MOTS_CLES_REVENTE) and "31 mai" in texte_tweet:
                        tweets_pertinents.append(texte_tweet)
            except:
                continue
        if tweets_pertinents:
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

def verifier_tous_les_sites():
    logger.info("Démarrage de la vérification de tous les sites")
    sites_tries = sorted(SITES_AMELIORES, key=lambda x: x.get('priorité', 999))
    resultats = verifier_sites_en_parallele(sites_tries)
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
    try:
        url_social = "https://nitter.net/rolandgarros"
        headers = {'User-Agent': obtenir_user_agent()}
        session = creer_session()
        try:
            reponse_social = session.get(url_social, headers=headers, timeout=30)
            if reponse_social.status_code == 200:
                soup_social = BeautifulSoup(reponse_social.text, 'html.parser')
                tweets = soup_social.select('.timeline-item')
                for tweet in tweets[:5]:
                    texte_tweet = tweet.get_text().lower()
                    if ('billet' in texte_tweet or 'ticket' in texte_tweet) and ('31 mai' in texte_tweet or '31/05' in texte_tweet):
                        screenshots_data = []
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
                                        screenshots_data.append({
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
                            "screenshots": screenshots_data
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
    verification_twitter = random.choice([True, False])
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
    envoyer_stats_vers_webapp(resultats)
    return resultats

def envoyer_notifications(sujet, message, alertes=None):
    success = False
    screenshots = []
    if alertes:
        for alerte in alertes:
            if 'screenshots' in alerte and alerte['screenshots']:
                screenshots.extend(alerte['screenshots'])
    if EMAIL_ADDRESS and EMAIL_PASSWORD:
        email_ok = envoyer_email(sujet, message, screenshots)
    else:
        email_ok = False
        logger.warning("Configuration email manquante, notification par email non envoyée")
    if UTILISER_TELEGRAM and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        telegram_message = f"*{sujet}*\n\n"
        if alertes:
            telegram_message += "Détails des alertes:\n"
            for idx, alerte in enumerate(alertes, 1):
                telegram_message += f"{idx}. *{alerte['source']}*\n"
                telegram_message += f"   {alerte['message']}\n"
                telegram_message += f"   [Voir ici]({alerte['url']})\n\n"
        else:
            clean_message = re.sub(r'\s+', ' ', message)
            telegram_message += clean_message
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
        telegram_message += f"\n\nContactez directement le service client au +33 1 47 43 48 00 si nécessaire."
        telegram_ok = envoyer_alerte_telegram(telegram_message, screenshots)
        success = email_ok or telegram_ok
    else:
        telegram_ok = False
        logger.warning("Configuration Telegram manquante, notification Telegram non envoyée")
        success = email_ok
    return success

def programme_principal():
    logger.info(f"Bot démarré - Surveillance des billets pour Roland-Garros le {DATE_CIBLE}")
    compteur_verifications = 0
    derniere_alerte = None
    derniere_verif_twitter = datetime.now()
    intervalle_twitter = 3600
    if not os.path.exists('logs'):
        os.makedirs('logs')
    sites_alertes = set()
    temps_debut_total = datetime.now()
    nombre_alertes = 0
    while True:
        try:
            intervalle_verification = random.randint(INTERVALLE_VERIFICATION_MIN, INTERVALLE_VERIFICATION_MAX)
            maintenant = datetime.now()
            compteur_verifications += 1
            logger.info(f"Vérification #{compteur_verifications} - {maintenant.strftime('%d/%m/%Y %H:%M:%S')}")
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
            alertes = []
            try:
                temps_debut = datetime.now()
                resultats = verifier_tous_les_sites()
                temps_fin = datetime.now()
                duree = (temps_fin - temps_debut).total_seconds()
                logger.info(f"Vérification complète en {duree:.2f} secondes")
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
                time.sleep(INTERVALLE_RETRY)
                continue
            if alertes:
                alertes_nouvelles = []
                for alerte in alertes:
                    alerte_key = f"{alerte['source']}_{alerte['url']}"
                    if alerte_key not in sites_alertes or (derniere_alerte and (maintenant - derniere_alerte).total_seconds() > 86400):
                        alertes_nouvelles.append(alerte)
                        sites_alertes.add(alerte_key)
                if alertes_nouvelles:
                    sujet = f"ALERTE - Billets Roland-Garros disponibles pour le {DATE_CIBLE}!"
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
                    for idx, alerte in enumerate(alertes_nouvelles, 1):
                        contenu_email += f"""
                        <div class="alert">
                            <div class="source">{idx}. {alerte['source']}</div>
                            <div class="message">{alerte['message']}</div>
                            <div class="url"><a href="{alerte['url']}">Voir ici</a></div>
                        </div>
                        """
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
                    if derniere_alerte is None or (maintenant - derniere_alerte).total_seconds() > 14400:
                        notification_ok = envoyer_notifications(sujet, contenu_email, alertes_nouvelles)
                        if notification_ok:
                            derniere_alerte = maintenant
                            nombre_alertes += 1
                            logger.info(f"ALERTES ENVOYÉES - {len(alertes_nouvelles)} détections")
                            try:
                                with open(f'logs/alerte_{maintenant.strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
                                    json.dump({
                                        "timestamp": maintenant.isoformat(),
                                        "alertes": [
                                            {
                                                "source": al["source"],
                                                "message": al["message"],
                                                "url": al["url"]
                                            } for al in alertes_nouvelles
                                        ]
                                    }, f)
                            except Exception as e:
                                logger.warning(f"Impossible d'enregistrer les détails de l'alerte: {e}")
                        else:
                            logger.error("Échec de l'envoi des notifications")
                    else:
                        logger.info("Disponibilités détectées mais alerte récente déjà envoyée il y a moins de 4 heures")
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
            prochaine_verification = maintenant + timedelta(seconds=intervalle_verification)
            logger.info(f"Prochaine vérification: {prochaine_verification.strftime('%H:%M:%S')} (intervalle de {intervalle_verification} secondes)")
            try:
                log_file = "bot_roland_garros.log"
                if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 1024 * 5:
                    logger.info("Purge du fichier de log")
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                    with open(log_file, 'w') as f:
                        f.writelines(lines[-1000:])
            except Exception as e:
                logger.warning(f"Erreur lors de la purge du fichier de log: {e}")
            time.sleep(intervalle_verification)
        except KeyboardInterrupt:
            logger.info("Bot arrêté manuellement")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans la boucle principale: {e}")
            time.sleep(INTERVALLE_RETRY)

if __name__ == "__main__":
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "votre_chat_id":
            logger.error("ERREUR: Configuration Telegram incomplète. Veuillez configurer votre TELEGRAM_TOKEN et TELEGRAM_CHAT_ID")
            print("=== CONFIGURATION INCOMPLÈTE ===")
            print(f"Token actuel: {TELEGRAM_TOKEN}")
            print(f"Chat ID actuel: {TELEGRAM_CHAT_ID}")
            print("Veuillez configurer correctement ces valeurs dans les variables d'environnement.")
            exit(1)
        logger.info(f"=== Configuration ===")
        logger.info(f"Date cible: {DATE_CIBLE}")
        logger.info(f"Intervalle de vérification: {INTERVALLE_VERIFICATION_MIN}-{INTERVALLE_VERIFICATION_MAX} secondes")
        logger.info(f"Nombre de sites surveillés: {len(SITES_AMELIORES)}")
        logger.info(f"Notifications Telegram: {'Activées' if UTILISER_TELEGRAM else 'Désactivées'}")
        logger.info(f"Notifications Email: {'Activées' if EMAIL_ADDRESS and EMAIL_PASSWORD else 'Désactivées'}")
        logger.info(f"Auto-réservation: {'Activée' if AUTO_RESERVATION else 'Désactivée'}")
        logger.info(f"Service de proxy: {proxy_manager.proxy_service}")
        logger.info("Vérification de l'accès aux sites...")
        sites_inaccessibles = []
        session_test = creer_session()
        for site in SITES_AMELIORES:
            try:
                test_response = session_test.get(site["url"], timeout=10, headers={'User-Agent': obtenir_user_agent()})
                if test_response.status_code != 200:
                    sites_inaccessibles.append((site["nom"], test_response.status_code))
            except Exception as e:
                sites_inaccessibles.append((site["nom"], str(e)))
        if sites_inaccessibles:
            logger.warning("Certains sites sont actuellement inaccessibles :")
            for nom, erreur in sites_inaccessibles:
                logger.warning(f"  - {nom}: {erreur}")
            envoyer_notifications(
                "Démarrage Bot Roland-Garros avec avertissements",
                f"Le bot a démarré mais certains sites sont inaccessibles: {', '.join(nom for nom, _ in sites_inaccessibles)}.\n\n"
                f"La surveillance continue pour les autres sites.",
                None
            )
        else:
            logger.info("Tous les sites sont accessibles.")
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
        try:
            envoyer_notifications(
                "ERREUR - Bot Roland-Garros",
                f"Le bot s'est arrêté en raison d'une erreur: {e}"
            )
        except:
            logger.error("Impossible d'envoyer la notification d'erreur")
