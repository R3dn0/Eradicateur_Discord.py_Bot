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

- `/ping` — vérifie que le bot répond
- `/inscrire <pseudo>` — enregistre ton pseudo Albion sur ton compte Discord
- `/membres` — liste les membres enregistrés
