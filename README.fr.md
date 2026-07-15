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
- `/ping` - vérifie que le bot répond *(Aucune restriction)*

**Payout / Comptabilité** (`payout.py`) :

- `/payout creer` — ouvre un modal pour créer un nouveau payout. Après confirmation, publie un récapitulatif public et notifie chaque participant par MP avec le montant reçu et son nouveau solde. *(Nécessite : rôle Officier)*
- `/payout config roles` — définit les rôles officier et leader pour la gestion des payouts, plus un rôle optionnel `no_dm` dont les membres ne reçoivent pas de MP pour les payout. *(Nécessite : permission Administrateur Discord)*
- `/payout config taux` — modifie les taux d'imposition utilisés dans les calculs de paiement. *(Nécessite : rôle Leader)*
- `/payout config afficher` — affiche la configuration actuelle, y compris le rôle d'exclusion des MP si configuré. *(Aucune restriction)*

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
