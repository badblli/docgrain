"""Bounded TR/EN/DE/RU structure vocabulary (WP122); never a general translator.

Only the explicit concepts below have English comparison/storage keys. Unknown labels
retain their normalized spelling for comparison. Source labels and values never change.
Existing TR/EN field outputs are compatibility-sensitive: e.g. Mutfak stays ``mutfak``.
"""

import re

from .normalize import fold

# Existing TR/EN outputs are kept verbatim for accepted workspace schemas.
FIELD_KEYS = {
    "name": "name", "ad": "name", "adi": "name", "isim": "name", "ismi": "name", "title": "name",
    "description": "description", "aciklama": "description", "detail": "detail", "detay": "detail",
    "ayrinti": "detail", "price": "price", "fiyat": "price", "ucret": "price", "tutar": "price",
    "cost": "price", "hours": "hours", "saat": "hours", "saatler": "hours", "saatleri": "hours",
    "opening hours": "hours", "acilis saatleri": "hours", "calisma saatleri": "hours",
    "hizmet saatleri": "hours", "open": "opening_time", "opens": "opening_time",
    "acilis": "opening_time", "closes": "closing_time", "kapanis": "closing_time",
    "capacity": "capacity", "kapasite": "capacity", "kisi": "capacity", "kisi sayisi": "capacity",
    "phone": "phone", "telefon": "phone", "tel": "phone", "email": "email", "e mail": "email",
    "e posta": "email", "eposta": "email", "address": "address", "adres": "address",
    "location": "location", "konum": "location", "yer": "location", "date": "date",
    "tarih": "date", "duration": "duration", "sure": "duration", "floor": "floor", "kat": "floor",
    "type": "category", "tur": "category", "tip": "category", "kategori": "category",
    "category": "category", "notes": "notes", "note": "notes", "not": "notes", "notlar": "notes",
    "size": "size", "alan": "size", "buyukluk": "size", "website": "website", "web": "website",
    "web sitesi": "website", "unit": "unit", "birim": "unit", "currency": "currency",
    "para birimi": "currency", "day": "day", "gun": "day", "gunler": "days", "days": "days",
}
COLLECTION_KEYS = {
    "restaurants": "restaurants", "restaurant": "restaurants", "restoran": "restaurants",
    "restoranlar": "restaurants", "bars": "bars", "bar": "bars", "barlar": "bars",
    "rooms": "rooms", "room": "rooms", "oda": "rooms", "odalar": "rooms",
    "activities": "activities", "aktiviteler": "activities", "etkinlikler": "activities",
    "services": "services", "hizmetler": "services", "prices": "prices", "fiyatlar": "prices",
    "fiyat listesi": "prices", "price list": "prices", "contacts": "contacts",
    "iletisim": "contacts", "contact": "contacts", "products": "products", "urunler": "products",
    "menu": "menu_items", "menuler": "menu_items", "staff": "staff_members",
    "personel": "staff_members", "courses": "courses", "kurslar": "courses",
    "dersler": "courses", "events": "events", "branches": "branches", "subeler": "branches",
    "meeting rooms": "meeting_rooms", "toplanti salonlari": "meeting_rooms",
    "pools": "pools", "havuzlar": "pools", "policies": "policies", "kurallar": "policies",
}

# German and Russian labels for the same concepts; no new TR/EN field mappings.
FIELD_KEYS.update({
    "name": "name", "bezeichnung": "name", "название": "name", "имя": "name",
    "beschreibung": "description", "описание": "description",
    "einzelheiten": "detail", "подробности": "detail",
    "preis": "price", "kosten": "price", "цена": "price", "стоимость": "price",
    "offnungszeiten": "hours", "часы работы": "hours", "время работы": "hours",
    "offnung": "opening_time", "открытие": "opening_time",
    "schliessung": "closing_time", "закрытие": "closing_time",
    "kapazitat": "capacity", "вместимость": "capacity",
    "телефон": "phone", "электронная почта": "email",
    "adresse": "address", "адрес": "address",
    "standort": "location", "lage": "location", "расположение": "location",
    "datum": "date", "дата": "date", "dauer": "duration", "длительность": "duration",
    "etage": "floor", "этаж": "floor", "kategorie": "category", "категория": "category",
    "тип": "category", "hinweise": "notes", "примечания": "notes",
    "grosse": "size", "размер": "size", "площадь": "size", "сайт": "website",
    "einheit": "unit", "единица": "unit", "wahrung": "currency", "валюта": "currency",
    "tag": "day", "день": "day", "tage": "days", "дни": "days",
})
COLLECTION_KEYS.update({
    "ресторан": "restaurants", "рестораны": "restaurants",
    "бар": "bars", "бары": "bars", "zimmer": "rooms", "номер": "rooms", "номера": "rooms",
    "aktivitaten": "activities", "мероприятия": "activities",
    "dienstleistungen": "services", "услуги": "services",
    "preise": "prices", "preisliste": "prices", "цены": "prices", "прайс лист": "prices",
    "kontakte": "contacts", "kontakt": "contacts", "контакты": "contacts",
    "produkte": "products", "продукты": "products", "товары": "products",
    "speisekarte": "menu_items", "меню": "menu_items",
    "mitarbeiter": "staff_members", "персонал": "staff_members",
    "kurse": "courses", "курсы": "courses", "veranstaltungen": "events", "события": "events",
    "filialen": "branches", "филиалы": "branches",
    "besprechungsraume": "meeting_rooms", "konferenzraume": "meeting_rooms",
    "конференц залы": "meeting_rooms", "бассеины": "pools",
    "richtlinien": "policies", "regeln": "policies", "правила": "policies",
})


def vocabulary_key(label: str | None) -> str:
    """Same folding as the original field lookup (including Turkish dotless i)."""
    return " ".join(fold(label or "").replace("ı", "i").split())


def _tokens(label: str | None) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W_]+", vocabulary_key(label)))


# Longest phrases win: 'meeting rooms' must not also count as the distinct kind 'rooms'.
_COLLECTION_PHRASES = sorted(
    {(_tokens(label), key) for label, key in COLLECTION_KEYS.items()}
    | {(_tokens(key), key) for key in COLLECTION_KEYS.values()},
    key=lambda pair: (-len(pair[0]), pair))


def known_collection_key(title: str | None) -> str | None:
    """Known head noun at the end of a title; mixed kinds are deliberately unknown.

    'A la carte restaurants', 'Ana restoranlar', 'Unsere Restaurants' are restaurants.
    'Restaurants & Bars' is unknown, as are 'Restaurants overview' and unlisted concepts.
    Only token boundaries match; this does not translate arbitrary text.
    """
    tokens = _tokens(title)
    kinds, head = set(), None
    index = 0
    while index < len(tokens):
        match = next(((phrase, key) for phrase, key in _COLLECTION_PHRASES
                      if tokens[index:index + len(phrase)] == phrase), None)
        if match:
            phrase, key = match
            kinds.add(key)
            index += len(phrase)
            if index == len(tokens):
                head = key
        else:
            index += 1
    return head if len(kinds) == 1 else None
