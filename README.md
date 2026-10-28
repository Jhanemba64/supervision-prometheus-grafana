# Supervision de serveurs critiques — Prometheus + Grafana

Une pile de supervision prête à l'emploi, lancée par un simple `docker compose up -d`, qui surveille
trois serveurs critiques (web, base de données, cache) et l'hôte qui les porte : CPU, espace
disque et disponibilité des services.

Tout est décrit dans des fichiers versionnés : rien n'est configuré à la main dans une interface.

## Architecture

Les serveurs sont simulés par des conteneurs. Pour que chacun se comporte comme une machine
distincte, il reçoit :

- son propre **quota de vCPU**, ce qui permet de saturer un serveur sans toucher aux autres ;
- sa propre **partition `/data` de taille fixe** (volume tmpfs limité). Quand elle est pleine, les
  écritures échouent comme sur un vrai disque. PostgreSQL y stocke réellement ses données ;
- son **agent `node_exporter`**, qui lit cette partition comme l'agent installé sur chaque machine
  d'un parc réel.

| Composant | Image | Rôle |
|---|---|---|
| srv-web-01 / srv-db-01 / srv-cache-01 | `nginx:1.30.6-alpine`, `postgres:18.6-alpine`, `redis:8.6.8-alpine` | Serveurs critiques surveillés |
| agent-web / agent-db / agent-cache | `prom/node-exporter:v1.12.1` | Espace disque de la partition `/data` de chaque serveur |
| node-exporter | `prom/node-exporter:v1.12.1` | CPU et disque de l'hôte Docker |
| cadvisor | `ghcr.io/google/cadvisor:v0.60.6` | CPU de chaque serveur, mesuré par cgroup |
| blackbox | `prom/blackbox-exporter:v0.29.1` | Sondes de disponibilité des services |
| prometheus | `prom/prometheus:v3.15.1` | Collecte toutes les 5 s, règles d'enregistrement, rétention 7 jours |
| grafana | `grafana/grafana:13.2.5` | Tableau de bord, règles d'alerte, notifications (interface en français) |

## Démarrage rapide

**Prérequis** : Docker avec Compose v2 et environ 1,2 Go de RAM libre (dont 900 Mo pour Grafana),
plus la place des partitions `/data` si on les remplit (1 Go au maximum). Les ports `3000` et
`9090` doivent être libres sur `127.0.0.1`.

```bash
cp .env.example .env      # puis choisir les mots de passe Grafana et PostgreSQL
docker compose up -d
docker compose ps         # 11 conteneurs "Up"
```

| Interface | Adresse | Accès |
|---|---|---|
| Grafana | <http://localhost:3000> | `admin` / mot de passe défini dans `.env` |
| Prometheus | <http://localhost:9090> | — |

Le tableau de bord « Supervision des serveurs critiques » s'ouvre directement comme page
d'accueil de Grafana. Les ports ne sont publiés que sur `127.0.0.1`.

Arrêt et nettoyage complet : `docker compose down -v`.

## Le tableau de bord

Le tableau de bord est versionné dans `grafana/dashboards/supervision-serveurs.json` et chargé
automatiquement par provisioning. Il se lit de haut en bas :

1. **Vue d'ensemble** : trois compteurs (services hors ligne, serveurs en surcharge CPU, disques
   critiques), verts à 0 et rouges dès 1, et la liste des alertes en cours.
2. **Utilisation CPU** : jauge par serveur et historique sur fond de zones colorées.
3. **Espace disque** : jauge par partition, tableau détaillé (taille, espace libre, % utilisé) et historique.
4. **Services critiques** : état EN LIGNE / HORS LIGNE, frise de disponibilité et détail des sondes.

| Indicateur | Normal | Avertissement | Critique | Alerte |
|---|---|---|---|---|
| CPU | < 70 % | 70 à 85 % | > 85 % | > 85 % pendant 1 min |
| Espace disque utilisé | < 80 % | 80 à 90 % | > 90 % (moins de 10 % libre) | > 90 % pendant 1 min |
| Service | EN LIGNE | — | HORS LIGNE | dès le premier échec |

Pourquoi ces valeurs :

- **CPU** : 70 % laisse une marge pour absorber un pic ; au-delà de 85 % de façon prolongée, les
  temps de réponse se dégradent.
- **Disque** : 80 % laisse le temps d'agir (purge, extension) ; à 90 %, une petite partition peut
  se remplir en quelques minutes avec des journaux ou une sauvegarde.
- **Attente d'une minute** pour le CPU et le disque : un pic bref ne doit pas réveiller l'astreinte.
  Pour un service, aucune attente : une coupure est signalée tout de suite.

Côté interactivité :

- la variable **Serveur** (sélection multiple) filtre tous les panneaux ;
- le rafraîchissement est automatique toutes les 5 s ;
- les tableaux se trient d'un clic sur l'en-tête ;
- chaque panneau a une info-bulle qui explique ce qu'il mesure.

## Calcul des indicateurs

Prometheus calcule chaque indicateur par une **règle d'enregistrement**
(`prometheus/rules/serveurs.yml`). Quelle que soit la source, l'indicateur porte un nom unique et
une étiquette `server`. Grafana affiche ainsi tous les serveurs dans un même panneau, avec les mêmes seuils.

| Indicateur | Métrique | Calcul |
|---|---|---|
| CPU d'un serveur | `server:cpu_usage:percent` | temps CPU consommé (cAdvisor) ÷ vCPU alloués × 100 |
| CPU de l'hôte | `server:cpu_usage:percent` | temps CPU actif ÷ temps CPU total compté × 100 (node_exporter) |
| Espace disque | `server:disk_usage:percent` | (1 − espace disponible ÷ taille) × 100 |
| Disponibilité | `probe_success` | 1 si la sonde réussit, 0 sinon |

Pourquoi cAdvisor pour le CPU des serveurs ? Les conteneurs partagent le noyau de l'hôte. Un
`node_exporter` placé dans un conteneur lit `/proc/stat`, c'est-à-dire le CPU de **toute** la
machine. La seule mesure propre à chaque serveur est sa consommation de cgroup, rapportée au quota
qui lui est alloué.

Les sondes de `blackbox/blackbox.yml` vérifient chaque service depuis l'extérieur :

| Service | Sonde | Ce qui est vérifié |
|---|---|---|
| nginx | `http_2xx` | La page d'accueil répond en HTTP 2xx |
| PostgreSQL | `tcp_connect` | Le port 5432 accepte les connexions |
| Redis | `redis` | Redis répond `+PONG` à un `PING` : le protocole est vérifié, pas seulement le port |

## Pièges rencontrés sous Docker Desktop / WSL2

| Symptôme | Cause | Solution |
|---|---|---|
| `node_exporter` de l'hôte ne démarre pas : *path / is mounted on / but it is not a shared or slave mount* | Docker Desktop refuse la propagation `rslave` sur la racine | Monter `/:/host:ro`, sans `rslave` |
| CPU de l'hôte affiché à 80 % alors que la machine est au repos | Sous WSL2, le temps « idle » des vCPU n'est pas entièrement comptabilisé : la somme des modes ne fait que 8,6 s/s pour 16 vCPU. La formule classique `1 − idle` surestime donc le CPU | Calculer temps actif ÷ temps total compté, une formule qui reste juste même si des compteurs manquent |
| Disque de l'hôte introuvable sur `/var/lib/docker` | Le disque de données de la VM Docker Desktop est monté sur `/var/lib` | Cibler `/var/lib` |
| La frise de disponibilité affiche « 1+ » au lieu de « EN LIGNE » | Le mode de couleur « seuils » prend le pas sur les correspondances de valeurs | Retirer ce mode : les correspondances portent le texte et la couleur |
| Tableau de bord modifié mais non rechargé | Les fichiers provisionnés depuis un dossier Windows ne sont pas relus à chaud | `docker compose restart grafana` (l'état des alertes est conservé) |
