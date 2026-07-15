# Bot Discord - ERADICATEURS - Guilde Albion Online

> 🇬🇧 [Read in English](README.md)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # puis renseigner DISCORD_TOKEN et GUILD_ID
python -m bot.main
```

## Commandes disponibles

**Général** (`guild_commands.py`) :
- `/ping` - vérifie que le bot répond

**Payout / Comptabilité** (`payout.py`) :
- `/payout config roles <officier> <leader>` — définit les rôles officier et leader pour la gestion des paiements (Administrateur uniquement)
- `/payout config rates <marché> <guilde> <transport>` — modifie les taux d'imposition utilisés dans les calculs de paiement (rôle Leader requis)
- `/payout config show` — affiche la configuration actuelle des paiements (aucune restriction)

## Structure du projet

```
bot/
├── cogs/           # Commandes Discord (groupées par fonctionnalité)
├── repositories/   # Couche d'accès aux données
├── services/       # Logique métier
├── locales/        # Traductions i18n
├── config.py       # Configuration
├── i18n.py         # Traducteur
└── main.py         # Point d'entrée
```
