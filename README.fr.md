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

**Général** (`help/`, `guild_commands.py`) :
- `/help` — affiche la liste de toutes les commandes disponibles *(Aucune restriction)*
- `/ping` - vérifie que le bot répond *(Aucune restriction)*

**Payout / Comptabilité** (`payout/`) :

- `/payout creer` — ouvre un modal pour créer un nouveau payout. Après confirmation, publie un récapitulatif public et notifie chaque participant par MP avec le montant reçu et son nouveau solde. *(Nécessite : rôle Officier)*
- `/payout annuler <id>` — annule un payout et rembourse tous les participants. Marque le payout comme annulé, insère des écritures compensatoires (solde net nul) et envoie des MP avec les soldes ajustés. Refuse les payouts déjà annulés ou inconnus. *(Nécessite : rôle Officier)*
- `/payout config roles` — définit les rôles officier et leader pour la gestion des payouts. *(Nécessite : permission Administrateur Discord)*
- `/payout config taux` — modifie les taux d'imposition utilisés dans les calculs de payout. *(Nécessite : rôle Leader)*
- `/payout config permissions` — définit le niveau de permission requis pour `/solde payer` et `/solde ajouter`. *(Nécessite : rôle Leader)*
- `/payout config afficher` — affiche la configuration actuelle des payouts. *(Aucune restriction)*

**Solde** (`balance/`) :

- `/solde afficher [member]` — voir votre propre solde (aucune restriction) ou le solde d'un autre membre si autorisé. *(Voir celui des autres nécessite le niveau de permission Pay/Add — Officier ou Leader, selon `/payout config permissions`)*
- `/solde historique [membre]` — voir l'historique des transactions d'un membre avec pagination (Précédent/Suivant). Voir le vôtre est sans restriction ; voir celui des autres nécessite le niveau de permission Pay/Add. *(Aucune restriction pour son propre historique)*
- `/solde liste` — liste tous les membres avec un solde non nul. *(Nécessite le niveau de permission Pay/Add)*
- `/solde payer` — retire manuellement un montant du solde d'un joueur (refusé si solde insuffisant). *(Nécessite : rôle Officier ou Leader, selon `/payout config permissions`)*
- `/solde ajouter` — crédite manuellement le solde d'un joueur avec une raison. *(Nécessite : rôle Officier ou Leader, selon `/payout config permissions`)*

**Configuration** (`config/`) :

- `/config nonotification role` — définit ou efface le rôle dont les membres sont exclus des MP de payout. *(Nécessite : permission Administrateur Discord)*
- `/config nonotification afficher` — affiche la configuration actuelle des notifications. *(Aucune restriction)*
- `/config logs salon` — définit ou efface le salon de journalisation des commandes. *(Nécessite : permission Administrateur Discord)*
- `/config logs afficher` — affiche la configuration actuelle du salon de journalisation. *(Aucune restriction)*

**Journalisation** : si un salon de journalisation est configuré, chaque exécution réussie d'une commande slash y est automatiquement enregistrée avec la mention de l'utilisateur et le nom complet de la commande (ex. `payout creer`). Les commandes échouées ne sont pas journalisées.

## Structure du projet

```
bot/
├── cogs/           # Commandes Discord (groupées par fonctionnalité)
├── repositories/   # Couche d'accès aux données
├── services/       # Logique métier
├── locales/        # Traductions i18n
├── config.py       # Configuration
├── db_manager.py   # Gestionnaire de connexions par serveur
├── i18n.py         # Traducteur
└── main.py         # Point d'entrée
```

### Base de données

Chaque serveur Discord possède son propre fichier SQLite dans
`data/guilds/<guild_id>.db`. Les connexions sont ouvertes à la première
commande pour un serveur et fermées automatiquement après 30 minutes
d'inactivité. Le gestionnaire (`GuildDatabaseManager`) est thread-safe
par serveur.

Pour ajouter une commande nécessitant un repository :
```python
db = await self.bot.db_manager.get_connection(interaction.guild.id)
repo = MonRepository(db)
await repo.faire_quelque_chose()
```
