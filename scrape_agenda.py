"""
De Hallen Amsterdam – Agenda naar ICS scraper
Haalt evenementen op van dehallen-amsterdam.nl en genereert een .ics bestand.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import re
import uuid
import os

URL = "https://www.dehallen-amsterdam.nl/agenda"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

BEKENDE_CATEGORIES = [
    "Film", "Expo", "Markt", "Muziek", "Talks & Community",
    "Theater & Performance", "Workshops & Maken", "Families",
    "Eten & Drinken", "Kunst & Cultuur", "Shops"
]


def fetch_agenda():
    """Haal alle agendapagina's op en combineer de HTML."""
    all_html = []
    page = 1
    while True:
        page_url = URL if page == 1 else f"{URL}?895d75a1_page={page}"
        print(f"  Pagina {page} ophalen: {page_url}")
        response = requests.get(page_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        html = response.text
        all_html.append(html)

        # Stop als er geen "Meer laden" link meer is
        if "895d75a1_page=" not in html and page > 1:
            break
        # Maximaal 10 pagina's om oneindige loops te voorkomen
        if page >= 10:
            break
        # Controleer of de volgende pagina bestaat via de "Meer laden" link
        next_page_marker = f"895d75a1_page={page + 1}"
        if next_page_marker not in html:
            break
        page += 1

    return "\n".join(all_html)


def find_dates_near_element(element):
    """Zoek YYYY-MM-DD datums in het element zelf en zijn directe omgeving."""
    # Kijk in het element zelf
    text = element.get_text(" ", strip=True)
    dates = DATE_PATTERN.findall(text)
    if dates:
        return dates

    # Kijk in de parent
    parent = element.parent
    if parent:
        text = parent.get_text(" ", strip=True)
        dates = DATE_PATTERN.findall(text)
        if dates:
            return dates

    # Kijk in de grootouder
    grandparent = parent.parent if parent else None
    if grandparent:
        text = grandparent.get_text(" ", strip=True)
        dates = DATE_PATTERN.findall(text)
        if dates:
            return dates

    return []


def parse_link_date_text(text):
    """
    Probeer datum te parsen uit linktekst als 'Thu28May' of 'May28t/m1Jul'.
    Geeft (start_date, end_date) of (None, None).
    """
    MAANDEN = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }
    jaar = datetime.now().year

    # Patroon: bijv. "28May" of "1Jul"
    match = re.search(r"(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text)
    if match:
        dag = int(match.group(1))
        maand = MAANDEN.get(match.group(2))
        if maand:
            # Als de maand al voorbij is, gebruik volgend jaar
            now = datetime.now()
            if maand < now.month or (maand == now.month and dag < now.day):
                jaar_start = jaar + 1
            else:
                jaar_start = jaar
            try:
                return datetime(jaar_start, maand, dag), datetime(jaar_start, maand, dag)
            except ValueError:
                pass
    return None, None


def parse_events(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/agenda/" not in href or href.rstrip("/") == "/agenda":
            continue

        full_url = href if href.startswith("http") else "https://www.dehallen-amsterdam.nl" + href

        if full_url in seen_urls:
            continue
        # Nog NIET toevoegen aan seen_urls — dat doen we pas als we datum hebben

        # Tekst van de link
        link_text = link.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in link_text.split("\n") if l.strip()]

        if not lines:
            continue

        # Categorie, titel en locatie herkennen
        categorie = ""
        titel = ""
        locatie_datum = ""

        for i, line in enumerate(lines):
            for cat in BEKENDE_CATEGORIES:
                if line == cat or line.startswith(cat):
                    categorie = cat
                    titel = lines[i + 1] if i + 1 < len(lines) else ""
                    locatie_datum = lines[i + 2] if i + 2 < len(lines) else ""
                    break
            if categorie:
                break

        if not titel:
            # Probeer titel te vinden: pak de langste regel die geen datum of categorie is
            for line in lines:
                if not DATE_PATTERN.search(line) and line not in BEKENDE_CATEGORIES and len(line) > 3:
                    titel = line
                    break

        if not titel or len(titel) < 3:
            continue

        # Datums zoeken: eerst in omliggende HTML-elementen
        raw_dates = find_dates_near_element(link)

        all_dates = []
        if raw_dates:
            for d in raw_dates:
                try:
                    all_dates.append(datetime.strptime(d, "%Y-%m-%d"))
                except ValueError:
                    pass

        # Fallback: probeer datum uit de linktekst te halen
        if not all_dates:
            start_date, _ = parse_link_date_text(link_text)
            if start_date:
                all_dates = [start_date]

        if not all_dates:
            continue

        # Nu pas markeren als gezien — we hebben een datum, dus dit evenement wordt opgenomen
        seen_urls.add(full_url)

        # Bepaal of het een aaneengesloten evenement is (bijv. expo die weken loopt)
        # of losse momenten (bijv. markt op specifieke zaterdagen)
        # Aaneengesloten = elke dag een datum (max 1 dag tussenruimte)
        aaneengesloten = True
        sorted_dates = sorted(set(all_dates))
        for i in range(1, len(sorted_dates)):
            gap = (sorted_dates[i] - sorted_dates[i - 1]).days
            if gap > 2:  # meer dan 2 dagen tussenruimte = losse momenten
                aaneengesloten = False
                break

        beschrijving = (
            f"Categorie: {categorie}\n{locatie_datum}\nMeer info: {full_url}"
            if categorie else
            f"{locatie_datum}\nMeer info: {full_url}"
        ).strip()

        if aaneengesloten:
            # Één evenement van begin tot eind
            events.append({
                "titel": titel,
                "categorie": categorie,
                "locatie_datum": locatie_datum,
                "url": full_url,
                "beschrijving": beschrijving,
                "dates": [sorted_dates[0]],
                "end_date": sorted_dates[-1],
                "is_range": True,
            })
        else:
            # Eén evenement per datum
            for d in sorted_dates:
                events.append({
                    "titel": titel,
                    "categorie": categorie,
                    "locatie_datum": locatie_datum,
                    "url": full_url,
                    "beschrijving": beschrijving,
                    "dates": [d],
                    "end_date": d,
                    "is_range": False,
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
    """ICS vereist dat regels niet langer dan 75 bytes zijn (RFC 5545)."""
    result = []
    while len(line.encode("utf-8")) > 75:
        # Knip op tekenbasis zodat we geen UTF-8 kapotmaken
        cut = 74
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        result.append(line[:cut])
        line = " " + line[cut:]
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
        "X-WR-CALNAME:De Hallen Amsterdam - Agenda",
        "X-WR-CALDESC:Activiteiten agenda van De Hallen Amsterdam",
        "X-WR-TIMEZONE:Europe/Amsterdam",
    ]

    for event in events:
        start_date = event["dates"][0]
        end_date = event["end_date"]

        dtstart = start_date.strftime("%Y%m%d")
        if end_date and end_date > start_date:
            dtend = (end_date + timedelta(days=1)).strftime("%Y%m%d")
        else:
            dtend = (start_date + timedelta(days=1)).strftime("%Y%m%d")

        # Unieke UID per evenement + datum (zodat losse momenten elk eigen UID hebben)
        uid_base = f"{event['url']}:{dtstart}"
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, uid_base))

        event_lines = [
            "BEGIN:VEVENT",
            fold_line(f"UID:{uid}@dehallen-amsterdam.nl"),
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            fold_line(f"SUMMARY:{escape_ics(event['titel'])}"),
            fold_line(f"DESCRIPTION:{escape_ics(event['beschrijving'])}"),
            fold_line(f"URL:{event['url']}"),
        ]
        if event["categorie"]:
            event_lines.append(fold_line(f"CATEGORIES:{escape_ics(event['categorie'])}"))
        event_lines.append("END:VEVENT")
        lines.extend(event_lines)

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    print("Agenda ophalen van De Hallen Amsterdam...")
    html = fetch_agenda()
    events = parse_events(html)

    print(f"{len(events)} agenda-items aangemaakt.")
    for e in events[:5]:
        print(f"  - {e['titel']} | {e['dates'][0].strftime('%Y-%m-%d')} | {'reeks' if e['is_range'] else 'losse datum'}")

    ics_content = generate_ics(events)

    output_path = os.path.join(os.path.dirname(__file__), "agenda.ics")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"ICS-bestand opgeslagen: {output_path}")


if __name__ == "__main__":
    main()
