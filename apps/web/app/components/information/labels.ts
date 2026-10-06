/**
 * Docgrain Hospitality & Bilgi screen localized labels.
 *
 * wp52 (discovered collections) can replace or extend this mapping later.
 */

export const COLLECTION_LABELS: Record<string, string> = {
  rooms: "Odalar",
  outlets: "Mekanlar (Restoran/Bar)",
  activities: "Etkinlikler",
  facilities: "Olanaklar",
  policies: "Kurallar ve Politikalar",
  contacts: "İletişim",
  contact: "İletişim",
  properties: "Tesis Bilgileri",
  property: "Tesis Bilgileri",
  service_prices: "Hizmet Fiyatları",
  services: "Hizmet Fiyatları",
  meeting_rooms: "Toplantı Odaları",
};

export const FIELD_LABELS: Record<string, string> = {
  name: "Ad",
  title: "Başlık",
  capacity: "Kapasite",
  bed_types: "Yatak tipleri",
  view: "Manzara",
  features: "Özellikler",
  size_m2: "Büyüklük (m²)",
  address: "Adres",
  description: "Açıklama",
  category: "Kategori",
  kind: "Tür",
  hours: "Çalışma saatleri",
  opening_hours: "Açılış saatleri",
  fee: "Ücret",
  price: "Fiyat",
  reservation: "Rezervasyon",
  schedule: "Program / Saatler",
  age_range: "Yaş aralığı",
  text: "Metin",
  applies_to: "Geçerlilik alanı",
  value: "Değer",
  amount: "Tutar",
  currency: "Para birimi",
  unit: "Birim",
  conditions: "Koşullar",
  phone: "Telefon",
  email: "E-posta",
  website: "Web sitesi",
  location: "Konum",
  status: "Durum",
  notes: "Notlar",
  created_at: "Oluşturulma tarihi",
  updated_at: "Güncellenme tarihi",
};

/**
 * Converts snake_case or kebab-case keys to a human-readable title:
 * e.g. "snake_case" -> "Snake case", "bed_types" -> "Bed types"
 */
export function humanizeKey(key: string): string {
  if (!key) return "";
  const cleaned = key.replace(/[-_]+/g, " ").trim();
  if (!cleaned) return key;
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1).toLowerCase();
}

/**
 * Returns Turkish label for a collection key or falls back to humanized key.
 */
export function getCollectionLabel(key: string): string {
  return COLLECTION_LABELS[key] || humanizeKey(key);
}

/**
 * Returns Turkish label for a field key or falls back to humanized key.
 */
export function getFieldLabel(key: string): string {
  return FIELD_LABELS[key] || humanizeKey(key);
}
