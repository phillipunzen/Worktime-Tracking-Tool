# ⏱ Zeiterfassung

Webbasierte Arbeitszeiterfassung für kleine und mittlere Teams, die per Docker auf dem eigenen Server läuft.
Sie funktioniert am PC und auf dem Handy und lässt sich dort wie eine App auf den Homebildschirm legen.
Gespeichert wird in **MySQL** oder **Microsoft SQL Server**.

## Funktionen

**Für Mitarbeiter**
- Stempeluhr mit **Kommen / Pause / Weiter / Gehen** und Live-Zeitanzeige; zu jeder Buchung ist eine Notiz möglich (z. B. Projekt)
- Übersicht über heute und die laufende Woche, Wochensaldo, **Überstundenkonto** und **Resturlaub**
- Zeiten nachtragen und korrigieren; nachträgliche Einträge werden gekennzeichnet und protokolliert (als Modul abschaltbar)
- **Abwesenheiten**: Urlaub, Krank, Sonderurlaub, Fortbildung und Freizeitausgleich, auch als halbe Tage
- Hinweis, wenn das Ausstempeln vergessen wurde

**Für Vorgesetzte**
- **Team-Übersicht** in Echtzeit: wer anwesend ist, wer Pause macht, wer Urlaub hat, dazu Stunden und Saldo
- Zeiten der eigenen Mitarbeiter ansehen und korrigieren; das gilt auch für indirekt unterstellte Mitarbeiter
- **Urlaubsanträge genehmigen oder ablehnen**, optional mit E-Mail-Benachrichtigung

**Berichte**
- Zeiträume: **Tag, Woche, Monat, Jahr oder frei wählbar**, jeweils für eine Person oder das ganze Team
- Ausgewiesen werden Soll, Ist, Pausen, Gutschriften für Urlaub und Krankheit, die Differenz und der Gesamtsaldo
- Warnhinweise nach Arbeitszeitgesetz: Pause unter 30 bzw. 45 Minuten, mehr als 10 Stunden am Tag
- **PDF-Export** mit Zusammenfassung, Tagesliste und Unterschriftsfeldern, für Teams mit Übersichtsseite
- **CSV-Export**, der direkt in Excel geöffnet werden kann

**Für Administratoren**
- **Module**: Funktionen je nach Bedarf ein- und ausschalten (siehe unten)
- Benutzerverwaltung mit den Rollen *Mitarbeiter*, *Vorgesetzter* und *Administrator*; jedem Benutzer kann ein Vorgesetzter zugeordnet werden
- Individuelles Arbeitszeitmodell: Wochenstunden, Arbeitstage, Urlaubstage, Beginn der Erfassung und Übertrag von Überstunden
- **Gesetzliche Feiertage je Bundesland per Klick importieren**; eigene Betriebsruhetage und halbe Tage sind möglich
- **Änderungsprotokoll** aller Korrekturen, Genehmigungen und Verwaltungsaktionen
- Schutz vor Passwort-Raten: Sperre nach 5 Fehlversuchen; beim ersten Login ist ein Passwortwechsel Pflicht

## Module

Unter **Module** kann der Administrator Funktionen ein- und ausschalten. Die Einstellung gilt sofort für alle Benutzer.
Ist ein Modul deaktiviert, verschwinden Menüpunkte und Buttons, und die zugehörigen Seiten sind nicht mehr erreichbar.
Die gespeicherten Daten bleiben erhalten.

| Bereich | Modul | Wirkung |
|---|---|---|
| Zeiterfassung | Pausen-Stempel | Button Pause/Weiter an der Stempeluhr; ohne das Modul gibt es nur Kommen und Gehen |
| | Notizen beim Stempeln | Freitext, z. B. Projekt, direkt an der Stempeluhr |
| | Zeiten selbst nachtragen | Mitarbeiter dürfen eigene Zeiten korrigieren; Vorgesetzte und Admins dürfen das immer |
| | Arbeitszeitgesetz-Hinweise | Warnungen zu Pausen und Höchstarbeitszeit |
| Abwesenheiten | Abwesenheiten & Urlaub | Urlaub, Krank, Freizeitausgleich und Urlaubskonto |
| | Genehmigungs-Workflow | Anträge muss der Vorgesetzte genehmigen; ohne das Modul gelten Einträge sofort |
| | E-Mail-Benachrichtigungen | Mails zu Anträgen; setzt SMTP-Zugangsdaten voraus |
| Auswertung | Überstundenkonto | Gesamtsaldo auf Startseite, Team-Übersicht, in Berichten und im PDF |
| | Team-Übersicht | Live-Anwesenheit für Vorgesetzte |
| | PDF-Export / CSV-Export | Download-Buttons in den Berichten |
| Verwaltung | Feiertage | Feiertagsverwaltung; ohne das Modul werden Feiertage nicht berücksichtigt |
| | Änderungsprotokoll | Protokoll aller Korrekturen und Verwaltungsaktionen |

Manche Module setzen andere voraus; die E-Mails etwa brauchen den Genehmigungs-Workflow.
Die Modulseite zeigt, wenn ein Modul deshalb inaktiv ist.

Die Standardwerte vor dem ersten Speichern lassen sich per Umgebungsvariable setzen,
z. B. `MODULE_TEAM=false` oder `MODULE_ABSENCE_APPROVAL=false`.
Bei Docker Compose gehören diese Variablen in den Abschnitt `environment:` des `app`-Dienstes.
Sobald ein Modul auf der Modulseite gespeichert wurde, gilt der Wert aus der Datenbank.

## Schnellstart (MySQL)

Voraussetzung ist ein Host mit Docker und dem Docker-Compose-Plugin.

```bash
git clone <dieses-repo> zeiterfassung && cd zeiterfassung
cp .env.example .env
# .env bearbeiten: mindestens SECRET_KEY, MYSQL_PASSWORD und MYSQL_ROOT_PASSWORD setzen
#   SECRET_KEY erzeugen:  openssl rand -hex 32
docker compose up -d
```

Danach ist die Oberfläche unter **http://&lt;host&gt;:8080** erreichbar.
Die erste Anmeldung erfolgt mit `admin` / `admin` bzw. den Werten aus `.env`. Das Passwort muss dabei sofort geändert werden.

**Empfohlene erste Schritte**
1. Unter *Feiertage* die Feiertage für das eigene Bundesland und das laufende Jahr importieren.
2. Unter *Benutzer* zuerst die Vorgesetzten anlegen, danach die Mitarbeiter mit zugeordnetem Vorgesetzten.
3. Auf dem Handy die Seite öffnen und über „Zum Home-Bildschirm hinzufügen“ ablegen.

## Variante mit Microsoft SQL Server

```bash
cp .env.example .env    # MSSQL_SA_PASSWORD setzen (Komplexitätsregeln beachten!)
docker compose -f docker-compose.mssql.yml up -d
```

Soll ein **bereits vorhandener** SQL Server oder MySQL-Server genutzt werden, genügt der App-Container allein.
Die Datenbank muss dafür schon existieren; die Tabellen legt die App selbst an.

```bash
docker build -t zeiterfassung .
docker run -d --name zeiterfassung -p 8080:8000 \
  -e DB_TYPE=mssql -e DB_HOST=sqlserver.local -e DB_PORT=1433 \
  -e DB_NAME=zeiterfassung -e DB_USER=zeit -e DB_PASSWORD='…' \
  -e SECRET_KEY="$(openssl rand -hex 32)" -e TZ=Europe/Berlin \
  zeiterfassung
```

Alternativ kann eine vollständige SQLAlchemy-URL übergeben werden, etwa `DATABASE_URL=mysql+pymysql://user:pw@host/db`.

## Konfiguration (Umgebungsvariablen)

| Variable | Standard | Beschreibung |
|---|---|---|
| `DB_TYPE` | `mysql` | `mysql` oder `mssql` |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | – | Verbindung zur Datenbank |
| `DATABASE_URL` | – | Alternative zu den `DB_*`-Variablen |
| `SECRET_KEY` | – | **Pflicht**, langer zufälliger Wert |
| `TZ` | `Europe/Berlin` | Zeitzone für die Stempelzeiten |
| `COMPANY_NAME` | `Zeiterfassung` | Name in der Oberfläche und auf den PDFs |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin` | Erster Administrator; wird nur angelegt, solange die Datenbank leer ist |
| `ALLOW_SELF_EDIT` | `true` | Standardwert für das Modul „Zeiten selbst nachtragen“ |
| `MODULE_<NAME>` | – | Standardwert eines Moduls, z. B. `MODULE_TEAM=false` (siehe [Module](#module)) |
| `BEHIND_PROXY` | `false` | `true`, wenn die App hinter nginx, Traefik oder Caddy läuft |
| `SESSION_COOKIE_SECURE` | `false` | `true` bei Zugriff über HTTPS |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SECURITY`, `SMTP_FROM` | – | Optional: E-Mails zu Urlaubsanträgen |
| `GUNICORN_WORKERS` | `3` | Anzahl der Worker-Prozesse |

### HTTPS / Reverse-Proxy

Für den Zugriff von unterwegs sollte die App hinter einem Reverse-Proxy mit HTTPS laufen.
In diesem Fall `BEHIND_PROXY=true` und `SESSION_COOKIE_SECURE=true` setzen. Beispiel für Caddy:

```
zeit.example.de {
    reverse_proxy localhost:8080
}
```

## So wird gerechnet

- **Soll pro Tag** = Wochenstunden ÷ Anzahl der Arbeitstage. An Feiertagen entfällt das Soll, an halben Feiertagen die Hälfte. Vor dem Beginn der Erfassung gibt es kein Soll.
- **Arbeitszeit** = Summe der gestempelten Blöcke abzüglich eingetragener Pausenminuten.
  Die Zeit zwischen zwei Blöcken eines Tages zählt als Pause.
- **Urlaub, Krank, Sonderurlaub und Fortbildung** schreiben das Tagessoll gut. **Freizeitausgleich** schreibt nichts gut und baut so Überstunden ab.
- **Differenz** = Ist + Gutschrift − Soll. Zukünftige Tage zählen erst, wenn sie erreicht sind.
- **Überstundenkonto** = Übertrag + Summe aller Differenzen vom Beginn der Erfassung bis gestern.

## Betrieb

```bash
docker compose logs -f app                                  # Logs ansehen
docker compose pull db && docker compose up -d --build      # Update nach git pull
docker compose exec app flask reset-password admin NeuesPasswort123   # Notfall-Passwort
docker compose exec db sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" zeiterfassung' > backup.sql   # Backup
```

Die MySQL-Daten liegen im Docker-Volume `db_data`. Es sollte regelmäßig gesichert werden.

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
pytest                                    # Tests laufen mit SQLite im Speicher
DATABASE_URL=sqlite:///dev.db flask --app wsgi init-db
DATABASE_URL=sqlite:///dev.db flask --app wsgi run --debug
```

Technik: Python 3.12, Flask, SQLAlchemy, ReportLab (PDF), Gunicorn; die Oberfläche kommt ohne externe CDNs aus.
