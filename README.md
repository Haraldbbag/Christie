# Christie Kinoprojektoren für Home Assistant

Custom Integration zur Steuerung von Christie-Kinoprojektoren über das
Netzwerk (Christie-Serial-Protokoll auf TCP-Port 5000). Einrichtung komplett
über die Oberfläche, beliebig viele Projektoren pro Home-Assistant-Instanz.

Gedacht für Series 2 (z. B. CP2210/CP2220/CP2230) sowie CineLife-/CineLife+-
Projektoren (Series 3/4, Xenon und Laser). Die Grundfunktionen sind für alle
Serien gleich.

## Installation

### Über HACS

1. In jeder HA-Instanz: **HACS → ⋮ → Benutzerdefinierte Repositories** →
   `https://github.com/Haraldbbag/christie`, Typ *Integration* →
   herunterladen → HA neu starten.
2. Updates: `version` im Manifest erhöhen, Release taggen – HACS bietet das
   Update in allen Instanzen an.

### Manuell

Ordner `custom_components/christie` nach `/config/custom_components/`
kopieren und HA neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → Christie Kinoprojektor**

| Feld | Bedeutung |
|------|-----------|
| Host | IP-Adresse des Projektors |
| Port | Standard **5000** |
| Name | z. B. „Kino 1“ – Gerätename und Präfix der Entitäten |
| Benutzer / Passwort | nur nötig, wenn der Projektor eine Anmeldung (`UID`) verlangt, z. B. für Testbilder |

Pro Projektor erneut hinzufügen (drei Projektoren = dreimal). IP-Wechsel:
**⋮ → Neu konfigurieren**.

### Optionen (⋮ → Optionen)

| Option | Standard | Wirkung |
|--------|----------|---------|
| Abfrageintervall | 5 s | Polling von Power, Shutter, Kanal, Testbild |
| Nur lesen | aus | Blockiert alle Schaltbefehle (gut zum gefahrlosen Testen) |
| Kanalnamen | leer | Nur für Projektoren, die ihre Kanäle nicht auflisten können: ein Name pro Zeile, in der Reihenfolge der Kanalnummern |

## Entitäten

| Entität | Funktion |
|---------|----------|
| **Auswahl „Betriebszustand“** | *Standby* (`PWR 3`) / *Lampe aus* (`PWR 0`) / *Lampe an* (`PWR 1`) |
| **Sensor „Status“** | Standby, Lampe aus, Lampe an, Aufwärmen, Abkühlen (Attribut `cooldown_seconds`) |
| **Schalter „Shutter geschlossen“** | an = Shutter zu (`SHU 1`), aus = offen (`SHU 0`) |
| **Auswahl „Kanal“** | Kanalnamen vom Projektor (CineLife: `CHA?L`, Series 2: `NAM+CALL?`), sonst aus den Optionen |
| **Auswahl „Testbild“** | Liste vom Projektor (`ITP?L`), „Aus“ schaltet das Testbild ab (`ITP ""`) |
| Binärsensor „Verbunden“ | Diagnose |
| Button „Listen aktualisieren“ | liest Kanal- und Testbildliste neu (passiert sonst alle 10 min und beim Einschalten) |

Nach jedem Befehl fragt die Integration den Zustand sofort und danach
sekündlich ab, nach einem Power-Befehl bis der Projektor fertig aufgewärmt
bzw. abgekühlt ist (max. 2 min).

## Aktion `christie.send_command`

Sendet einen beliebigen Befehl und gibt alle Antworten zurück – z. B. zum
Ausprobieren oder für Funktionen, die (noch) keine Entität haben. Im Modus
„Nur lesen“ sind nur Abfragen (`…?`) erlaubt.

```yaml
action: christie.send_command
data:
  device_id: <Gerät>
  command: "(HLP?)"
response_variable: antwort
```

## Protokoll-Hinweise

Grundlage: Christie *CineLife 2.3.1 Serial Commands* (020-102774-01) und
*CineLife+ Serial Commands* (020-103075).

- Nachrichten in runden Klammern: `(PWR 1)` setzen, `(PWR?)` abfragen,
  `(PWR!001)` Antwort, Listen als `(ITP!L001 001 000 "Name")` bis `"--END--"`,
  Fehler als `(65535 00000 ERR00005 "Text")`.
- Eine persistente Verbindung, Befehle werden serialisiert, bei Abbruch
  automatische Neuverbindung.
- **Series 2** (getestet: CP2210, TPC-Software 4.8.1, `PNG` Typ 46): Kanäle sind
  nummeriert, `CHA?` liefert `101`–`164`, gesetzt wird ebenfalls per Nummer
  (`CHA 118`), die Namen kommen aus `NAM+CALL?`. Im Standby (`PWR 3`) beantwortet
  der Projektor `CHA?` und `ITP?` nicht – Kanal und Testbild zeigen dann den
  letzten bekannten Wert. „Testpattern Off“ ist Testbild 0 und erscheint als „Aus“.
- Abfragen, die ein Modell nicht kennt (z. B. `PWR+STAT` bei älteren Geräten),
  werden übersprungen und alle 10 min erneut probiert.

Debug-Log:

```yaml
logger:
  logs:
    custom_components.christie: debug
```

## Testen ohne Projektor

```bash
python3 tests/fake_christie.py 0.0.0.0 5000            # CineLife-Verhalten
python3 tests/fake_christie.py 0.0.0.0 5000 --series2  # ältere Geräte
python3 tests/test_client.py                           # Protokoll-Tests
```
