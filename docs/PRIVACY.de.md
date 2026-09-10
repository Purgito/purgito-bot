# Datenschutzrichtlinie (Privacy Policy)

**Zuletzt aktualisiert:** 16. August 2026

Diese Richtlinie beschreibt, wie **Purgito** die Informationen erhebt, nutzt, speichert und schützt, die zur Bereitstellung seiner Funktionen nötig sind.

Purgito ist ein öffentlicher Discord-Bot, der von mehreren Servern genutzt wird. Die Daten, die wir erheben, und wie wir sie verarbeiten, sind für alle Server gleich, auf denen der Bot vorhanden ist.

---

# 1. Erhobene Informationen

Um korrekt zu funktionieren, kann der Bot folgende Informationen speichern:

## Discord-Informationen

- Nutzer-IDs.
- Server-IDs.
- Kanal-IDs.

Diese Kennungen werden ausschließlich für den internen Betrieb des Bots verwendet.

---

## Nachrichteninhalt

Wenn die Lernfunktionen aktiviert sind, speichert der Bot den Inhalt von Textnachrichten, die in zugelassenen Kanälen gesendet werden.

Diese Nachrichten können verwendet werden, um:

- Lokale Markov-Ketten zu trainieren.
- Automatische Antworten im Chat zu generieren.
- Den Schreibstil von Nutzern zu imitieren.
- Als begrenzte Vokabular-Stichprobe bei der Meme-Generierung zu dienen (lokal mit Markov oder über die optionale Groq-Integration, falls konfiguriert).

Als **NSFW** markierte Kanäle in Discord sind von diesem Lernen immer ausgenommen: Purgito speichert niemals Nachrichten aus einem NSFW-Kanal, ohne Ausnahme und ohne Möglichkeit, dies manuell für den Corpus zu aktivieren. Wird ein Kanal, der bereits für den Corpus aktiviert war, später als NSFW markiert, wird der bereits gespeicherte Verlauf dieses Kanals sofort gelöscht.

---

## Multimedia

Der Bot kann speichern:

- URLs von Bildern.
- URLs von GIFs.
- Mediendateien, die für die Funktionen der GIF-Galerie und der Meme-Sammlung nötig sind.

Wo zutreffend, können diese Dateien dauerhaft über Cloudflare R2 gespeichert werden.

---

## Anzeigename

Der Anzeigename (Display Name) eines Nutzers kann zusammen mit bestimmten Nachrichten gespeichert werden, um Funktionen wie die Nutzerimitation zu ermöglichen.

---

## Anmeldung im Web-Panel

Beim Anmelden auf purgito.app mit Discord werden die Berechtigungen (Scopes) `identify`, `email` und `guilds` angefragt. Damit können wir dir deinen Benutzernamen, Avatar und deine E-Mail innerhalb deiner eigenen Sitzung anzeigen und dein Discord-Konto mit den Servern verknüpfen, die du verwaltest (der Scope `guilds` ist das, was uns erlaubt zu wissen, auf welchen Servern du Administratorrechte hast, damit wir dir in deinem Panel nur diese anzeigen). Es wird ein Sitzungscookie gespeichert, um dich beim Navigieren auf der Seite eingeloggt zu halten; dieses Cookie wird nicht zu Werbe- oder seitenübergreifenden Tracking-Zwecken verwendet.

---

## Audit-Log des Panels

Wenn ein Administrator eine Konfigurationsänderung über das Web-Panel vornimmt (Befehl `/settings`), speichert Purgito ein eigenes Audit-Log für diesen Server: die Discord-ID und den Anzeigenamen der Person, die die Änderung vorgenommen hat, um welche Art von Aktion es sich handelte (zum Beispiel das Hinzufügen einer speziellen Phrase, das Hinzufügen eines GIFs oder das Leeren des Corpus eines Kanals) und in manchen Fällen ein Freitext-Detail, das wörtlich von der Person geschriebenen Inhalt enthalten kann.

Dieses Log ist ausschließlich für die Administratoren desselben Servers sichtbar, im Tab Verlauf des Panels, und existiert, damit die Community sehen kann, welche Änderungen gemacht wurden und von wem. Es wird maximal 90 Tage aufbewahrt und danach automatisch gelöscht (siehe "Datenspeicherung").

---

Der Bot **erhebt nicht**:

- Passwörter.
- E-Mail-Adressen, außer der, die Discord bei der Anmeldung im Web-Panel (purgito.app) übermittelt — diese E-Mail wird nur genutzt, um dich innerhalb deiner eigenen Sitzung zu identifizieren, und wird nicht an Dritte weitergegeben.
- Persönliche Daten außer den von der offiziellen Discord-API bereitgestellten.

**IP-Adressen:** Das Dashboard (purgito.app) verarbeitet deine IP-Adresse vorübergehend und eng begrenzt, ausschließlich um Missbrauch vorzubeugen (Ratenbegrenzung von Anfragen). Diese IP existiert nur im Arbeitsspeicher des Prozesses für ein kurzes Zeitfenster (Sekunden bis Minuten), wird niemals in der Datenbank oder in einem dauerhaften Log gespeichert und nicht an Dritte weitergegeben.

Zu Zahlungsdaten siehe den Abschnitt **"Zahlungen und Abonnements"** weiter unten: Purgito speichert sie nicht, aber der Zahlungsabwickler (Polar.sh) erhebt sie bei der Abwicklung eines Kaufs.

---

## Zahlungen und Abonnements

Wenn ein Server Premium über das Dashboard (purgito.app) bucht, wird die Zahlung von **Polar.sh** verarbeitet, nicht von Purgito.

**Purgito speichert ausschließlich:**

- Die ID des Servers (guild_id) mit aktivem Premium.
- Das Datum der Aktivierung.
- Einen Textvermerk zur Identifikation des Plans (zum Beispiel "Polar — monatlich" oder "Polar — jährlich").

Purgito **speichert nicht** Kartennummer, Rechnungsdaten, E-Mail oder Namen der kaufenden Person.

**Polar.sh erhebt sehr wohl** die für die Zahlungsabwicklung nötigen Daten (Karte, E-Mail, Rechnungsdaten) gemäß seiner eigenen [Datenschutzrichtlinie](https://polar.sh/legal/privacy). Diese Datenbeziehung besteht zwischen der kaufenden Person und Polar.sh als Abwickler/Merchant of Record.

---

# 2. Nutzung der Informationen

Die erhobenen Informationen werden ausschließlich genutzt, um die Funktionen des Bots bereitzustellen, einschließlich:

- Textgenerierung über lokale Markov-Ketten.
- Meme- und Caption-Generierung (lokal oder über die optionale Groq-Integration).
- GIF-Galerie.
- Automatisierungen des Servers.
- Konfiguration von Befehlen und Einstellungen.

Die Daten werden **nicht verkauft** und von Purgito nicht für Werbung genutzt.

---

# 3. Dienste Dritter

Purgito nutzt externe Dienste für bestimmte Funktionen. Jeder Anbieter verarbeitet ausschließlich die Informationen, die für die Erbringung seines Dienstes nötig sind.

## Discord und Speicherung

- **Discord**: Für Kommunikation, Empfang von Ereignissen, Authentifizierung und den Versand von Nachrichten auf der Plattform.
- **Cloudflare R2**: Für die dauerhafte Speicherung von Mediendateien (Bilder aus dem Meme-Pool des Servers und in die Galerie hochgeladene GIFs).

## Groq API (KI-Captions für Memes)

- **Was es ist und wofür es genutzt wird**: Groq ist ein externer Anbieter für die Inferenz von KI-Modellen (Bild und Sprache), der optional und ausschließlich genutzt wird, um Bilder zu analysieren und Captions in der Meme-Funktion zu verfassen.
- **Welche Daten übermittelt werden können**: Das für das Meme verwendete Bild (base64-kodiert) und eine begrenzte Stichprobe des Corpus des Servers (bis maximal 25 kurze und 15 lange Nachrichten, als Referenz für Vokabular und Ton).
- **Wann es zum Einsatz kommt**: Ausschließlich beim Anfordern oder Ausführen der Generierung eines Memes (Befehl `/momo`, Trigger-Antwort auf ein Bild oder geplantes Meme) und nur, wenn der Schlüssel `GROQ_API_KEY` vom Betreiber des Bots konfiguriert wurde.
- **Eng begrenzter Umfang**: Groq verarbeitet keine gewöhnlichen Chat-Unterhaltungen und erhält nicht den vollständigen Corpus irgendeines Servers. Die allgemeine Unterhaltung von Purgito läuft zu 100 % lokal.
- **Lokaler Fallback**: Wenn Groq nicht konfiguriert, nicht verfügbar ist oder fehlschlägt, erfolgt die Caption-Generierung zu 100 % lokal über Markov-Ketten.
- **Werbung**: Die für diese Funktion an Groq übermittelten Daten werden von Purgito nicht für Werbezwecke oder den Verkauf von Daten genutzt.

## Zahlungen und Infrastruktur

- **Polar.sh**: Zahlungsabwickler und Merchant of Record für die Premium-Abonnements. Siehe dessen [Datenschutzrichtlinie](https://polar.sh/legal/privacy).
- Andere Infrastrukturdienste, die für den Betrieb des Bots zwingend nötig sind.

---

# 4. Datenspeicherung

Die erhobenen Daten werden nur so lange aufbewahrt, wie sie für den Betrieb des Bots nötig sind.

Der Nachrichtenverlauf wird nicht unbegrenzt aufbewahrt, auch nicht solange der Server aktiv ist: Jeder Server hat ein maximales Kontingent an gespeicherten Nachrichten (höher bei Servern mit Premium). Ist dieses Kontingent erreicht, werden die ältesten Nachrichten automatisch verworfen, sobald neue Nachrichten gespeichert werden, ohne dass ein Administrator manuell eingreifen muss.

Die Administratoren des Servers können erhobene Inhalte außerdem jederzeit über das interaktive Konfigurationspanel löschen (Befehl `/settings`), das Schaltflächen zum Leeren des gelernten Nachrichten-Corpus und zum Löschen gespeicherter GIFs enthält.

Das Audit-Log des Panels (siehe Abschnitt 1) wird maximal 90 Tage ab jedem Eintrag aufbewahrt und danach automatisch bereinigt, ohne manuellen Eingriff.

Wenn der Bot einen Server verlässt (zum Beispiel, wenn er entfernt wird), werden die Daten dieses Servers für eine Karenzzeit von 30 Tagen aufbewahrt, bevor sie vollständig gelöscht werden. Das soll sicherstellen, dass der Server, falls der Bot innerhalb dieser Frist erneut eingeladen wird, seine Konfiguration und seine Inhalte zurückbekommt, ohne von vorne anfangen zu müssen. Während dieser Zeit, solange der Bot nicht auf dem Server ist, gibt es keine Möglichkeit, auf das Verwaltungspanel zuzugreifen, um diese Daten zu verwalten. Derzeit gibt es keinen Self-Service-Weg, um diese Löschung auf Serverebene vor Ablauf der 30 Tage zu beschleunigen; wenn du Administrator eines Servers bist und möchtest, dass dessen Daten vor diesem Zeitpunkt gelöscht werden, kannst du dies beantragen, indem du den Entwickler kontaktierst (siehe "Kontakt" weiter unten).

---

## Löschung deiner eigenen Daten (individuelles Recht auf Vergessenwerden)

Unabhängig vom Vorstehenden kann jeder Nutzer jederzeit verlangen, dass seine eigenen Informationen gelöscht werden, ohne Administrator eines Servers sein zu müssen oder die 30 Tage aus dem vorigen Punkt abwarten zu müssen.

Der Befehl `/borrar_mis_datos`, verfügbar für jede Person auf jedem Server, auf dem Purgito vorhanden ist, löscht dauerhaft und sofort, auf **allen** Servern, auf denen du geschrieben hast:

- Deinen für die Imitationsfunktion (`/imitar`) gespeicherten Schreibstil.
- Die Nachrichten, die Purgito von dir gelernt hat, um Text zu generieren.

Deine ursprünglichen Discord-Nachrichten sind davon nicht betroffen: Dies löscht nur die Kopie, die Purgito gespeichert hat, um von deiner Schreibweise zu lernen. Da es sich um eine unumkehrbare Aktion handelt, verlangt der Befehl eine ausdrückliche Bestätigung, bevor die Löschung ausgeführt wird.

Diese Löschung ist speziell für die oben beschriebenen Nachrichten-Lerndaten gedacht und deckt nicht automatisch andere Kategorien ab, die du auf einem Server erzeugt haben könntest — zum Beispiel GIFs oder Bilder, die du zum Pool des Servers beigetragen hast, oder deine eigenen Einträge im Audit-Log des Panels, falls du Administrator bist — da diese dem Server zugeordnet sind, auf dem sie erzeugt wurden, nicht nur deinem Konto. Wenn du die Löschung von etwas davon beantragen möchtest, kannst du den Entwickler kontaktieren (siehe "Kontakt").

---

# 5. Rechte der Nutzer

Jeder Nutzer kann seine eigenen Informationen jederzeit mit dem Befehl `/borrar_mis_datos` löschen (siehe Abschnitt 4), ohne Administrator eines Servers sein zu müssen.

Die Administratoren des Servers verfügen außerdem über eigene Werkzeuge, um die Datenerhebung ihrer Community zu steuern (siehe Abschnitt 4), einschließlich der Möglichkeit, bestimmte Nutzer auszuschließen: unabhängig voneinander können sie festlegen, dass Purgito nicht mit diesem Nutzer interagiert (nicht antwortet, reagiert oder Trigger auslöst) und/oder nicht von dessen Nachrichten lernt (sie weder für den Corpus noch für die Imitationsfunktion nutzt).

Wenn du der Ansicht bist, dass es Informationen gibt, die gelöscht werden sollten und die nicht von diesen Self-Service-Werkzeugen abgedeckt sind, oder Fragen zur Verarbeitung der Daten hast, kannst du den Entwickler kontaktieren.

Wo es technisch möglich ist, wird angemessenen Löschanfragen entsprochen.

---

# 6. Minderjährige

Purgito richtet sich an Nutzer, die die von Discord festgelegten Mindestaltersanforderungen erfüllen.

Der Abschluss eines Premium-Abonnements setzt Geschäftsfähigkeit voraus, oder die Zustimmung eines verantwortlichen Erwachsenen. Purgito überprüft dies nicht aktiv; es liegt in der Verantwortung der kaufenden Person.

---

# 7. Sicherheit

Es werden angemessene Maßnahmen ergriffen, um die gespeicherten Informationen zu schützen.

Dennoch kann kein System absolute Sicherheit vor Zwischenfällen oder unbefugtem Zugriff garantieren.

---

# 8. Änderungen dieser Richtlinie

Diese Richtlinie kann aktualisiert werden, um neue Funktionen, technische Verbesserungen oder rechtliche Änderungen widerzuspiegeln.

Das Datum "Zuletzt aktualisiert" zeigt stets die geltende Version an.

Der Code von Purgito liegt auf GitHub, wo eine öffentliche Versionshistorie geführt wird.

---

# 9. Kontakt

Wenn du Fragen zu dieser Richtlinie hast oder die Löschung von Informationen im Zusammenhang mit dem Bot beantragen möchtest, kannst du den Entwickler erreichen über:

- E-Mail: contacto@purgito.app.
- Den offiziellen Discord-Server des Projekts (sofern zutreffend).
