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
- `/solde payer` — retire manuellement un montant du solde d'un joueur (refusé si solde insuffisant). En cas de succès, envoie un MP au joueur concerné avec le montant débité et le nouveau solde. *(Nécessite : rôle Officier ou Leader, selon `/payout config permissions`)*
- `/solde ajouter` — crédite manuellement le solde d'un joueur avec une raison. En cas de succès, envoie un MP au joueur concerné avec le montant crédité, la raison et le nouveau solde. *(Nécessite : rôle Officier ou Leader, selon `/payout config permissions`)*

**Inscriptions d'activités** (`activite/`) :

- `/activite creer` — ouvre un formulaire unique (titre, lieu de départ, heure de RDV, stuff optionnel, et la structure des slots : `CATEGORIE - description`, `@mention` pré-remplit un slot). Une date/heure reconnaissable (ex : `03/08 20:00` ou `20h00`) est rendue en timestamp Discord, donc chacun la voit dans son fuseau local. L'embed d'inscription est ensuite posté avec un menu déroulant pour modifier chaque champ, une fil de discussion, et des slots par rôle. Un slot `FILL` est ajouté automatiquement à la fin. *(Aucune restriction)*
- Slots — n'importe qui peut réclamer un slot depuis le menu déroulant de l'embed, ou dans la fil avec `/activite rejoindre <slot>`. Un joueur ne peut tenir qu'un seul slot par activité ; plusieurs joueurs peuvent partager un slot. `/activite quitter` libère ton slot, et le bouton **Fermer** fige l'embed. L'embed est la source de vérité, donc les commandes de fil continuent de fonctionner après un redémarrage du bot (aucune base de données, rien n'est traqué).

**Configuration** (`config/`) :

- `/config nonotification role` — définit ou efface le rôle dont les membres sont exclus des MP de payout. *(Nécessite : permission Administrateur Discord)*
- `/config nonotification afficher` — affiche la configuration actuelle des notifications. *(Aucune restriction)*
- `/config logs salon` — définit ou efface le salon de journalisation des commandes. *(Nécessite : permission Administrateur Discord)*
- `/config logs afficher` — affiche la configuration actuelle du salon de journalisation. *(Aucune restriction)*

**Journalisation** : si un salon de journalisation est configuré, chaque exécution réussie d'une commande slash y est automatiquement enregistrée avec la mention de l'utilisateur et le nom complet de la commande (ex. `payout creer`). Les commandes échouées ne sont pas journalisées.

**Journalisation dev** : les logs d'exécution sont écrits dans des fichiers par serveur sous `<data_dir>/logs/` (`guild_<id>.log`, plus un `bot.log` global pour l'activité hors serveur), avec rotation automatique (1 Mo par fichier, 10 backups) et **les entrées les plus récentes en haut** de chaque fichier. Un `errors.log` global agrège tous les enregistrements `ERROR`+ de tous les serveurs — une liste unique de tous les problèmes à investiguer. Chaque ligne mentionne les noms de la guilde et de l'utilisateur quand ils sont connus, ex. `executed by 1354... "R3dn0" in guild 1526... "Eradicateur-Bot TEST"`. L'activité de chaque serveur est routée vers son propre fichier via le contexte d'exécution des commandes slash. Le niveau est contrôlé par `LOG_LEVEL` dans `.env` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, défaut `DEBUG`). La console affiche les `INFO`+ (logs de lancement/cycle de vie et la stack trace complète en cas d'erreur) pour confirmer visuellement le démarrage du bot, tandis que le détail `DEBUG` par commande reste dans les fichiers. Les échecs de commande y sont journalisés avec leur traceback complet — pratique pour les serveurs auxquels tu n'as pas accès. Les rejets côté utilisateur (`CheckFailure`, `CommandNotFound`, `CommandOnCooldown`) sont journalisés en `DEBUG` dans les fichiers uniquement, pas comme des erreurs.

## Structure du projet

```
bot/
├── cogs/           # Commandes Discord (groupées par fonctionnalité)
├── repositories/   # Couche d'accès aux données
├── services/       # Logique métier
├── locales/        # Traductions i18n
├── config.py       # Configuration
├── db_manager.py   # Gestionnaire de connexions par serveur
├── dev_logs.py     # Logs fichier par serveur pour les développeurs
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
