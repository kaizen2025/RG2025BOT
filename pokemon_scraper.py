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
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException
import chromedriver_autoinstaller
from selenium.webdriver.chrome.service import Service
import cloudscraper
from lxml import html
from concurrent.futures import ThreadPoolExecutor, as_completed

###############################################################################
#                         CIRCUIT BREAKER MANAGEMENT                          #
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
#                        PROXY MANAGEMENT (OPTIONAL)                          #
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
#                  LOADING ENVIRONMENT VARIABLES                              #
###############################################################################
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pokemon_stock_bot.log", mode='a')
    ]
)
logger = logging.getLogger("PokemonStockBot")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
USE_TELEGRAM = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

# For limiting access frequency
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]

# Random verification interval
CHECK_INTERVAL_MIN = int(os.getenv("INTERVALLE_MIN", "540"))
CHECK_INTERVAL_MAX = int(os.getenv("INTERVALLE_MAX", "660"))
RETRY_INTERVAL = 30  # in seconds

# List of User-Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

###############################################################################
#            DEFINITION OF SITES TO MONITOR                                   #
###############################################################################
POKEMON_COLLECTIONS = [
    {
        "name": "Collection Prismatique",
        "keywords": ["pokemon", "prismatique", "jcc", "coffret", "boosters"],
        "product_ids": ["B0D35YH8CW", "B0D35YH5T3"],  # Amazon product IDs examples
        "image_url": "https://m.media-amazon.com/images/I/71jjIpV14wL._AC_SL1500_.jpg"
    },
    {
        "name": "Collection Aventures Ensemble",
        "keywords": ["pokemon", "aventures ensemble", "jcc", "coffret", "boosters"],
        "product_ids": ["B0CD1MMYKL", "B0CD1K2Y9V"],  # Amazon product IDs examples
        "image_url": "https://m.media-amazon.com/images/I/71WJKOS8MIL._AC_SL1500_.jpg"
    },
    {
        "name": "Collection Eaux Florissantes",
        "keywords": ["pokemon", "eaux florissantes", "jcc", "coffret", "boosters"],
        "product_ids": ["B0BZ3Z7BF1", "B0C84MB8D4"],  # Amazon product IDs examples
        "image_url": "https://m.media-amazon.com/images/I/71J8vVaMB2L._AC_SL1500_.jpg"
    }
]

# Common scraping selectors for different sites
COMMON_SELECTORS = {
    "amazon": {
        "availability": [
            "#availability span", 
            "#availability",
            "#outOfStock",
            ".a-section.a-spacing-none.a-padding-none > #availability",
            ".a-section.a-spacing-micro > #availability"
        ],
        "price": [
            "#priceblock_ourprice", 
            ".a-price .a-offscreen",
            "#corePrice_feature_div .a-price .a-offscreen",
            ".a-section.a-spacing-none.aok-align-center > .a-price .a-offscreen"
        ],
        "title": [
            "#productTitle",
            "#title",
            ".product-title-word-break"
        ],
        "image": [
            "#landingImage",
            "#imgBlkFront",
            ".a-dynamic-image img",
            "#image-block-container img"
        ],
        "add_to_cart_button": [
            "#add-to-cart-button",
            "#add-to-cart",
            "#buy-now-button",
            ".a-button-input[name='submit.add-to-cart']",
            "#submit\\.add-to-cart"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Livraison gratuite",
            "expédié par Amazon",
            "Disponible à l'achat"
        ],
        "out_of_stock_text": [
            "Actuellement indisponible",
            "Nous ne savons pas quand cet article sera de nouveau approvisionné",
            "Temporairement en rupture de stock",
            "Cet article n'est pas disponible",
            "Rupture de stock"
        ]
    },
    "fnac": {
        "availability": [
            ".f-buyBox-availabilityStatus-available", 
            ".f-buyBox-availabilityStatus",
            ".js-Availability-price",
            ".f-buyBox-element.js-ProductAvailability"
        ],
        "price": [
            ".f-priceBox-price.f-priceBox-price--reco", 
            ".f-priceBox-price",
            ".js-ProductPrice span"
        ],
        "title": [
            ".f-productHeader-Title",
            ".js-ProductTitle",
            "h1[itemprop='name']"
        ],
        "image": [
            ".f-productVisuals-mainVisual img",
            ".js-ProductMainImage",
            ".product-img img[itemprop='image']"
        ],
        "add_to_cart_button": [
            ".js-ProductBuy-add button",
            ".f-buyBox-button--buyNow",
            ".js-AddToCart button",
            "button[data-fbt='addToCart']"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Expédié sous",
            "livraison gratuite",
            "En stock en ligne"
        ],
        "out_of_stock_text": [
            "Indisponible",
            "En rupture de stock",
            "Momentanément indisponible",
            "Rupture fournisseur",
            "Stock épuisé"
        ]
    },
    "cultura": {
        "availability": [
            ".stock-box", 
            ".availability-msg",
            ".product-info-stock"
        ],
        "price": [
            ".product-info-price .price-final-price .price", 
            ".regular-price .price",
            ".price-container .price"
        ],
        "title": [
            ".page-title-wrapper h1",
            ".product-name",
            ".product-info-main h1"
        ],
        "image": [
            ".gallery-placeholder img",
            ".product-image-photo",
            ".fotorama__img"
        ],
        "add_to_cart_button": [
            "#product-addtocart-button",
            ".tocart",
            "button.action.primary.tocart"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Expédié sous",
            "En stock en magasin",
            "En stock en ligne"
        ],
        "out_of_stock_text": [
            "Indisponible",
            "Rupture",
            "Épuisé",
            "Non disponible",
            "Plus en stock"
        ]
    },
    "carrefour": {
        "availability": [
            ".stock-status",
            ".product-detail__stock",
            "[data-automation='product-stock-status']"
        ],
        "price": [
            ".product-price__amount",
            ".product-details__current-price",
            "[data-automation='product-price']"
        ],
        "title": [
            ".product-detail__title",
            ".product-card__title",
            "h1.product-detail__title"
        ],
        "image": [
            ".product-detail__image img",
            ".product-card__image img",
            "[data-automation='product-visual'] img"
        ],
        "add_to_cart_button": [
            ".pdp-button-container button",
            ".add-to-cart-button",
            "[data-automation='add-to-cart-button']"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Livrable",
            "en magasin",
            "Disponible"
        ],
        "out_of_stock_text": [
            "Indisponible",
            "Épuisé",
            "Rupture",
            "Plus disponible",
            "Non livrable"
        ]
    },
    "joueclubdrive": {
        "availability": [
            ".product-info__stock", 
            ".stock-indication",
            ".in-stock-status"
        ],
        "price": [
            ".price-info .price", 
            ".current-price",
            ".product-price"
        ],
        "title": [
            ".product-info__name",
            ".product-name",
            "h1.product-title"
        ],
        "image": [
            ".product-media__image img",
            ".product-image img",
            ".product-image-container img"
        ],
        "add_to_cart_button": [
            ".product-add-form button",
            "#product-addtocart-button",
            ".add-to-cart-button"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Retrait",
            "Livraison",
            "En magasin"
        ],
        "out_of_stock_text": [
            "Indisponible",
            "Rupture",
            "Épuisé",
            "Non disponible",
            "Plus en stock"
        ]
    },
    "kingjouetonline": {
        "availability": [
            ".product-stock", 
            ".availability",
            ".stock-info"
        ],
        "price": [
            ".product-price", 
            ".price-box .regular-price",
            ".price-container .price"
        ],
        "title": [
            ".product-name h1",
            ".page-title",
            ".product-details h1"
        ],
        "image": [
            ".product-img-box img",
            ".product-image-container img",
            ".gallery-image img"
        ],
        "add_to_cart_button": [
            ".add-to-cart-buttons button",
            ".add-to-cart",
            ".product-add-form button"
        ],
        "in_stock_text": [
            "En stock",
            "Disponible",
            "Expédié sous",
            "Retrait",
            "En magasin"
        ],
        "out_of_stock_text": [
            "Indisponible",
            "Rupture",
            "Épuisé",
            "Non disponible",
            "Plus en stock"
        ]
    }
}

SITES = [
    {
        "name": "Amazon France",
        "base_url": "https://www.amazon.fr",
        "type": "official",
        "country": "France",
        "priority": 1,
        "selectors": COMMON_SELECTORS["amazon"],
        "anti_bot_protection": True,
        "products": [
            # Prismatique collection
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.fr/dp/B0D35YH8CW",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collection Prismatique - Booster Display 36 boosters",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.fr/dp/B0D35YH5T3",
                "expected_price_range": [129.99, 169.99]
            },
            
            # Aventures Ensemble collection
            {
                "name": "Collection Aventures Ensemble - Coffret Dresseur d'élite",
                "collection": "Collection Aventures Ensemble",
                "url": "https://www.amazon.fr/dp/B0CD1MMYKL",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collection Aventures Ensemble - Booster Display",
                "collection": "Collection Aventures Ensemble",
                "url": "https://www.amazon.fr/dp/B0CD1K2Y9V",
                "expected_price_range": [129.99, 169.99]
            },
            
            # Eaux Florissantes collection
            {
                "name": "Collection Eaux Florissantes - Coffret Dresseur d'élite",
                "collection": "Collection Eaux Florissantes",
                "url": "https://www.amazon.fr/dp/B0BZ3Z7BF1",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collection Eaux Florissantes - Booster Display",
                "collection": "Collection Eaux Florissantes",
                "url": "https://www.amazon.fr/dp/B0C84MB8D4",
                "expected_price_range": [129.99, 169.99]
            }
        ]
    },
    {
        "name": "Amazon Italie",
        "base_url": "https://www.amazon.it",
        "type": "official",
        "country": "Italie",
        "priority": 2,
        "selectors": COMMON_SELECTORS["amazon"],
        "anti_bot_protection": True,
        "products": [
            # Prismatique collection - Italian name: "Collezione Prismatica"
            {
                "name": "Collezione Prismatica - Elite Trainer Box",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.it/dp/B0D35YH8CW",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collezione Prismatica - Display 36 buste",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.it/dp/B0D35YH5T3",
                "expected_price_range": [129.99, 169.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "Amazon Espagne",
        "base_url": "https://www.amazon.es",
        "type": "official",
        "country": "Espagne",
        "priority": 2,
        "selectors": COMMON_SELECTORS["amazon"],
        "anti_bot_protection": True,
        "products": [
            # Prismatique collection - Spanish name: "Colección Prismática"
            {
                "name": "Colección Prismática - Caja de Entrenador Élite",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.es/dp/B0D35YH8CW",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Colección Prismática - Display 36 sobres",
                "collection": "Collection Prismatique",
                "url": "https://www.amazon.es/dp/B0D35YH5T3",
                "expected_price_range": [129.99, 169.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "Fnac",
        "base_url": "https://www.fnac.com",
        "type": "official_reseller",
        "country": "France",
        "priority": 1,
        "selectors": COMMON_SELECTORS["fnac"],
        "anti_bot_protection": False,
        "products": [
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.fnac.com/a18577953/Pokemon-Coffret-Dresseur-d-Elite-Ecarlate-et-Violet-10-Collection-Prismatique",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collection Aventures Ensemble - Coffret Dresseur d'élite",
                "collection": "Collection Aventures Ensemble",
                "url": "https://www.fnac.com/a18381025/Pokemon-Coffret-Dresseur-d-Elite-Ecarlate-et-Violet-09-Collection-Aventures-Ensemble",
                "expected_price_range": [39.99, 59.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "Cultura",
        "base_url": "https://www.cultura.com",
        "type": "official_reseller",
        "country": "France",
        "priority": 1,
        "selectors": COMMON_SELECTORS["cultura"],
        "anti_bot_protection": False,
        "products": [
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.cultura.com/p-pokemon-coffret-dresseur-d-elite-collection-prismatique-10-0194735603494.html",
                "expected_price_range": [39.99, 59.99]
            },
            {
                "name": "Collection Aventures Ensemble - Coffret Dresseur d'élite",
                "collection": "Collection Aventures Ensemble",
                "url": "https://www.cultura.com/p-pokemon-coffret-dresseur-d-elite-collection-aventures-ensemble-9-0194735602923.html",
                "expected_price_range": [39.99, 59.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "Carrefour",
        "base_url": "https://www.carrefour.fr",
        "type": "retailer",
        "country": "France",
        "priority": 2,
        "selectors": COMMON_SELECTORS["carrefour"],
        "anti_bot_protection": False,
        "products": [
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.carrefour.fr/p/coffret-dresseur-d-elite-pokemon-epee-et-bouclier-collection-prismatique-0194735603494",
                "expected_price_range": [39.99, 59.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "JouéClub",
        "base_url": "https://www.joueclub.fr",
        "type": "official_reseller",
        "country": "France",
        "priority": 1,
        "selectors": COMMON_SELECTORS["joueclubdrive"],
        "anti_bot_protection": False,
        "products": [
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.joueclub.fr/produit/pokemon-coffret-dresseur-d-elite-collection-prismatique.html",
                "expected_price_range": [39.99, 59.99]
            }
            # Add more products here...
        ]
    },
    {
        "name": "King Jouet",
        "base_url": "https://www.king-jouet.com",
        "type": "official_reseller",
        "country": "France",
        "priority": 1,
        "selectors": COMMON_SELECTORS["kingjouetonline"],
        "anti_bot_protection": False,
        "products": [
            {
                "name": "Collection Prismatique - Coffret Dresseur d'élite",
                "collection": "Collection Prismatique",
                "url": "https://www.king-jouet.com/jeu-jouet/jeux-societe-plateau-cartes/jeux-de-cartes/ref-991322-pokemon-coffret-dresseur-d-elite-collection-prismatique.htm",
                "expected_price_range": [39.99, 59.99]
            }
            # Add more products here...
        ]
    }
]

circuit_breakers = {}
proxy_manager = ProxyManager()

###############################################################################
#        RANDOM WAIT FUNCTION WITH TIME (NO pyautogui)                        #
###############################################################################
def random_wait(min_sec=2, max_sec=5):
    """Wait a random time to simulate human behavior."""
    duration = random.uniform(min_sec, max_sec)
    time.sleep(duration)
    return duration


###############################################################################
#           HTTP SESSION CREATION WITH RETRIES AND PROXY SUPPORT              #
###############################################################################
def create_session(site_info=None):
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


def get_user_agent():
    return random.choice(USER_AGENTS)


###############################################################################
#         NOTIFICATION FUNCTIONS (EMAIL AND TELEGRAM)                         #
###############################################################################
def send_email(subject, message, screenshots=None):
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
        logger.warning("Incomplete email configuration, email notification not sent")
        return False
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            msg = MIMEMultipart()
            msg['Subject'] = subject
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
                        logger.error(f"Error adding screenshot {i+1}: {e}")
            server.send_message(msg)
        logger.info(f"Email sent successfully: {subject}")
        return True
    except (socket.gaierror, ssl.SSLError, smtplib.SMTPException) as e:
        logger.error(f"SMTP/SSL error when sending email: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error when sending email: {e}")
        return False


def send_telegram_alert(message, screenshots=None):
    if not USE_TELEGRAM:
        logger.warning("Telegram is not configured, notification not sent")
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Missing Telegram Token or Chat ID, notification not sent")
        return False
    try:
        for attempt in range(MAX_RETRIES):
            try:
                bot = telebot.TeleBot(TELEGRAM_TOKEN)
                bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='Markdown')
                if screenshots:
                    for screenshot in screenshots:
                        try:
                            img_data = base64.b64decode(screenshot["data"])
                            caption = screenshot.get("caption", "Stock availability detected")
                            with io.BytesIO(img_data) as img_stream:
                                bot.send_photo(TELEGRAM_CHAT_ID, img_stream, caption=caption)
                        except Exception as e:
                            logger.error(f"Error sending Telegram screenshot: {e}")
                logger.info("Telegram notification sent successfully")
                return True
            except telebot.apihelper.ApiTelegramException as e:
                if "429" in str(e):
                    # Rate limit
                    if attempt < MAX_RETRIES - 1:
                        wait_time = (attempt + 1) * 5
                        logger.warning(f"Telegram rate limit, retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        raise
                else:
                    raise
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
    return False


def send_notifications(subject, message, alerts=None):
    success = False
    screenshots = []
    if alerts:
        for alert in alerts:
            if alert.get('screenshots'):
                screenshots.extend(alert['screenshots'])
    email_ok = send_email(subject, message, screenshots)
    telegram_ok = False
    if USE_TELEGRAM:
        telegram_message = f"*{subject}*\n\n"
        if alerts:
            for idx, alert in enumerate(alerts, 1):
                telegram_message += f"{idx}. *{alert['source']}*\n"
                telegram_message += f"   {alert['message']}\n"
                telegram_message += f"   [Check here]({alert['url']})\n\n"
        else:
            telegram_message += re.sub(r'\s+', ' ', message)
        telegram_ok = send_telegram_alert(telegram_message, screenshots)
    return email_ok or telegram_ok


###############################################################################
#          INITIALIZING SELENIUM BROWSER FOR COMPLEX SITES                    #
###############################################################################
def initialize_browser(force_stable_chrome_version="113"):
    """
    Initialize and return a headless Chrome browser instance.
    force_stable_chrome_version: e.g. "113", "114"...
    """
    try:
        logger.info("Initializing headless browser (Selenium)")

        # FORCE a stable version (if possible) to avoid "no such driver by url" errors
        try:
            chromedriver_autoinstaller.install(True, force_stable_chrome_version)
        except Exception as e:
            logger.warning(f"chromedriver-autoinstaller couldn't install version {force_stable_chrome_version}: {e}")
            # Try a default install
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

        # Add proxy if configured
        proxy = proxy_manager.get_selenium_proxy()
        if proxy:
            options.proxy = proxy

        service = Service()  # chrome driver
        driver = webdriver.Chrome(service=service, options=options)

        # Anti-bot patches
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]})")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US']})")

        random_wait(1, 3)
        return driver

    except Exception as e:
        logger.error(f"Error initializing browser: {e}")
        return None


###############################################################################
#     SCREENSHOT CAPTURE WITH SELENIUM (OPTIONAL - IF AVAILABLE)             #
###############################################################################
def take_screenshot(driver, highlight_elements=None):
    """Take a screenshot with Selenium and highlight specific elements if needed."""
    try:
        if not driver:
            return None

        # Highlight availability elements or price elements before taking screenshot
        if highlight_elements:
            original_styles = {}
            for element in highlight_elements:
                try:
                    original_style = driver.execute_script("return arguments[0].getAttribute('style')", element)
                    original_styles[element] = original_style or ""
                    driver.execute_script(
                        "arguments[0].setAttribute('style', arguments[1] + 'background-color: yellow; border: 2px solid red; padding: 3px;')",
                        element, original_styles[element]
                    )
                except Exception as e:
                    logger.warning(f"Could not highlight element: {e}")

        # Take screenshot
        screenshot = driver.get_screenshot_as_base64()

        # Restore original styles
        if highlight_elements:
            for element, original_style in original_styles.items():
                try:
                    driver.execute_script(
                        "arguments[0].setAttribute('style', arguments[1])",
                        element, original_style
                    )
                except Exception:
                    pass

        return screenshot
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return None


###############################################################################
#                        STANDARD CHECK (WITHOUT SELENIUM)                    #
###############################################################################
def check_site_standard(site_info, product_info):
    try:
        session = create_session(site_info)
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://www.google.com/search?q=pokemon+jcc+collection",
        }
        if 'specific_headers' in site_info:
            headers.update(site_info['specific_headers'])

        cookies = {
            "visited": "true",
            "cookie_consent": "accepted",
            "session": f"session_{random.randint(10000, 99999)}",
            "language": "fr"
        }

        logger.info(f"Accessing {product_info['url']}")
        response = session.get(product_info['url'], headers=headers, cookies=cookies, timeout=30)
        random_wait(1, 2)

        if response.status_code != 200:
            msg = f"HTTP Error {response.status_code} on {site_info['name']} for {product_info['name']}"
            logger.warning(msg)
            return False, msg, [], {}

        # Parse HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        selectors = site_info['selectors']
        product_data = {
            "title": None,
            "price": None,
            "availability": None,
            "image_url": None,
            "buy_url": product_info['url']
        }

        # Extract product title
        for title_selector in selectors['title']:
            title_element = soup.select_one(title_selector)
            if title_element:
                product_data["title"] = title_element.get_text().strip()
                break

        # Extract product price
        for price_selector in selectors['price']:
            price_element = soup.select_one(price_selector)
            if price_element:
                price_text = price_element.get_text().strip()
                # Remove currency symbols and convert to float
                price_text = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
                try:
                    price_match = re.search(r'\d+\.\d+', price_text)
                    if price_match:
                        product_data["price"] = float(price_match.group(0))
                except (ValueError, AttributeError):
                    pass
                break

        # Extract product image
        for img_selector in selectors['image']:
            img_element = soup.select_one(img_selector)
            if img_element and img_element.has_attr('src'):
                img_url = img_element['src']
                # Make absolute URL if it's relative
                if img_url.startswith('/'):
                    img_url = site_info['base_url'] + img_url
                product_data["image_url"] = img_url
                break

        # Check availability - combine multiple approaches
        in_stock = False
        availability_text = ""
        
        # 1. Check via selectors
        for avail_selector in selectors['availability']:
            avail_element = soup.select_one(avail_selector)
            if avail_element:
                availability_text = avail_element.get_text().strip()
                # Check positive indicators
                for in_stock_phrase in selectors['in_stock_text']:
                    if in_stock_phrase.lower() in availability_text.lower():
                        in_stock = True
                        break
                # Check negative indicators
                for out_of_stock_phrase in selectors['out_of_stock_text']:
                    if out_of_stock_phrase.lower() in availability_text.lower():
                        in_stock = False
                        break
                break
        
        # 2. Check for add to cart button
        if not in_stock:
            for cart_selector in selectors['add_to_cart_button']:
                cart_button = soup.select_one(cart_selector)
                if cart_button and not cart_button.has_attr('disabled'):
                    in_stock = True
                    availability_text = "Add to cart button is enabled"
                    break
        
        # 3. Check content for availability indicators
        if not availability_text:
            content = response.text.lower()
            for in_stock_phrase in selectors['in_stock_text']:
                if in_stock_phrase.lower() in content:
                    in_stock = True
                    availability_text = in_stock_phrase
                    break
            if not in_stock:
                for out_of_stock_phrase in selectors['out_of_stock_text']:
                    if out_of_stock_phrase.lower() in content:
                        availability_text = out_of_stock_phrase
                        break

        product_data["availability"] = availability_text

        # Generate success message if in stock
        if in_stock:
            price_info = f" at {product_data['price']}€" if product_data["price"] else ""
            msg = f"IN STOCK: {product_info['name']}{price_info}"
            logger.info(msg)
            return True, msg, [], product_data
        else:
            msg = f"Not available: {product_info['name']} - {availability_text}"
            logger.info(msg)
            return False, msg, [], product_data

    except requests.exceptions.RequestException as e:
        err_msg = f"Connection error to {site_info['name']} for {product_info['name']}: {e}"
        logger.error(err_msg)
        return False, err_msg, [], {}
    except Exception as e:
        err_msg = f"Error checking {site_info['name']} for {product_info['name']}: {e}"
        logger.error(err_msg)
        return False, err_msg, [], {}


###############################################################################
#           CLOUDSCRAPER CHECK (SITES WITH CLOUDFLARE)                        #
###############################################################################
def check_site_with_cloudscraper(site_info, product_info):
    logger.info(f"Checking {site_info['name']} for {product_info['name']} with CloudScraper")
    site_name = site_info['name']
    product_name = product_info['name']
    circuit_breaker_key = f"{site_name}_{product_name}"
    
    if circuit_breaker_key not in circuit_breakers:
        circuit_breakers[circuit_breaker_key] = CircuitBreaker(circuit_breaker_key)
    if not circuit_breakers[circuit_breaker_key].allow_request():
        return False, f"Circuit breaker open for {site_name} - {product_name}", [], {}

    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True},
            delay=5
        )
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/search?q=pokemon+jcc+collection",
        }
        cookies = {
            "visited": "true",
            "session": f"session_{random.randint(10000, 99999)}",
            "language": "fr"
        }
        proxies = proxy_manager.get_proxy_dict()
        response = scraper.get(product_info['url'], headers=headers, cookies=cookies, proxies=proxies, timeout=30)
        random_wait(1, 2)

        if response.status_code != 200:
            circuit_breakers[circuit_breaker_key].record_failure()
            return False, f"HTTP Error {response.status_code} on {site_name} for {product_name}", [], {}

        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        selectors = site_info['selectors']
        product_data = {
            "title": None,
            "price": None,
            "availability": None,
            "image_url": None,
            "buy_url": product_info['url']
        }

        # Extract product title
        for title_selector in selectors['title']:
            title_element = soup.select_one(title_selector)
            if title_element:
                product_data["title"] = title_element.get_text().strip()
                break

        # Extract product price
        for price_selector in selectors['price']:
            price_element = soup.select_one(price_selector)
            if price_element:
                price_text = price_element.get_text().strip()
                # Remove currency symbols and convert to float
                price_text = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
                try:
                    price_match = re.search(r'\d+\.\d+', price_text)
                    if price_match:
                        product_data["price"] = float(price_match.group(0))
                except (ValueError, AttributeError):
                    pass
                break

        # Extract product image
        for img_selector in selectors['image']:
            img_element = soup.select_one(img_selector)
            if img_element and img_element.has_attr('src'):
                img_url = img_element['src']
                # Make absolute URL if it's relative
                if img_url.startswith('/'):
                    img_url = site_info['base_url'] + img_url
                product_data["image_url"] = img_url
                break

        # Check availability
        in_stock = False
        availability_text = ""
        
        # 1. Check via selectors
        for avail_selector in selectors['availability']:
            avail_element = soup.select_one(avail_selector)
            if avail_element:
                availability_text = avail_element.get_text().strip()
                # Check positive indicators
                for in_stock_phrase in selectors['in_stock_text']:
                    if in_stock_phrase.lower() in availability_text.lower():
                        in_stock = True
                        break
                # Check negative indicators
                for out_of_stock_phrase in selectors['out_of_stock_text']:
                    if out_of_stock_phrase.lower() in availability_text.lower():
                        in_stock = False
                        break
                break
        
        # 2. Check for add to cart button
        if not in_stock:
            for cart_selector in selectors['add_to_cart_button']:
                cart_button = soup.select_one(cart_selector)
                if cart_button and not cart_button.has_attr('disabled'):
                    in_stock = True
                    availability_text = "Add to cart button is enabled"
                    break

        product_data["availability"] = availability_text

        circuit_breakers[circuit_breaker_key].record_success()
        
        # Generate message and screenshots
        if in_stock:
            price_info = f" at {product_data['price']}€" if product_data["price"] else ""
            msg = f"IN STOCK: {product_name}{price_info} on {site_name}"
            return True, msg, [], product_data
        else:
            msg = f"Not available: {product_name} on {site_name} - {availability_text}"
            return False, msg, [], product_data

    except Exception as e:
        circuit_breakers[circuit_breaker_key].record_failure()
        return False, f"CloudScraper Error for {site_name} - {product_name}: {e}", [], {}


###############################################################################
#          SELENIUM CHECK (SITES WITH STRONG PROTECTION)                      #
###############################################################################
def check_site_with_selenium(site_info, product_info):
    logger.info(f"Checking {site_info['name']} for {product_info['name']} with Selenium")
    site_name = site_info['name']
    product_name = product_info['name']
    circuit_breaker_key = f"{site_name}_{product_name}"
    
    if circuit_breaker_key not in circuit_breakers:
        circuit_breakers[circuit_breaker_key] = CircuitBreaker(circuit_breaker_key)
    if not circuit_breakers[circuit_breaker_key].allow_request():
        return False, f"Circuit breaker open for {site_name} - {product_name}", [], {}

    driver = None
    try:
        driver = initialize_browser()
        if not driver:
            circuit_breakers[circuit_breaker_key].record_failure()
            return False, f"Could not initialize browser for {site_name} - {product_name}", [], {}

        driver.get(product_info['url'])
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        random_wait(1, 2)

        selectors = site_info['selectors']
        product_data = {
            "title": None,
            "price": None,
            "availability": None,
            "image_url": None,
            "buy_url": product_info['url']
        }
        
        highlight_elements = []

        # Extract product title
        for title_selector in selectors['title']:
            try:
                title_elements = driver.find_elements(By.CSS_SELECTOR, title_selector)
                if title_elements:
                    product_data["title"] = title_elements[0].text.strip()
                    break
            except Exception:
                continue

        # Extract product price
        for price_selector in selectors['price']:
            try:
                price_elements = driver.find_elements(By.CSS_SELECTOR, price_selector)
                if price_elements:
                    price_text = price_elements[0].text.strip()
                    # Remove currency symbols and convert to float
                    price_text = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
                    try:
                        price_match = re.search(r'\d+\.\d+', price_text)
                        if price_match:
                            product_data["price"] = float(price_match.group(0))
                    except (ValueError, AttributeError):
                        pass
                    highlight_elements.append(price_elements[0])
                    break
            except Exception:
                continue

        # Extract product image
        for img_selector in selectors['image']:
            try:
                img_elements = driver.find_elements(By.CSS_SELECTOR, img_selector)
                if img_elements and img_elements[0].get_attribute('src'):
                    img_url = img_elements[0].get_attribute('src')
                    # Make absolute URL if it's relative
                    if img_url.startswith('/'):
                        img_url = site_info['base_url'] + img_url
                    product_data["image_url"] = img_url
                    break
            except Exception:
                continue

        # Check availability
        in_stock = False
        availability_text = ""
        availability_element = None
        
        # 1. Check via selectors
        for avail_selector in selectors['availability']:
            try:
                avail_elements = driver.find_elements(By.CSS_SELECTOR, avail_selector)
                if avail_elements:
                    availability_element = avail_elements[0]
                    availability_text = availability_element.text.strip()
                    highlight_elements.append(availability_element)
                    
                    # Check positive indicators
                    for in_stock_phrase in selectors['in_stock_text']:
                        if in_stock_phrase.lower() in availability_text.lower():
                            in_stock = True
                            break
                    
                    # Check negative indicators
                    for out_of_stock_phrase in selectors['out_of_stock_text']:
                        if out_of_stock_phrase.lower() in availability_text.lower():
                            in_stock = False
                            break
                    break
            except Exception:
                continue
        
        # 2. Check for add to cart button
        cart_button = None
        if not in_stock:
            for cart_selector in selectors['add_to_cart_button']:
                try:
                    cart_buttons = driver.find_elements(By.CSS_SELECTOR, cart_selector)
                    if cart_buttons and not cart_buttons[0].get_attribute('disabled'):
                        cart_button = cart_buttons[0]
                        in_stock = True
                        availability_text = "Add to cart button is enabled"
                        highlight_elements.append(cart_button)
                        break
                except Exception:
                    continue

        product_data["availability"] = availability_text

        # Take screenshot with highlighted elements
        screenshots = []
        screenshot_data = take_screenshot(driver, highlight_elements)
        if screenshot_data:
            caption = f"{product_name} on {site_name} - {'IN STOCK' if in_stock else 'Not available'}"
            screenshots.append({"data": screenshot_data, "caption": caption})

        circuit_breakers[circuit_breaker_key].record_success()
        
        if in_stock:
            price_info = f" at {product_data['price']}€" if product_data["price"] else ""
            msg = f"IN STOCK: {product_name}{price_info} on {site_name}"
            return True, msg, screenshots, product_data
        else:
            msg = f"Not available: {product_name} on {site_name} - {availability_text}"
            return False, msg, screenshots, product_data

    except TimeoutException:
        circuit_breakers[circuit_breaker_key].record_failure()
        return False, f"Timeout on {site_name} for {product_name}", [], {}
    except WebDriverException as e:
        circuit_breakers[circuit_breaker_key].record_failure()
        return False, f"WebDriver Error for {site_name} - {product_name}: {e}", [], {}
    except Exception as e:
        circuit_breakers[circuit_breaker_key].record_failure()
        return False, f"Selenium Error for {site_name} - {product_name}: {e}", [], {}
    finally:
        if driver:
            driver.quit()


###############################################################################
#                   GLOBAL SITE CHECK FUNCTION                                #
###############################################################################
def check_site_product(site_info, product_info):
    # Detect anti-bot protection + priority usage
    if site_info.get('anti_bot_protection'):
        # Try cloudscraper first, then selenium if it fails
        available, msg, screenshots, product_data = check_site_with_cloudscraper(site_info, product_info)
        if "Error" in msg or not available:
            available2, msg2, screenshots2, product_data2 = check_site_with_selenium(site_info, product_info)
            if screenshots2:
                screenshots.extend(screenshots2)
            if product_data2 and product_data2.get("title"):
                product_data = product_data2
            return available2, msg2, screenshots, product_data
        else:
            return available, msg, screenshots, product_data
    else:
        # Otherwise use standard version or selenium based on site type
        if site_info.get('type') in ['official', 'official_reseller'] and site_info.get('priority', 999) <= 2:
            # E.g., try standard first, then selenium
            available, msg, screenshots, product_data = check_site_standard(site_info, product_info)
            if not available and "Error" in msg:
                # As a last resort
                available2, msg2, screenshots2, product_data2 = check_site_with_selenium(site_info, product_info)
                if screenshots2:
                    screenshots.extend(screenshots2)
                if product_data2 and product_data2.get("title"):
                    product_data = product_data2
                return available2, msg2, screenshots, product_data
            return available, msg, screenshots, product_data
        else:
            # Simple
            return check_site_standard(site_info, product_info)


###############################################################################
#                        MAIN PROGRAM FUNCTION                                #
###############################################################################
def main_program():
    logger.info(f"Bot started - Monitoring Pokemon card collections")
    counter = 0
    while True:
        try:
            counter += 1
            now = datetime.now()
            logger.info(f"Check #{counter} - {now}")
            check_interval = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)

            alerts = []
            for site in SITES:
                logger.info(f"Checking site: {site['name']}")
                for product in site['products']:
                    available, message, screenshots, product_data = check_site_product(site, product)
                    
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
                        logger.info(f"DETECTION - {site['name']} for {product['name']}: {message}")
                    else:
                        logger.info(f"{site['name']} for {product['name']}: {message}")

                    time.sleep(1)  # Small pause between products

                time.sleep(2)  # Small pause between sites

            if alerts:
                subject = f"ALERT - Pokemon cards in stock!"
                text = f"Stock availability detected for Pokemon collections.\n\n"
                for idx, al in enumerate(alerts, 1):
                    text += f"{idx}. {al['source']} -> {al['product_name']}\n"
                    if al['product_data'].get('price'):
                        text += f"   Price: {al['product_data']['price']}€\n"
                    text += f"   Url: {al['url']}\n\n"
                send_notifications(subject, text, alerts)

            next_check = now + timedelta(seconds=check_interval)
            logger.info(f"Next check: {next_check.strftime('%H:%M:%S')} (in {check_interval} s)")
            time.sleep(check_interval)

        except KeyboardInterrupt:
            logger.info("Bot stopped manually.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(RETRY_INTERVAL)


###############################################################################
#                    VERSION SIMPLIFIÉE POUR RENDER                           #
###############################################################################
def check_single_site():
    """Version simplifiée qui vérifie uniquement un site prioritaire."""
    now = datetime.now()
    logger.info(f"Simplified check at {now.strftime('%d/%m/%Y %H:%M:%S')}")
    
    # Sélectionner un site prioritaire (Amazon France)
    priority_site = next((site for site in SITES if site['name'] == 'Amazon France'), SITES[0])
    
    # Vérifier uniquement ce site
    for product in priority_site['products'][:3]:  # Limite à 3 produits pour économiser des ressources
        try:
            available, message, screenshots, product_data = check_site_product(priority_site, product)
            logger.info(f"{priority_site['name']} for {product['name']}: {message}")
            
            # Si disponible, envoyer des notifications
            if available:
                subject = f"ALERT - Pokemon cards in stock!"
                text = f"Stock availability detected for {product['name']} on {priority_site['name']}.\n\n"
                text += f"Price: {product_data.get('price', 'N/A')}€\n"
                text += f"URL: {product['url']}\n\n"
                
                alerts = [{
                    "source": priority_site["name"],
                    "product_name": product["name"],
                    "collection": product["collection"],
                    "message": message,
                    "url": product["url"],
                    "screenshots": screenshots,
                    "product_data": product_data
                }]
                
                send_notifications(subject, text, alerts)
                logger.info(f"ALERT SENT for {product['name']}")
        except Exception as e:
            logger.error(f"Error checking {priority_site['name']} for {product['name']}: {e}")
        
        # Pause between requests
        time.sleep(5)


###############################################################################
#                ENTRY POINT IF RUNNING THIS FILE DIRECTLY                    #
###############################################################################
if __name__ == "__main__":
    try:
        # Basic checks
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Incomplete or missing Telegram configuration.")
        main_program()
    except KeyboardInterrupt:
        logger.info("Manual stop.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
