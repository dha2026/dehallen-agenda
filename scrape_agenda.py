"""
De Hallen Amsterdam – Agenda naar ICS scraper
Haalt evenementen op van dehallen-amsterdam.nl en genereert een .ics bestand.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
import uuid
import os

URL = "https://www.dehallen-amsterdam.nl/agenda"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AgendaScraper/1.0)"
}


def fetch_agenda():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


def parse_events(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # Zoek alle agenda-items (links met categorie, titel, locatie, datum)
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/agenda/" not in href or href == "/agenda":
            continue

        text = link.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        if len(lines) < 2:
            continue

        # Probeer categorie, titel en locatie/datum te herkennen
        categorie = ""
        titel = ""
        locatie_datum = ""

        # Categorieën zoals "Film", "Expo", "Markt", etc.
        bekende_categories = [
            "Film", "Expo", "Markt", "Muziek", "Talks & Community",
            "Theater & Performance", "Workshops & Maken", "Families",
            "Eten & Drinken", "Kunst & Cultuur", "Shops"
        ]

        for i, line in enumerate(lines):
            for cat in bekende_categories:
                if line.strip() == cat or line.startswith(cat):
                    categorie = cat
                    if i + 1 < len(lines):
                        titel = lines[i + 1]
                    if i + 2 < len(lines):
                        locatie_datum = lines[i + 2]
                    break
            if categorie:
                break

        if not titel and lines:
            titel = lines[0]
        if not locatie_datum and len(lines) > 1:
            locatie_datum = lines[-1]

        if not titel or len(titel) < 3:
            continue

        # Verwijder dubbelen op basis van URL
        full_url = href if href.startswith("http") else "https://www.dehallen-amsterdam.nl" + href
        if any(e["url"] == full_url for e in events):
            continue

        # Beschrijving: combineer beschikbare info
        beschrijving = f"Categorie: {categorie}\\n{locatie_datum}\\nMeer info: {full_url}" if categorie else f"{locatie_datum}\\nMeer info: {full_url}"

        # Probeer datum te parsen uit data-attributen of tekst
        dates = link.get("data-dates") or link.get("data-date") or ""
        start_date = None
        end_date = None

        if dates:
            date_list = [d.strip() for d in dates.split(",") if d.strip()]
            if date_list:
                try:
                    start_date = datetime.strptime(date_list[0], "%Y-%m-%d")
                    end_date = datetime.strptime(date_list[-1], "%Y-%m-%d")
                except ValueError:
                    pass

        events.append({
            "titel": titel,
            "categorie": categorie,
            "locatie_datum": locatie_datum,
            "url": full_url,
            "beschrijving": beschrijving,
            "start_date": start_date,
            "end_date": end_date,
        })

    return events


def escape_ics(text):
    """Ontsnap speciale tekens voor ICS-formaat."""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


def fold_line(line):
    """ICS vereist dat regels niet langer dan 75 tekens zijn (RFC 5545)."""
    result = []
    while len(line.encode("utf-8")) > 75:
        result.append(line[:75])
        line = " " + line[75:]
    result.append(line)
    return "\r\n".join(result)


def generate_ics(events):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//De Hallen Amsterdam//Agenda//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:De Hallen Amsterdam – Agenda",
        "X-WR-CALDESC:Activiteiten agenda van De Hallen Amsterdam",
        "X-WR-TIMEZONE:Europe/Amsterdam",
    ]

    for event in events:
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, event["url"]))

        if event["start_date"]:
            dtstart = event["start_date"].strftime("%Y%m%d")
            if event["end_date"] and event["end_date"] != event["start_date"]:
                # Einddatum is exclusief in ICS (all-day), dus +1 dag
                from datetime import timedelta
                dtend = (event["end_date"] + timedelta(days=1)).strftime("%Y%m%d")
            else:
                from datetime import timedelta
                dtend = (event["start_date"] + timedelta(days=1)).strftime("%Y%m%d")
            dtstart_line = f"DTSTART;VALUE=DATE:{dtstart}"
            dtend_line = f"DTEND;VALUE=DATE:{dtend}"
        else:
            # Geen datum bekend: gebruik vandaag
            today = datetime.now().strftime("%Y%m%d")
            dtstart_line = f"DTSTART;VALUE=DATE:{today}"
            dtend_line = f"DTEND;VALUE=DATE:{today}"

        lines += [
            "BEGIN:VEVENT",
            fold_line(f"UID:{uid}@dehallen-amsterdam.nl"),
            f"DTSTAMP:{now}",
            dtstart_line,
            dtend_line,
            fold_line(f"SUMMARY:{escape_ics(event['titel'])}"),
            fold_line(f"DESCRIPTION:{escape_ics(event['beschrijving'])}"),
            fold_line(f"URL:{event['url']}"),
            fold_line(f"CATEGORIES:{escape_ics(event['categorie'])}") if event["categorie"] else "",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")

    # Verwijder lege regels
    lines = [l for l in lines if l]
    return "\r\n".join(lines) + "\r\n"


def main():
    print("Agenda ophalen van De Hallen Amsterdam...")
    html = fetch_agenda()
    events = parse_events(html)
    print(f"{len(events)} evenementen gevonden.")

    ics_content = generate_ics(events)

    output_path = os.path.join(os.path.dirname(__file__), "agenda.ics")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"ICS-bestand opgeslagen: {output_path}")


if __name__ == "__main__":
    main()
