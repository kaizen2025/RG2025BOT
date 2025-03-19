# Pokemon Stock Monitor Pro

Un système complet de surveillance en temps réel des stocks de collections Pokémon sur plusieurs sites e-commerce, avec notifications instantanées, interface web responsive et gestion des utilisateurs.

![Pokemon Stock Monitor](https://via.placeholder.com/800x400/3B5BA7/FFFFFF?text=Pokemon+Stock+Monitor)

## Caractéristiques

- 🔍 **Surveillance multi-sites** : Amazon, Fnac, Cultura, Carrefour, Joué Club, King Jouet, etc.
- 🛡️ **Anti-détection avancé** : Rotation d'User-Agents, proxies, délais aléatoires et circuit breakers
- 🖼️ **Captures d'écran** : Screenshots automatiques avec mise en valeur des prix et statuts de stock
- 📊 **Interface web moderne** : Dashboard interactif et responsive avec statistiques en temps réel
- 🔔 **Notifications multi-canaux** : Email, Telegram et notifications dans le navigateur
- 👥 **Système d'utilisateurs** : Enregistrement, validation par admin et préférences personnalisées
- 📱 **Responsive** : Interface adaptée à tous les appareils (ordinateurs, tablettes, smartphones)
- 🌙 **Mode sombre** : Interface avec thème clair/sombre selon vos préférences

## Architecture technique

Le système est construit autour des technologies suivantes :

- **Backend** : Python 3.9 avec Flask
- **Frontend** : HTML5, CSS3, JavaScript avec Bootstrap 5
- **Base de données** : SQLite (peut être migré vers PostgreSQL/MySQL)
- **Scraping** : BeautifulSoup4, Selenium, CloudScraper
- **Visualisation** : Chart.js
- **Authentification** : Système personnalisé avec validation par admin

## Prérequis

- Python 3.9 ou supérieur
- Chrome (pour Selenium)
- Pip (gestionnaire de paquets Python)

## Installation

### Installation standard

1. Clonez le dépôt :
   ```bash
   git clone https://github.com/votre-utilisateur/pokemon-stock-monitor.git
   cd pokemon-stock-monitor
   ```

2. Créez et activez un environnement virtuel :
   ```bash
   python -m venv venv
   source venv/bin/activate  # Sur Windows : venv\Scripts\activate
   ```

3. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

4. Installez ChromeDriver pour Selenium :
   ```bash
   # Le script l'installera automatiquement, mais vous pouvez aussi l'installer manuellement
   ```

5. Configurez vos variables d'environnement dans un fichier `.env` :
   ```
   # Notifications
   EMAIL_ADDRESS=votre-email@gmail.com
   EMAIL_PASSWORD=votre-mot-de-passe
   EMAIL_RECIPIENT=destinataire@email.com
   TELEGRAM_TOKEN=votre-token-telegram
   TELEGRAM_CHAT_ID=votre-chat-id
   
   # Intervalles de vérification (en secondes)
   INTERVALLE_MIN=540
   INTERVALLE_MAX=660
   
   # Configuration de l'application
   SECRET_KEY=votre-clé-secrète-très-longue
   FLASK_DEBUG=False
   ```

6. Lancez l'application :
   ```bash
   python app.py
   ```

### Installation avec Docker

1. Construisez l'image Docker :
   ```bash
   docker build -t pokemon-stock-monitor .
   ```

2. Exécutez le conteneur :
   ```bash
   docker run -p 5000:5000 --env-file .env pokemon-stock-monitor
   ```

## Configuration

### Sites surveillés

Les sites surveillés sont configurés dans le fichier `pokemon_scraper.py`. Vous pouvez ajouter, modifier ou supprimer des sites selon vos besoins.

### Proxies

Le système supporte plusieurs services de proxy :
- BrightData
- SmartProxy
- Liste de proxies personnalisée

Configurez vos proxies dans le panneau d'administration ou via les variables d'environnement.

### Notifications

Le système peut envoyer des notifications via :
- Email (SMTP)
- Telegram
- Notifications dans le navigateur

## Utilisation

1. Accédez à l'interface web : `http://localhost:5000`
2. Connectez-vous avec les identifiants par défaut :
   - Utilisateur : `admin`
   - Mot de passe : `admin123`
3. Modifiez le mot de passe admin dans votre profil
4. Approuvez les nouveaux utilisateurs via le panneau d'administration
5. Configurez vos préférences de notification
6. Surveillez les stocks en temps réel !

## Sécurité

- Les mots de passe sont hachés avec bcrypt
- Protection contre les attaques de force brute
- Circuit breakers pour éviter les bannissements d'IP
- Validation des entrées côté serveur et client

## Extension du système

### Ajout d'un nouveau site

1. Identifiez les sélecteurs CSS nécessaires (disponibilité, prix, titre, image, bouton d'ajout au panier)
2. Ajoutez une nouvelle entrée dans la liste `SITES` dans `pokemon_scraper.py`
3. Testez avec la fonction "Vérifier maintenant" dans l'interface

### Ajout d'une nouvelle collection

1. Définissez les mots-clés et identifiants de produits dans la liste `POKEMON_COLLECTIONS`
2. Ajoutez les produits correspondants dans les sites surveillés

## Contribution

Les contributions sont les bienvenues ! Voici comment contribuer :

1. Fork du projet
2. Création d'une branche (`git checkout -b feature/amazing-feature`)
3. Commit de vos changements (`git commit -m 'Add amazing feature'`)
4. Push vers la branche (`git push origin feature/amazing-feature`)
5. Création d'une Pull Request

## Licence

Ce projet est distribué sous licence MIT. Voir le fichier `LICENSE` pour plus d'informations.

## Remerciements

- [Bootstrap](https://getbootstrap.com/)
- [Chart.js](https://www.chartjs.org/)
- [FontAwesome](https://fontawesome.com/)
- [Selenium](https://www.selenium.dev/)
- [Flask](https://flask.palletsprojects.com/)
- [Bcrypt](https://pypi.org/project/bcrypt/)

---

Développé par [KAIZEN2025 KB]
