# DLP Cinema Projector für Home Assistant

Custom Integration zur Steuerung von DLP-Kinoprojektoren über das Netzwerk –
Einrichtung komplett über die Oberfläche, beliebig viele Projektoren pro
Home-Assistant-Instanz, für alle Hersteller dieselben Entitäten.

| Hersteller | Modelle | Protokoll | Port |
|------------|---------|-----------|------|
| **Christie** | Series 2 (z. B. CP2210/2220/2230), CineLife / CineLife+ (Series 3/4, Xenon und Laser) | Christie-Serial (Text) | 5000 |
| **Barco** | DP Series 2 (Series 1 mit Port 43680) | Barco-DP (binär) | 43728 |
| **Kinoton** | Barco DP Series 2 im Kinoton-Gehäuse | wie Barco | 43728 |

## Installation

### Über HACS

1. In jeder HA-Instanz: **HACS → ⋮ → Benutzerdefinierte Repositories** →
   `https://github.com/Haraldbbag/DLP_CinemaProjector`, Typ *Integration* →
   herunterladen → HA neu starten.
2. Updates: `version` im Manifest erhöhen – HACS bietet das Update in allen Instanzen an.

### Manuell

Ordner `custom_components/dlp_cinema_projector` nach `/config/custom_components/`
kopieren und HA neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → DLP Cinema Projector**,
dann den Hersteller wählen.

| Feld | Bedeutung |
|------|-----------|
| Host | IP-Adresse des Projektors |
| Port | wird je Hersteller vorbelegt |
| Name | z. B. „Kino 1“ – Gerätename und Präfix der Entitäten |
| Benutzer / Passwort | nur Christie, nur wenn der Projektor eine Anmeldung (`UID`) verlangt |

Pro Projektor erneut hinzufügen. IP-Wechsel: **⋮ → Neu konfigurieren**.
**Barco und Kinoton werden zunächst mit „Nur lesen“ eingerichtet** – nach dem
ersten erfolgreichen Test in den Optionen ausschalten.

### Optionen (⋮ → Optionen)

| Option | Standard | Wirkung |
|--------|----------|---------|
| Abfrageintervall | 5 s | Polling von Lampe/Power, Shutter, Kanal, Testbild |
| Nur lesen | aus (Barco/Kinoton: an) | Blockiert alle Schaltbefehle |
| Kanalnamen | leer | nur Christie, nur für Projektoren ohne Kanalliste |

## Entitäten

| Entität | Christie | Barco / Kinoton |
|---------|----------|-----------------|
| **Auswahl „Betriebszustand“** | Standby (`PWR 3`) / Lampe aus (`PWR 0`) / Lampe an (`PWR 1`) | Lampe aus / Lampe an (`76 1A 00/01`) |
| **Schalter „Shutter geschlossen“** | `SHU 1` / `SHU 0` | `23 42 00` / `22 42 00`, gelesen mit `21 42` |
| **Auswahl „Kanal“** | Kanäle des Projektors | Makros/Presets der Keypad-Tasten, Auswahl führt das Makro aus |
| **Auswahl „Testbild“** | Liste vom Projektor, „Aus“ schaltet ab | – |
| **Sensor „Status“** | Standby, Lampe aus/an, Aufwärmen, Abkühlen | – |
| Binärsensor „Verbunden“ | Diagnose | Diagnose |
| Button „Listen aktualisieren“ | Kanal- und Testbildliste neu lesen | Preset-Liste neu lesen |

„Betriebszustand“ zeigt den gewählten Zielzustand, „Status“ den tatsächlichen
Zustand inklusive Übergängen. Nach jedem Befehl fragt die Integration sofort
und danach sekündlich ab, nach einem Power-Befehl bis der Übergang vorbei ist
(max. 2 min).

## Aktion `dlp_cinema_projector.send_command`

Sendet einen Rohbefehl und gibt alle Antworten zurück. Im Modus „Nur lesen“
sind nur Abfragen erlaubt.

```yaml
# Christie: Text, mit oder ohne Klammern
action: dlp_cinema_projector.send_command
data: {device_id: <Gerät>, command: "(HLP?)"}
response_variable: antwort

# Barco/Kinoton: Befehls- und Datenbytes als Hex, Rahmen und Prüfsumme ergänzt die Integration
action: dlp_cinema_projector.send_command
data: {device_id: <Gerät>, command: "76 9A"}
response_variable: antwort   # z. B. ["00 06", "76 9A 01"] = ACK, Lampe an
```

## Protokoll-Hinweise

### Christie

Grundlage: *CineLife 2.3.1 Serial Commands* (020-102774-01) und *CineLife+
Serial Commands* (020-103075).

- Text in runden Klammern: `(PWR 1)` setzen, `(PWR?)` abfragen, `(PWR!001)`
  Antwort, Listen `(ITP!L001 001 000 "Name")` bis `"--END--"`, Fehler
  `(65535 00000 ERR00005 "Text")`.
- **Series 2** (getestet: CP2210, TPC 4.8.1, `PNG` Typ 46): Kanäle nummeriert,
  `CHA?` liefert `101`–`164`, gesetzt per Nummer (`CHA 118`), Namen aus
  `NAM+CALL?`. Im Standby werden `CHA?`/`ITP?` nicht beantwortet – Kanal und
  Testbild zeigen dann den letzten bekannten Wert. „Testpattern Off“ = Testbild 0 = „Aus“.

### Barco / Kinoton

Grundlage: *Communication Interface Barco DP Projectors* (TDE4313, Rev. 5).

- Rahmen `FE 00 <Befehl> <Daten> <Prüfsumme> FF`, Prüfsumme = Summe aus
  Adresse, Befehl und Daten mod 256; `80`/`FE`/`FF` werden als `80 00`/`80 7E`/`80 7F` gesendet.
- Jeder Befehl wird mit ACK `00 06` oder NACK `00 15` quittiert, Abfragen
  danach mit dem wiederholten Befehl plus Daten beantwortet.
- Presets: Barco kann nur die Makros der Keypad-Tasten auflisten (`E8 05`,
  Tasten 1–16); „Kanal“ zeigt das zuletzt ausgeführte Makro (`E8 01`).
- Der Projektor trennt nach 15 min Inaktivität; das Polling hält die Verbindung offen.

Debug-Log:

```yaml
logger:
  logs:
    custom_components.dlp_cinema_projector: debug
```

## Testen ohne Projektor

```bash
python3 tests/fake_christie.py 0.0.0.0 5000 [--series2]
python3 tests/fake_barco.py 0.0.0.0 43728
python3 tests/test_christie.py
python3 tests/test_barco.py
```
