"""
advanced_anti_detection.py - Système avancé pour éviter la détection du bot
"""

import random
import time
import json
import os
import logging
from datetime import datetime, timedelta
from user_agents import parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

class AdvancedAntiDetection:
    def __init__(self, config_file='config/anti_detection.json'):
        self.logger = logging.getLogger('anti_detection')
        
        # Charger la configuration
        self.config = self._load_config(config_file)
        
        # Initialiser les statistiques
        self.stats = {
            'requests_total': 0,
            'requests_blocked': 0,
            'last_reset': datetime.now().isoformat(),
            'site_stats': {}
        }
        
        # Charger les statistiques depuis le fichier s'il existe
        self._load_stats()
        
        # Initialiser les temps d'attente par site
        self.site_wait_times = {}
        for site in self.config['sites']:
            self.site_wait_times[site['name']] = {
                'last_request': None,
                'cooldown': site.get('cooldown', self.config['default_cooldown'])
            }
            
            # Initialiser les statistiques du site si elles n'existent pas
            if site['name'] not in self.stats['site_stats']:
                self.stats['site_stats'][site['name']] = {
                    'requests_total': 0,
                    'requests_blocked': 0,
                    'failures': 0,
                    'last_successful_request': None
                }
    
    def _load_config(self, config_file):
        """Charge la configuration depuis un fichier JSON"""
        default_config = {
            'default_cooldown': 60,  # Temps d'attente par défaut entre les requêtes en secondes
            'user_agent_rotation': True,  # Activer la rotation des user agents
            'proxy_rotation': True,  # Activer la rotation des proxies
            'request_timeout': 30,  # Timeout par défaut pour les requêtes en secondes
            'max_retries': 3,  # Nombre maximum de tentatives en cas d'échec
            'backoff_factor': 2,  # Facteur multiplicateur pour le temps d'attente entre les tentatives
            'sites': [],  # Liste des sites à surveiller avec leurs configurations spécifiques
            'user_agents': [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:93.0) Gecko/20100101 Firefox/93.0",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/94.0.4606.76 Mobile/15E148 Safari/604.1"
            ],
            'fingerprint_variations': True,  # Activer les variations d'empreinte digitale
            'canvas_noise': True,  # Ajouter du bruit aux canvas pour éviter le fingerprinting
            'webgl_noise': True,  # Ajouter du bruit aux WebGL pour éviter le fingerprinting
            'timezone_spoofing': True,  # Usurper le fuseau horaire
            'hardware_concurrency_spoofing': True,  # Usurper le nombre de cœurs CPU
            'randomize_viewport': True,  # Randomiser la taille de la fenêtre
        }
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    loaded_config = json.load(f)
                    # Fusionner avec la configuration par défaut
                    for key, value in loaded_config.items():
                        default_config[key] = value
                self.logger.info(f"Configuration chargée depuis {config_file}")
            else:
                self.logger.warning(f"Fichier de configuration {config_file} introuvable, utilisation des valeurs par défaut")
                
                # Créer le répertoire si nécessaire
                os.makedirs(os.path.dirname(config_file), exist_ok=True)
                
                # Sauvegarder la configuration par défaut
                with open(config_file, 'w') as f:
                    json.dump(default_config, f, indent=4)
                self.logger.info(f"Configuration par défaut sauvegardée dans {config_file}")
        except Exception as e:
            self.logger.error(f"Erreur lors du chargement de la configuration: {e}")
        
        return default_config

    def _load_stats(self):
        """Charge les statistiques depuis un fichier JSON"""
        stats_file = 'logs/anti_detection_stats.json'
        try:
            if os.path.exists(stats_file):
                with open(stats_file, 'r') as f:
                    self.stats = json.load(f)
                    self.logger.info("Statistiques d'anti-détection chargées")
        except Exception as e:
            self.logger.error(f"Erreur lors du chargement des statistiques: {e}")

    def _save_stats(self):
        """Sauvegarde les statistiques dans un fichier JSON"""
        stats_file = 'logs/anti_detection_stats.json'
        try:
            # Créer le répertoire si nécessaire
            os.makedirs(os.path.dirname(stats_file), exist_ok=True)
            
            with open(stats_file, 'w') as f:
                json.dump(self.stats, f, indent=4)
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde des statistiques: {e}")

    def get_user_agent(self):
        """Renvoie un user agent aléatoire depuis la liste configurée"""
        if self.config['user_agent_rotation'] and self.config['user_agents']:
            return random.choice(self.config['user_agents'])
        return self.config['user_agents'][0] if self.config['user_agents'] else None

    def should_wait(self, site_name):
        """Détermine si le bot doit attendre avant d'envoyer une requête à un site"""
        site_info = self.site_wait_times.get(site_name)
        if not site_info:
            return False
        
        last_request = site_info['last_request']
        cooldown = site_info['cooldown']
        
        if last_request is None:
            return False
        
        last_request_time = datetime.fromisoformat(last_request)
        wait_until = last_request_time + timedelta(seconds=cooldown)
        
        if datetime.now() < wait_until:
            wait_seconds = (wait_until - datetime.now()).total_seconds()
            self.logger.info(f"Attente de {wait_seconds:.2f}s pour {site_name} (cooldown: {cooldown}s)")
            return True
        
        return False

    def wait_for_site(self, site_name):
        """Attend le temps nécessaire avant de faire une requête à un site"""
        site_info = self.site_wait_times.get(site_name)
        if not site_info:
            time.sleep(self.config['default_cooldown'])
            return
        
        last_request = site_info['last_request']
        cooldown = site_info['cooldown']
        
        if last_request is None:
            return
        
        last_request_time = datetime.fromisoformat(last_request)
        wait_until = last_request_time + timedelta(seconds=cooldown)
        
        if datetime.now() < wait_until:
            wait_seconds = (wait_until - datetime.now()).total_seconds()
            self.logger.info(f"Attente de {wait_seconds:.2f}s pour {site_name}")
            time.sleep(wait_seconds)

    def record_request(self, site_name, success=True):
        """Enregistre une requête pour un site"""
        # Mettre à jour le dernier temps de requête
        self.site_wait_times[site_name]['last_request'] = datetime.now().isoformat()
        
        # Mettre à jour les statistiques
        self.stats['requests_total'] += 1
        if site_name in self.stats['site_stats']:
            self.stats['site_stats'][site_name]['requests_total'] += 1
            
            if success:
                self.stats['site_stats'][site_name]['last_successful_request'] = datetime.now().isoformat()
            else:
                self.stats['site_stats'][site_name]['failures'] += 1
                self.stats['site_stats'][site_name]['requests_blocked'] += 1
                self.stats['requests_blocked'] += 1
        
        # Sauvegarder les statistiques
        self._save_stats()

    def get_headers(self, site_name=None):
        """Génère des en-têtes HTTP pour éviter la détection"""
        user_agent = self.get_user_agent()
        
        # Analyse du user agent pour des en-têtes cohérents
        ua_info = parse(user_agent)
        
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
        # Ajouter des en-têtes spécifiques au site
        if site_name:
            site_config = next((site for site in self.config['sites'] if site['name'] == site_name), None)
            if site_config and 'headers' in site_config:
                for key, value in site_config['headers'].items():
                    headers[key] = value
        
        return headers

    def init_selenium_options(self):
        """Initialise les options Selenium avec des paramètres anti-détection"""
        options = Options()
        
        # Options de base
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # User Agent
        user_agent = self.get_user_agent()
        options.add_argument(f'--user-agent={user_agent}')
        
        # Langue
        options.add_argument('--lang=fr-FR')
        
        # Viewport aléatoire si activé
        if self.config['randomize_viewport']:
            width = random.randint(1024, 1920)
            height = random.randint(768, 1080)
            options.add_argument(f'--window-size={width},{height}')
        
        # Ajouter des arguments pour contourner la détection
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        return options

    def create_selenium_driver(self):
        """Crée et configure un pilote Selenium avec des mesures anti-détection"""
        options = self.init_selenium_options()
        
        # Tenter d'installer ChromeDriver automatiquement
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except:
            service = Service()
        
        driver = webdriver.Chrome(service=service, options=options)
        
        # Configurer des paramètres supplémentaires via JavaScript
        scripts = []
        
        # Masquer la chaîne webdriver
        scripts.append("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        """)
        
        # Simuler des plugins
        scripts.append("""
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        """)
        
        # Simuler les langues
        scripts.append("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['fr-FR', 'fr', 'en-US', 'en']
        });
        """)
        
        # Usurper le fuseau horaire si activé
        if self.config['timezone_spoofing']:
            timezone = random.choice(['Europe/Paris', 'Europe/Brussels', 'Europe/Madrid'])
            scripts.append(f"""
            Object.defineProperty(Intl, 'DateTimeFormat', {{
                get: () => function() {{ return {{ resolvedOptions: () => {{ return {{ timeZone: '{timezone}' }} }} }} }}
            }});
            """)
        
        # Usurper le nombre de cœurs CPU si activé
        if self.config['hardware_concurrency_spoofing']:
            cores = random.randint(2, 8) * 2
            scripts.append(f"""
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {cores}
            }});
            """)
        
        # Ajouter du bruit aux canvas si activé
        if self.config['canvas_noise']:
            scripts.append("""
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type) {
                const canvas = document.createElement('canvas');
                canvas.width = this.width;
                canvas.height = this.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(this, 0, 0);
                
                // Ajouter du bruit
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const pixels = imageData.data;
                for (let i = 0; i < pixels.length; i += 4) {
                    pixels[i] = pixels[i] + Math.floor(Math.random() * 3) - 1; // Rouge
                    pixels[i+1] = pixels[i+1] + Math.floor(Math.random() * 3) - 1; // Vert
                    pixels[i+2] = pixels[i+2] + Math.floor(Math.random() * 3) - 1; // Bleu
                }
                ctx.putImageData(imageData, 0, 0);
                
                return originalToDataURL.apply(canvas, arguments);
            };
            """)
        
        # Exécuter tous les scripts
        for script in scripts:
            driver.execute_script(script)
        
        return driver

    def get_site_config(self, site_name):
        """Récupère la configuration spécifique à un site"""
        return next((site for site in self.config['sites'] if site['name'] == site_name), None)

    def adjust_cooldown(self, site_name, success):
        """Ajuste dynamiquement le temps d'attente entre les requêtes en fonction du succès"""
        site_info = self.site_wait_times.get(site_name)
        if not site_info:
            return
        
        site_config = self.get_site_config(site_name)
        
        if success:
            # Réduire le cooldown si plusieurs succès consécutifs
            site_stats = self.stats['site_stats'].get(site_name, {})
            failures = site_stats.get('failures', 0)
            
            if failures == 0:
                # Réduire le cooldown jusqu'à un minimum
                min_cooldown = site_config.get('min_cooldown', 30) if site_config else 30
                site_info['cooldown'] = max(site_info['cooldown'] * 0.9, min_cooldown)
        else:
            # Augmenter le cooldown en cas d'échec
            max_cooldown = site_config.get('max_cooldown', 300) if site_config else 300
            site_info['cooldown'] = min(site_info['cooldown'] * 1.5, max_cooldown)
        
        self.logger.info(f"Cooldown pour {site_name} ajusté à {site_info['cooldown']:.2f}s")

    def get_stats(self):
        """Renvoie les statistiques du système anti-détection"""
        return self.stats

# Exemple d'utilisation
if __name__ == "__main__":
    # Configuration du logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Créer une instance du système anti-détection
    anti_detection = AdvancedAntiDetection()
    
    # Exemple d'utilisation avec requests
    import requests
    
    site_name = "Amazon France"
    
    # Vérifier s'il faut attendre
    if anti_detection.should_wait(site_name):
        anti_detection.wait_for_site(site_name)
    
    # Obtenir des en-têtes adaptés
    headers = anti_detection.get_headers(site_name)
    
    try:
        # Faire la requête
        response = requests.get("https://www.amazon.fr", headers=headers, timeout=30)
        success = response.status_code == 200
        
        # Enregistrer la requête
        anti_detection.record_request(site_name, success)
        
        # Ajuster le cooldown
        anti_detection.adjust_cooldown(site_name, success)
        
        if success:
            print("Requête réussie!")
        else:
            print(f"Échec de la requête: {response.status_code}")
    except Exception as e:
        print(f"Erreur: {e}")
        anti_detection.record_request(site_name, False)
        anti_detection.adjust_cooldown(site_name, False)
    
    # Exemple d'utilisation avec Selenium
    print("\nTest avec Selenium:")
    driver = anti_detection.create_selenium_driver()
    
    try:
        driver.get("https://www.amazon.fr")
        print("Navigation Selenium réussie!")
        anti_detection.record_request(site_name, True)
        anti_detection.adjust_cooldown(site_name, True)
    except Exception as e:
        print(f"Erreur Selenium: {e}")
        anti_detection.record_request(site_name, False)
        anti_detection.adjust_cooldown(site_name, False)
    finally:
        driver.quit()
    
    # Afficher les statistiques
    print("\nStatistiques:")
    stats = anti_detection.get_stats()
    print(json.dumps(stats, indent=2))
