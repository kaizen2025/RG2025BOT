#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import time
import smtplib
from email.mime.text import MIMEText
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

# Nouvelle importation pour contourner les protections (remplace Selenium)
import cloudscraper
from lxml import html
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54'
]

# Liste améliorée des sites à surveiller (cf. l'original)
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
        "mots_cles_additionnels": ["billets finales", "week-end final", "derniers jours"]
    },
    {
        "nom": "Fnac Billetterie",
        "url": "https://www.fnacspectacles.com/place-spectacle/sport/tennis/roland-garros/",
        "type": "revendeur_officiel",
        "priorité": 2,
        "selectors": {
            "liste_events": ".events-list, .event-card, .event-item",
            "date_items": ".event-date, .date, .datetime",
            "prix": ".price, .tarif, .amount",
            "disponibilite": ".availability, .status, .stock-status"
        },
        "anti_bot_protection": True
    },
    {
        "nom": "Viagogo",
        "url": "https://www.viagogo.fr/Billets-Sport/Tennis/Roland-Garros-Internationaux-de-France-de-Tennis-Billets",
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
        }
    },
    {
        "nom": "Ticketmaster",
        "url": "https://www.ticketmaster.fr/fr/resultat?ipSearch=roland+garros",
        "type": "revendeur_officiel",
        "priorité": 2,
        "selectors": {
            "liste_events": ".event-list, .search-results, .events-container",
            "date_items": ".event-date, .date, [data-date]",
            "prix": ".price, .amount, .ticket-price",
            "disponibilite": ".availability, .status, .tickets-available"
        },
        "api_url": "https://www.ticketmaster.fr/api/v1/events/search?q=roland%20garros"
    },
    {
        "nom": "StubHub",
        "url": "https://www.stubhub.fr/roland-garros-billets/ca6873/",
        "type": "revente",
        "priorité": 3,
        "selectors": {
            "liste_events": ".event-listing, .events-list",
            "date_items": ".event-date, .date-display",
            "prix": ".price, .amount",
            "disponibilite": ".availability, .ticket-count"
        },
        "anti_bot_protection": True
    },
    {
        "nom": "Billetréduc",
        "url": "https://www.billetreduc.com/recherche.htm?q=roland+garros",
        "type": "reduction",
        "priorité": 3
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
        "ajax_api": "https://tickets.fft.fr/api/availability/dates?event=roland-garros",
        "headers_specifiques": {
            "X-Requested-With": "XMLHttpRequest"
        }
    },
    {
        "nom": "Rakuten Billets",
        "url": "https://fr.shopping.rakuten.com/event/roland-garros",
        "type": "revente",
        "priorité": 3,
        "selectors": {
            "liste_billets": ".listing, .event-tickets",
            "date_items": ".event-date, .ticket-date",
            "prix": ".price, .ticket-price",
            "disponibilite": ".available, .status"
        },
        "mots_cles_additionnels": ["mai 2025", "31/05", "samedi"]
    },
    {
        "nom": "Seetickets",
        "url": "https://www.seetickets.com/fr/search?q=roland+garros",
        "type": "revendeur_officiel",
        "priorité": 3,
        "selectors": {
            "liste_events": ".search-results, .events-list",
            "date_items": ".event-date, .date",
            "prix": ".price, .amount",
            "disponibilite": ".status, .availability"
        }
    },
    {
        "nom": "Eventim",
        "url": "https://www.eventim.fr/search/?affiliate=FES&searchterm=roland+garros",
        "type": "revendeur_officiel",
        "priorité": 3,
        "selectors": {
            "liste_events": ".eventlist, .search-results",
            "date_items": ".date, .event-date",
            "prix": ".price, .amount",
            "disponibilite": ".availability, .status"
        }
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
MOTS_CLES_REVENTE = [
    "roland garros 31 mai", "31 mai 2025", "samedi 31 mai",
    "roland garros weekend", "derniers jours", "demi-finales",
    "billet disponible", "ticket disponible", "disponibilités"
]

# Créer une session HTTP réutilisable avec retry
def creer_session():
    """Crée une session HTTP avec paramètres de retry."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=RETRY_STATUS_FORCELIST,
        allowed_methods=["GET", "HEAD", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def obtenir_user_agent():
    """Renvoie un User-Agent aléatoire."""
    return random.choice(USER_AGENTS)

def envoyer_email(sujet, message):
    """Envoie un email de notification."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
        logger.warning("Configuration email incomplète, notification non envoyée")
        return False
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP('smtp.gmail.com', 587) as serveur:
            serveur.ehlo()
            serveur.starttls(context=context)
            serveur.ehlo()
            serveur.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            msg = MIMEText(message)
            msg['Subject'] = sujet
            msg['From'] = EMAIL_ADDRESS
            msg['To'] = EMAIL_RECIPIENT
            serveur.send_message(msg)
        logger.info(f"Email envoyé avec succès: {sujet}")
        return True
    except socket.gaierror as e:
        logger.error(f"Erreur de résolution DNS: {e}")
        return False
    except ssl.SSLError as e:
        logger.error(f"Erreur SSL: {e}")
        return False
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Erreur d'authentification SMTP: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"Erreur SMTP: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'envoi de l'email: {e}")
        return False

def envoyer_alerte_telegram(message):
    """Envoie une notification via Telegram."""
    if not UTILISER_TELEGRAM or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Configuration Telegram incomplète, alerte non envoyée")
        return False
    try:
        for tentative in range(MAX_RETRIES):
            try:
                bot = telebot.TeleBot(TELEGRAM_TOKEN)
                bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='Markdown')
                logger.info("Notification Telegram envoyée avec succès")
                return True
            except telebot.apihelper.ApiTelegramException as e:
                if "429" in str(e) and tentative < MAX_RETRIES - 1:
                    attente = (tentative + 1) * 5
                    logger.warning(f"Rate limit Telegram, nouvel essai dans {attente} secondes...")
                    time.sleep(attente)
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
    """Renvoie les instructions de configuration du bot Telegram."""
    instructions = f"""
=== CONFIGURATION DU BOT TELEGRAM ===

1. Ouvrez Telegram et recherchez BotFather (@BotFather)
2. Envoyez la commande /newbot et suivez les instructions pour créer un nouveau bot
3. Copiez le TOKEN fourni et remplacez "votre_token_bot_telegram" dans ce script
4. Envoyez un message au bot pour obtenir votre CHAT_ID via https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates
5. Remplacez "votre_chat_id" dans ce script par le CHAT_ID obtenu

Le bot surveille Roland-Garros pour le {DATE_CIBLE} et vous alertera dès qu'une disponibilité est détectée.
"""
    logger.info("Instructions Telegram générées")
    return instructions

def analyser_json_pour_disponibilite(json_data):
    """
    Analyse un objet JSON pour y trouver des indices de disponibilité pour le 31 mai.
    Retourne un tuple (score, liste de mots-clés trouvés).
    """
    score = 0
    mots_trouves = []
    def explorer_json(obj, chemin=""):
        nonlocal score, mots_trouves
        if isinstance(obj, dict):
            date_cible_trouvee = False
            dispo_trouvee = False
            for key, value in obj.items():
                key_lower = str(key).lower()
                if 'date' in key_lower or 'jour' in key_lower or 'day' in key_lower:
                    if '31/05' in str(value).lower() or '31-05' in str(value).lower() or '31 mai' in str(value).lower() or '2025-05-31' in str(value).lower():
                        date_cible_trouvee = True
                        mots_trouves.append(f"date 31 mai trouvée dans JSON à {chemin}.{key}")
                elif any(term in key_lower for term in ['disponible', 'available', 'status', 'bookable', 'stock']):
                    if str(value).lower() in ['true', '1', 'yes', 'disponible', 'available', 'en stock', 'in stock']:
                        dispo_trouvee = True
                        mots_trouves.append(f"disponibilité trouvée dans JSON à {chemin}.{key}")
            if date_cible_trouvee and dispo_trouvee:
                score += 5
                mots_trouves.append("date 31 mai ET disponibilité trouvées dans le même objet JSON")
            for k, v in obj.items():
                explorer_json(v, f"{chemin}.{k}" if chemin else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                explorer_json(item, f"{chemin}[{i}]")
    explorer_json(json_data)
    return score, mots_trouves

# ***************** Modification majeure *****************
# Suppression totale de Selenium.
# La fonction verifier_site_ameliore utilise uniquement cloudscraper.
def verifier_site_ameliore(site_info):
    """
    Vérifie un site en utilisant cloudscraper exclusivement.
    Cette version remplace l'ancienne logique Selenium.
    Retourne un tuple (disponible, message).
    """
    try:
        logger.info(f"Vérification de {site_info['nom']} via Cloudscraper")
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
            delay=5
        )
        headers = {
            'User-Agent': obtenir_user_agent(),
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
            'session': f'session_{random.randint(10000,99999)}',
            'language': 'fr'
        }
        logger.info(f"Accès à {site_info['url']} via Cloudscraper")
        response = scraper.get(site_info['url'], headers=headers, cookies=cookies, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Erreur HTTP {response.status_code} sur {site_info['nom']}")
            return False, f"Erreur HTTP {response.status_code} sur {site_info['nom']}"
        soup = BeautifulSoup(response.text, 'html.parser')
        lxml_tree = html.fromstring(response.content)
        contenu_page = soup.get_text().lower()
        mots_trouves = []
        score = 0
        # Vérifier la présence de la date cible
        if any(date_format in contenu_page for date_format in ["31 mai", "31/05/2025", "31/05", "samedi 31"]):
            mots_trouves.append("date du 31 mai trouvée dans la page")
            score += 5
        selectors = site_info.get('selectors', {})
        # Vérifier calendrier
        if 'calendrier' in selectors:
            for cal in soup.select(selectors['calendrier']):
                if '31' in cal.get_text().lower() and ('mai' in cal.get_text().lower() or '05' in cal.get_text().lower()):
                    score += 3
                    mots_trouves.append("calendrier avec 31 mai détecté")
                    classes = cal.get('class', [])
                    if any('available' in c or 'bookable' in c or 'in-stock' in c for c in classes):
                        score += 3
                        mots_trouves.append("jour 31 mai marqué comme disponible")
        # Vérifier éléments de date
        if 'date_items' in selectors:
            for date_elem in soup.select(selectors['date_items']):
                if '31' in date_elem.get_text().lower() and ('mai' in date_elem.get_text().lower() or '05' in date_elem.get_text().lower()):
                    score += 2
                    mots_trouves.append("élément de date 31 mai détecté")
                    parent = date_elem.find_parent()
                    if parent and any(term in str(parent).lower() for term in ['disponible', 'available', 'acheter', 'buy']):
                        score += 3
                        mots_trouves.append("date 31 mai associée à une disponibilité")
        # Vérifier boutons d'achat
        if 'achat_buttons' in selectors:
            for bouton in soup.select(selectors['achat_buttons']):
                if any(term in bouton.get_text().lower() for term in ['acheter', 'réserver', 'buy', 'book']):
                    score += 1
                    mots_trouves.append("bouton d'achat détecté")
                    parent = bouton.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent and ('31 mai' in parent.get_text().lower() or '31/05' in parent.get_text().lower()):
                        score += 4
                        mots_trouves.append("bouton d'achat pour le 31 mai")
        # Vérifier indicateurs de disponibilité
        if 'disponibilite' in selectors:
            for disp in soup.select(selectors['disponibilite']):
                if any(term in disp.get_text().lower() for term in ['disponible', 'available', 'en stock']):
                    parent = disp.find_parent('div', class_=lambda c: c and ('event' in c or 'ticket' in c))
                    if parent and ('31 mai' in parent.get_text().lower() or '31/05' in parent.get_text().lower()):
                        score += 5
                        mots_trouves.append("disponibilité explicite pour le 31 mai")
        # Mots-clés additionnels
        for mot in site_info.get('mots_cles_additionnels', []):
            if mot.lower() in contenu_page:
                mots_trouves.append(f"mot-clé '{mot}' trouvé")
                score += 1
        # Vérifier API associée si définie
        if 'api_url' in site_info:
            try:
                api_headers = headers.copy()
                api_headers['Accept'] = 'application/json'
                api_response = scraper.get(site_info['api_url'], headers=api_headers, cookies=cookies, timeout=20)
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
        # Recherche dans les scripts intégrés
        for script in soup.find_all('script'):
            script_content = script.string if script.string else ''
            if script_content:
                json_matches = re.findall(r'({[^{]*?"date.*?})', script_content)
                for json_str in json_matches:
                    try:
                        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_]+):', r'\1"\2":', json_str)
                        json_data = json.loads(json_str)
                        if isinstance(json_data, dict):
                            for k, v in json_data.items():
                                if 'date' in k.lower() and ('31/05' in str(v).lower() or '31 mai' in str(v).lower()):
                                    for key, value in json_data.items():
                                        if any(x in key.lower() for x in ['disponible', 'available', 'status']) and str(value).lower() in ['true', '1', 'yes', 'disponible', 'available']:
                                            score += 4
                                            mots_trouves.append("données JSON indiquant disponibilité pour le 31 mai")
                    except Exception:
                        pass
        # Recherche XPath avec lxml
        try:
            xpath_dispo = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//*[contains(@class, 'available') or contains(@class, 'dispo')]"
            elems = lxml_tree.xpath(xpath_dispo)
            if elems:
                score += 4
                mots_trouves.append(f"{len(elems)} éléments de disponibilité trouvés par XPath")
            xpath_boutons = "//div[contains(text(), '31 mai') or contains(text(), '31/05')]//button[contains(text(), 'Acheter') or contains(text(), 'Réserver') or contains(text(), 'Buy')]"
            boutons = lxml_tree.xpath(xpath_boutons)
            if boutons:
                score += 3
                mots_trouves.append(f"{len(boutons)} boutons d'achat trouvés par XPath")
        except Exception as e:
            logger.warning(f"Erreur lors de l'analyse XPath: {e}")
        # Définir le seuil de détection
        seuil_detection = 5
        if site_info['type'] == 'officiel':
            seuil_detection = 6
        elif site_info['type'] == 'revente':
            seuil_detection = 4
        if score >= seuil_detection:
            details = ", ".join(mots_trouves)
            return True, f"Disponibilité détectée sur {site_info['nom']} (score: {score}/10) - Éléments trouvés: {details}"
        else:
            return False, f"Aucune disponibilité détectée sur {site_info['nom']} (score: {score}/10)"
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de requête sur {site_info['nom']}: {e}")
        return False, f"Erreur de connexion à {site_info['nom']}: {e}"
    except Exception as e:
        logger.error(f"Erreur non gérée lors de la vérification de {site_info['nom']}: {e}")
        return False, f"Erreur lors de la vérification de {site_info['nom']}: {str(e)}"

# Fonction pour vérifier tous les sites en parallèle
def verifier_sites_en_parallele(sites, max_workers=5):
    """
    Vérifie plusieurs sites en parallèle pour améliorer la performance.
    Retourne une liste de résultats.
    """
    resultats = []
    sites_par_priorite = {}
    for site in sites:
        priorite = site.get('priorité', 999)
        sites_par_priorite.setdefault(priorite, []).append(site)
    for priorite in sorted(sites_par_priorite.keys()):
        sites_groupe = sites_par_priorite[priorite]
        if priorite == 1:
            logger.info(f"Vérification séquentielle des {len(sites_groupe)} sites de priorité 1")
            for site in sites_groupe:
                try:
                    dispo, msg = verifier_site_ameliore(site)
                    resultats.append({
                        "source": site["nom"],
                        "disponible": dispo,
                        "message": msg,
                        "url": site["url"],
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.info(f"{site['nom']}: {msg}")
                except Exception as e:
                    logger.error(f"Erreur sur {site['nom']}: {e}")
                    resultats.append({
                        "source": site["nom"],
                        "disponible": False,
                        "message": f"Erreur: {e}",
                        "url": site["url"],
                        "timestamp": datetime.now().isoformat()
                    })
                time.sleep(random.uniform(1, 3))
        else:
            logger.info(f"Vérification parallèle des {len(sites_groupe)} sites de priorité {priorite}")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_site = {executor.submit(verifier_site_ameliore, site): site for site in sites_groupe}
                for future in as_completed(future_to_site):
                    site = future_to_site[future]
                    try:
                        dispo, msg = future.result()
                        resultats.append({
                            "source": site["nom"],
                            "disponible": dispo,
                            "message": msg,
                            "url": site["url"],
                            "timestamp": datetime.now().isoformat()
                        })
                        logger.info(f"{site['nom']}: {msg}")
                    except Exception as e:
                        logger.error(f"Erreur sur {site['nom']}: {e}")
                        resultats.append({
                            "source": site["nom"],
                            "disponible": False,
                            "message": f"Erreur: {e}",
                            "url": site["url"],
                            "timestamp": datetime.now().isoformat()
                        })
            time.sleep(random.uniform(2, 5))
    return resultats

# Fonction pour vérifier les requêtes XHR potentielles du site Roland-Garros
def verifier_requests_xhr_roland_garros():
    """
    Tente de simuler les requêtes XHR faites par le site officiel de Roland-Garros.
    Retourne un tuple (disponible, message).
    """
    try:
        logger.info("Tentative de vérification des requêtes XHR de Roland-Garros")
        urls = [
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
        for url in urls:
            try:
                logger.info(f"Requête GET sur {url}")
                resp = session.get(url, headers=headers, cookies=cookies, timeout=20)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if isinstance(data, dict):
                            for key, value in data.items():
                                if ('disponible' in key.lower() or 'available' in key.lower()) and value:
                                    return True, f"Disponibilité détectée via GET XHR: {url}"
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and 'date' in item and ('31/05' in str(item['date']) or '2025-05-31' in str(item['date'])):
                                    if item.get('available', item.get('disponible', False)):
                                        return True, f"Disponibilité détectée via GET XHR: {url}"
                    except ValueError:
                        if '31 mai' in resp.text and any(term in resp.text.lower() for term in ['disponible', 'available']):
                            return True, f"Indices de disponibilité via GET XHR: {url}"
                time.sleep(random.uniform(1, 3))
                for payload in data_potentielles:
                    try:
                        logger.info(f"Requête POST sur {url}")
                        resp = session.post(url, headers=headers, cookies=cookies, json=payload, timeout=20)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict):
                                    for key, value in data.items():
                                        if ('disponible' in key.lower() or 'available' in key.lower()) and value:
                                            return True, f"Disponibilité détectée via POST XHR: {url}"
                            except ValueError:
                                pass
                    except requests.exceptions.RequestException:
                        continue
                    time.sleep(random.uniform(1, 3))
            except requests.exceptions.RequestException:
                continue
        return False, "Aucune info XHR détectée"
    except Exception as e:
        logger.error(f"Erreur XHR: {e}")
        return False, f"Erreur XHR: {e}"

def verifier_twitter():
    """
    Vérifie les tweets récents mentionnant Roland-Garros et les billets pour le 31 mai.
    Retourne (disponible, message).
    """
    try:
        url = "https://nitter.net/search?f=tweets&q=roland+garros+billets+31+mai"
        headers = {'User-Agent': obtenir_user_agent()}
        session = creer_session()
        try:
            resp = session.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur de requête sur Twitter: {e}")
            return False, f"Erreur de connexion à Twitter: {e}"
        if resp.status_code != 200:
            logger.warning(f"Erreur HTTP {resp.status_code} sur Twitter")
            return False, f"Erreur accès Twitter: {resp.status_code}"
        try:
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            logger.error(f"Erreur parsing Twitter: {e}")
            return False, f"Erreur analyse Twitter: {e}"
        tweets_recents = soup.select('.timeline-item')
        tweets_pertinents = []
        for tweet in tweets_recents[:10]:
            try:
                texte = tweet.get_text().lower()
                date_tweet = tweet.select_one('.tweet-date')
                if date_tweet and "h" in date_tweet.get_text():
                    if any(mot in texte for mot in MOTS_CLES + MOTS_CLES_REVENTE) and "31 mai" in texte:
                        tweets_pertinents.append(texte)
            except Exception as e:
                logger.warning(f"Erreur analyse tweet: {e}")
                continue
        if tweets_pertinents:
            return True, f"{len(tweets_pertinents)} tweets pertinents trouvés"
        return False, "Aucun tweet pertinent trouvé"
    except Exception as e:
        logger.error(f"Erreur Twitter: {e}")
        return False, f"Erreur Twitter: {e}"

def verifier_tous_les_sites():
    """
    Vérifie tous les sites configurés et retourne les résultats.
    """
    logger.info("Démarrage de la vérification de tous les sites")
    sites_tries = sorted(SITES_AMELIORES, key=lambda x: x.get('priorité', 999))
    resultats = verifier_sites_en_parallele(sites_tries)
    try:
        dispo_xhr, msg_xhr = verifier_requests_xhr_roland_garros()
        resultats.append({
            "source": "Requêtes XHR Roland-Garros",
            "disponible": dispo_xhr,
            "message": msg_xhr,
            "url": "https://www.rolandgarros.com/fr-fr/billetterie",
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"XHR: {msg_xhr}")
    except Exception as e:
        logger.error(f"Erreur XHR: {e}")
        resultats.append({
            "source": "Requêtes XHR Roland-Garros",
            "disponible": False,
            "message": f"Erreur: {e}",
            "url": "https://www.rolandgarros.com/fr-fr/billetterie",
            "timestamp": datetime.now().isoformat()
        })
    try:
        url_social = "https://nitter.net/rolandgarros"
        headers = {'User-Agent': obtenir_user_agent()}
        session = creer_session()
        resp_social = session.get(url_social, headers=headers, timeout=30)
        if resp_social.status_code == 200:
            soup_social = BeautifulSoup(resp_social.text, 'html.parser')
            tweets = soup_social.select('.timeline-item')
            for tweet in tweets[:5]:
                if ('billet' in tweet.get_text().lower() or 'ticket' in tweet.get_text().lower()) and ('31 mai' in tweet.get_text().lower() or '31/05' in tweet.get_text().lower()):
                    resultats.append({
                        "source": "Twitter Officiel Roland-Garros",
                        "disponible": True,
                        "message": "Tweet récent trouvé",
                        "url": "https://twitter.com/rolandgarros",
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.info("Tweet détecté sur Twitter Officiel")
                    break
            else:
                resultats.append({
                    "source": "Twitter Officiel Roland-Garros",
                    "disponible": False,
                    "message": "Aucun tweet récent trouvé",
                    "url": "https://twitter.com/rolandgarros",
                    "timestamp": datetime.now().isoformat()
                })
        else:
            resultats.append({
                "source": "Twitter Officiel Roland-Garros",
                "disponible": False,
                "message": f"Erreur accès: {resp_social.status_code}",
                "url": "https://twitter.com/rolandgarros",
                "timestamp": datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"Erreur Twitter officiel: {e}")
    if random.choice([True, False]):
        try:
            dispo_tw, msg_tw = verifier_twitter()
            resultats.append({
                "source": "Recherche Twitter",
                "disponible": dispo_tw,
                "message": msg_tw,
                "url": "https://twitter.com/search?q=roland%20garros%20billets%2031%20mai&src=typed_query&f=live",
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"Recherche Twitter: {msg_tw}")
        except Exception as e:
            logger.error(f"Erreur recherche Twitter: {e}")
            resultats.append({
                "source": "Recherche Twitter",
                "disponible": False,
                "message": f"Erreur: {e}",
                "url": "https://twitter.com/search?q=roland%20garros%20billets%2031%20mai&src=typed_query&f=live",
                "timestamp": datetime.now().isoformat()
            })
    return resultats

def envoyer_notifications(sujet, message, alertes=None):
    """Envoie des notifications par email et Telegram."""
    if EMAIL_ADDRESS and EMAIL_PASSWORD:
        email_ok = envoyer_email(sujet, message)
    else:
        email_ok = False
        logger.warning("Configuration email manquante, notification non envoyée")
    if UTILISER_TELEGRAM and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        telegram_message = f"*{sujet}*\n\n"
        if alertes:
            telegram_message += "Détails des alertes:\n"
            for idx, alerte in enumerate(alertes, 1):
                telegram_message += f"{idx}. *{alerte['source']}*\n   {alerte['message']}\n   [Voir ici]({alerte['url']})\n\n"
        else:
            clean_message = re.sub(r'\s+', ' ', message)
            telegram_message += clean_message
        telegram_message += f"\n\nContactez directement le service client au +33 1 47 43 48 00 si nécessaire."
        telegram_ok = envoyer_alerte_telegram(telegram_message)
        success = email_ok or telegram_ok
    else:
        logger.warning("Configuration Telegram manquante, notification Telegram non envoyée")
        success = email_ok
    return success

def envoyer_stats_vers_webapp():
    """Envoie les statistiques de vérification vers la webapp."""
    try:
        data = {
            "derniere_verification": datetime.now().isoformat(),
            "resultats": resultats  # Veillez à ce que 'resultats' soit défini dans le scope
        }
        requests.post("https://rg2025bot.onrender.com/api/update", json=data)
    except Exception as e:
        logger.error(f"Erreur d'envoi des stats: {e}")

def programme_principal():
    """Fonction principale qui effectue périodiquement les vérifications."""
    logger.info(f"Bot démarré - Surveillance des billets pour Roland-Garros le {DATE_CIBLE}")
    compteur_verifications = 0
    derniere_alerte = None
    temps_debut_total = datetime.now()
    nombre_alertes = 0
    if not os.path.exists('logs'):
        os.makedirs('logs')
    sites_alertes = set()
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
                        "intervalle": intervalle_verification
                    }
                    json.dump(etat, f)
            except Exception as e:
                logger.warning(f"Impossible de sauvegarder l'état: {e}")
            alertes = []
            try:
                t_debut = datetime.now()
                resultats = verifier_tous_les_sites()
                t_fin = datetime.now()
                logger.info(f"Vérification terminée en {(t_fin - t_debut).total_seconds():.2f} secondes")
                for r in resultats:
                    if r["disponible"]:
                        alertes.append({
                            "source": r["source"],
                            "message": r["message"],
                            "url": r["url"]
                        })
            except Exception as e:
                logger.error(f"Erreur lors de la vérification des sites: {e}")
                time.sleep(INTERVALLE_RETRY)
                continue
            if alertes:
                alertes_nouvelles = []
                for alerte in alertes:
                    cle = f"{alerte['source']}_{alerte['url']}"
                    if cle not in sites_alertes or (derniere_alerte and (maintenant - derniere_alerte).total_seconds() > 86400):
                        alertes_nouvelles.append(alerte)
                        sites_alertes.add(cle)
                if alertes_nouvelles:
                    sujet = f"ALERTE - Billets Roland-Garros disponibles pour le {DATE_CIBLE}!"
                    contenu_email = f"""
Bonjour,

Des disponibilités potentielles ont été détectées pour Roland-Garros le {DATE_CIBLE}.

Détails des alertes:
"""
                    for idx, alerte in enumerate(alertes_nouvelles, 1):
                        contenu_email += f"""
{idx}. {alerte['source']}
   {alerte['message']}
   URL: {alerte['url']}
"""
                    contenu_email += f"""
Veuillez vérifier rapidement ces sites pour confirmer et effectuer votre achat.

Détection: {maintenant.strftime('%d/%m/%Y %H:%M:%S')}

Ce message a été envoyé automatiquement par votre bot de surveillance.
"""
                    if derniere_alerte is None or (maintenant - derniere_alerte).total_seconds() > 14400:
                        if envoyer_notifications(sujet, contenu_email, alertes_nouvelles):
                            derniere_alerte = maintenant
                            nombre_alertes += 1
                            logger.info(f"Alertes envoyées: {len(alertes_nouvelles)}")
                            try:
                                with open(f'logs/alerte_{maintenant.strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
                                    json.dump({"timestamp": maintenant.isoformat(), "alertes": alertes_nouvelles}, f)
                            except Exception as e:
                                logger.warning(f"Erreur enregistrement alerte: {e}")
                        else:
                            logger.error("Échec de l'envoi des notifications")
                    else:
                        logger.info("Alerte déjà envoyée récemment")
            try:
                with open('logs/statistiques.json', 'w') as f:
                    stats = {
                        "verification_actuelle": compteur_verifications,
                        "derniere_verification": maintenant.isoformat(),
                        "temps_total_en_execution": str(maintenant - temps_debut_total),
                        "nombre_alertes_envoyees": nombre_alertes,
                        "sites_surveilles": len(SITES_AMELIORES),
                        "prochaine_verification": (maintenant + timedelta(seconds=intervalle_verification)).isoformat()
                    }
                    json.dump(stats, f)
            except Exception as e:
                logger.warning(f"Impossible d'enregistrer les statistiques: {e}")
            # Purge du fichier de log si trop volumineux (5 MB max, garder les 1000 dernières lignes)
            try:
                log_file = "bot_roland_garros.log"
                if os.path.exists(log_file) and os.path.getsize(log_file) > 5 * 1024 * 1024:
                    logger.info("Purge du fichier de log")
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                    with open(log_file, 'w') as f:
                        f.writelines(lines[-1000:])
            except Exception as e:
                logger.warning(f"Erreur lors de la purge du log: {e}")
            prochaine_verif = maintenant + timedelta(seconds=intervalle_verification)
            logger.info(f"Prochaine vérification: {prochaine_verif.strftime('%H:%M:%S')} (intervalle de {intervalle_verification} s)")
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
            logger.error("ERREUR: Configuration Telegram incomplète. Veuillez configurer TELEGRAM_TOKEN et TELEGRAM_CHAT_ID")
            print("=== CONFIGURATION INCOMPLÈTE ===")
            print(f"Token actuel: {TELEGRAM_TOKEN}")
            print(f"Chat ID actuel: {TELEGRAM_CHAT_ID}")
            print("Veuillez configurer correctement ces variables d'environnement.")
            exit(1)
        logger.info("=== Configuration ===")
        logger.info(f"Date cible: {DATE_CIBLE}")
        logger.info(f"Intervalle de vérification: {INTERVALLE_VERIFICATION_MIN}-{INTERVALLE_VERIFICATION_MAX} s")
        logger.info(f"Nombre de sites surveillés: {len(SITES_AMELIORES)}")
        logger.info(f"Notifications Telegram: {'Activées' if UTILISER_TELEGRAM else 'Désactivées'}")
        logger.info(f"Notifications Email: {'Activées' if EMAIL_ADDRESS and EMAIL_PASSWORD else 'Désactivées'}")
        # Vérification de l'accès aux sites
        logger.info("Vérification de l'accès aux sites...")
        sites_inaccessibles = []
        session_test = creer_session()
        for site in SITES_AMELIORES:
            try:
                test_resp = session_test.get(site["url"], timeout=10, headers={'User-Agent': obtenir_user_agent()})
                if test_resp.status_code != 200:
                    sites_inaccessibles.append((site["nom"], test_resp.status_code))
            except Exception as e:
                sites_inaccessibles.append((site["nom"], str(e)))
        if sites_inaccessibles:
            logger.warning("Certains sites sont inaccessibles :")
            for nom, err in sites_inaccessibles:
                logger.warning(f"  - {nom}: {err}")
            envoyer_notifications("Démarrage Bot Roland-Garros avec avertissement",
                                    f"Sites inaccessibles: {', '.join(nom for nom, _ in sites_inaccessibles)}")
        else:
            logger.info("Tous les sites sont accessibles.")
        # Envoi d'un message de test
        test_ok = envoyer_notifications(
            "Test - Bot Roland-Garros Démarré",
            f"Le bot de surveillance pour Roland-Garros le {DATE_CIBLE} a démarré avec succès. Vous recevrez des alertes ici."
        )
        if test_ok:
            logger.info("Test de notification réussi, démarrage de la surveillance...")
            programme_principal()
        else:
            logger.error("Échec du test de notification, vérifiez votre configuration Telegram.")
            print("ERREUR: Le test de notification a échoué. Vérifiez votre configuration Telegram.")
    except KeyboardInterrupt:
        logger.info("Bot arrêté manuellement")
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        try:
            envoyer_notifications("ERREUR - Bot Roland-Garros", f"Le bot s'est arrêté en raison de: {e}")
        except:
            logger.error("Impossible d'envoyer la notification d'erreur")
