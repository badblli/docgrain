# Docgrain marka kılavuzu

Uygulayıcı (Codex) için kısa kılavuz. Görsel referans: `docs/brand/docgrain-brand.html` (marka panosu).
Token kaynağı: `docs/brand/tokens.css`. Logolar: `apps/web/public/brand/`.

Fikir: **sakin bir şirket defteri.** Sayfa sessizdir; dikkat yalnızca bir insanın cevabı gerektiğinde
(amber) çekilir. Her bilgi kaynağıyla birlikte görünür; çelişki sorulur, tahmin edilmez.

## 1. Logo

- **Kavram:** dokuz taneye bölünmüş bir sayfa; sağ üst tane kıvrık köşedir. Belge, yerini bilen bilgi
  tanelerine ayrılır. Kelime işareti tek kalınlıkta çizgiyle çizilmiş küçük harf `docgrain`; i'nin
  noktası da kare bir tanedir.
- **Dosyalar:**
  - `logo.svg`: işaret + kelime. Kenar çubuğu, giriş ekranı, e-posta. Koyu temada kendi rengini değiştirir.
  - `logo-mark.svg`: yalnızca işaret, 24 px ve üstü.
  - `favicon.svg`: 16 px piksel ızgarasına oturan işaret (4/2/4/2/4). Sekme ikonu ve 20 px altı.
  - `logo-mono.svg`: tek renk, `currentColor`. Satır içi SVG olarak kullanılırsa metin rengini alır.
- **Kurallar:** çevrede en az bir tane (işaretin ¼'ü) boşluk. Tam logo en az 96 px genişlik, işaret en az
  16 px. Kenar çubuğunda logo yüksekliği 22 px. Kelime her zaman küçük harf; cümle içinde ürün adı "Docgrain".
- **Yapma:** gradyan, gölge, kontur, parıltı yok. Döndürme, kıvrık köşeyi taşıma, i tanesini ayrı renge
  boyama yok. İşareti renkli kutuya koyma (eski `.brandMark` çerçevesini kaldır).
- Uygulama: `app/layout` içinde `<link rel="icon" href="/brand/favicon.svg" type="image/svg+xml">`.

## 2. Renk rolleri

`tokens.css` içindeki adlar wp60 adlarıyla aynıdır (`--ground`, `--paper`, `--ink` …); dosyayı
`globals.css` ve `screens.css` içindeki `:root` bloklarının yerine koy. `globals.css` içindeki eski nötr
(Notion kahvesi `#37352f`) değerleri ve `.btn.pri` gibi sabit renkler token'a çevrilmeli.

| Rol | Token | Açık | Koyu | Kullanım |
|---|---|---|---|---|
| Zemin | `--ground` | #fafbf9 | #0e1514 | Uygulama arka planı |
| Kağıt | `--paper` | #ffffff | #141c1b | Kart, kenar çubuğu, giriş alanı |
| Sessiz dolgu | `--sheet` | #f5f7f6 | #18211f | Üzerine gelme, tablo başlığı |
| Çukur | `--sunken` | #eef2f0 | #0b1110 | İlerleme yolu, boş çubuk |
| Mürekkep | `--ink` / `--ink2` | #223333 / #445554 | #e2eae7 / #c0ccc9 | Başlık, değer / gövde |
| İkincil | `--muted` / `--faint` | #647573 / #73817f | #92a29f / #7f8f8c | Açıklama / meta (≥ 11 px) |
| Çizgi | `--line` / `--line2` | #dce3e0 / #edf0ee | #283331 / #1e2826 | Kart kenarı / kart içi ayraç |
| Vurgu | `--accent` | #245d65 | #79b7bd | Birincil düğme, seçili menü, bağlantı, odak |
| Vurgu zemini | `--accent-soft` | #eaf2f2 | #17302f | Seçili menü, seçilen kaynak |
| İşaret | `--mark` | #dcecea | #1f3d3d | Alıntıda değerin geçtiği yer |
| Onay | `--ok` (+ `-soft`, `-line`) | #327251 | #7cc39a | Onaylandı, kaynağı var |
| Uyarı | `--warn` (+ `-soft`, `-line`) | #956316 | #e2b45f | Kaynaklar farklı söylüyor, inceleme bekliyor, soru rozeti |
| Tehlike | `--danger` (+ `-soft`, `-line`) | #a5423a | #ec8f86 | Reddedildi, hata. `--err` takma adı korunur |

- Tek vurgu rengi var. Durum renkleri (yeşil, amber, kırmızı) yalnızca durum anlatır; süs, ikon rengi
  ya da kategori rengi olarak kullanılmaz.
- Koyu tema ayrı tasarlandı: vurgu açık teal'e döner, birincil düğme metni `--on-accent` (koyu) olur.
  Bileşenlerde hiçbir sabit renk yazma; her renk token'dan gelir.
- Mor `--derived` ve koyu `.json` bloğu geliştirici ekranlarına aittir; kullanıcı ekranlarında kullanma.

## 3. Yazı rolleri

- **Instrument Sans** (`--f-ui`): tüm arayüz. Başlık 600, gövde 400, metrik değeri 500. Başlıklarda
  `letter-spacing` −0,02 … −0,035em.
- **Source Serif 4** (`--f-doc`): yalnızca belgeden aynen gelen metin (alıntı, belge önizlemesi). Başlıkta,
  şirket adında, düğmede kullanılmaz. Okuyan kişi belgenin sesini Docgrain'in sesinden yazıdan ayırır.
  (Şu anki `.summaryHeader h1` serif; Instrument Sans'a çevir.)
- **JetBrains Mono** (`--f-mono`): konum (`satır 118`, `sayfa 2`, `B14`), belge tarihi, sayaç (`3 / 7`),
  API yolu. 11–12 px, `--faint`.
- Ölçek: 11 · 12 · 13 · 14 (gövde) · 16 · 18 · 23 · 30 · 36. Rakamlar hizalanıyorsa
  `font-variant-numeric: tabular-nums`.

## 4. Ses

- Türkçe, cümle düzeni büyük harf: "Sizden bir cevap bekliyor", "Tüm sorular". BAŞLIK DÜZENİ YOK.
- Sade kelime, kullanıcının gördüğü şeyin adı: **Koleksiyonlar** (asla "Bilgiler"), **Belgeler**,
  **Sorular**, **kayıt**, **kaynak**. "Pipeline", "chunk", "candidate", "record" kullanıcı ekranında geçmez.
- Düğme ne olacağını söyler: "Bu belge güncel", "Kaydet", "Belge ekle". Sonuç bildirimi geçmiş zaman:
  "Kaydedildi. Bahçe manzarası onaylandı."
- Hata ne olduğunu ve nasıl düzeleceğini söyler, özür dilemez: "Doğru değeri sayı olarak yazın."
- Emoji, ünlem, "Harika!" yok.

## 5. Bileşen kuralları

**Genel.** Kartlar `--paper`, 1 px `--line`, radius 12, gölge yok. Gölge (`--shadow-2`) yalnızca yüzen
öğelerde: menü, bildirim, diyalog. İç paneller radius 8. Düğme ve giriş yüksekliği 38 px (küçük 30 px).
Odak: `outline: 2px solid var(--focus); outline-offset: 2px` her etkileşimli öğede.

**Kenar çubuğu.** Genişlik 244 px, `--paper`, sağda hairline. Yukarıdan aşağı: logo (22 px yükseklik) →
"Şirket" seçici (baş harf kutusu + şirket adı + belge sayısı + ⇅ ikonu) → menü: Özet, Sorular, Koleksiyonlar,
Belgeler. Seçili öğe `--accent-soft` zemin + `--accent` metin. Sorular'da açık soru sayısı amber rozet
(`--warn-soft` / `--warn`, radius 6). Altta geliştirici modu anahtarı ve tek satır slogan. 780 px altında
üst menüye döner: logo + şirket seçici bir satır, dört menü ikon+etiket olarak eşit sütun.

**Metrik kutusu.** Etiket (13 px, `--ink2`) → sayı (34 px, 500, tabular) → tek satır açıklama (12 px,
`--muted`). Sayı yalnızca durum anlatıyorsa renk alır: Çelişki > 0 amber, Kaynaksız bilgi = 0 yeşil.
Onaylı oranında 4 px yeşil ölçek çubuğu. Dört kutu tek satır; 780 px altında 2×2.

**İnceleme durumu hapları.** Yükseklik 22, radius tam, 11 px 600. Renk ve biçim birlikte:

| Durum | Biçim | Renk |
|---|---|---|
| Öneri | içi boş halka | `--paper` zemin, `--muted` metin, `--line` kenar |
| İnceleme bekliyor | dolu nokta | `--warn-soft` / `--warn` / `--warn-line` |
| Onaylandı | tik ikonu | `--ok-soft` / `--ok` / `--ok-line` |
| Reddedildi | çarpı ikonu | `--danger-soft` / `--danger` / `--danger-line` |

**Soru kartı.** Ürünün odak noktası.
1. Durum satırı: amber nokta + "Kaynaklar farklı söylüyor" + `· koleksiyon adı` (`--muted`).
2. Soru başlığı 23 px: "{kayıt} için {alan} hangisi?" ya da doğal soru ("Aile Odası'nın manzarası hangisi?").
   Altında tek cümle yönerge.
3. **Seçenekler belgeye göre gruplanır, değere göre değil.** Her grup bir belge: başlık satırı
   `[belge ikonu] dosya-adı diyor ki · tarih` (tarih mono). Altında değer (26 px, 500). Hairline ayraç,
   sonra o belgedeki **tüm** alıntılar (serif 16 px), her birinin altında konum (mono). Alıntıda değerin
   geçtiği kısım `<mark>`: `--mark` zemin + 2 px `--accent` alt çizgi. Grubun altında ikincil düğme
   "Bu belge güncel". Gruplar `repeat(auto-fit, minmax(230px, 1fr))`.
4. Alt satır: "Hepsi doğru" (ikincil düğme; **yalnızca** alan liste değer alabiliyorsa, `allow_all`),
   "İkisi de yanlış, düzelt" (3+ belgede "Hiçbiri doğru değil, düzelt"), "Sonra sor" (sessiz), sağda
   `3 / 7` sayacı.
5. Seçilen grup `--accent` kenar + `--accent-soft` zemin, düğmesi "Seçildi" olur; diğerleri %55 opaklık.
   Kayıttan sonra kartın altında yeşil bildirim satırı + "Geri al". "Sonra sor" bildirimi nötr (`--sheet`).
6. Bir sonraki soru `--dur-enter` (280 ms) ile sağdan 12 px kayarak girer; `prefers-reduced-motion` ile kapanır.

**Koleksiyon kartı.** İkon kutusu (36 px, hairline, ikon `--accent`) + sağda ok (`--faint`) → başlık 16 px →
tek satır açıklama → 4 px durum çubuğu (yeşil onaylı, amber soru bekleyen, kalan boş = öneri) → alt satır
"14 kayıt · 9 onaylı · 2 soru" (soru amber, soru yoksa gösterme). Tüm kart tek düğme; üzerine gelince
kenar `--accent`. Izgara 3 / 2 / 1 sütun.

**Boş durumlar.** Kart içinde tek ikon (36 px yuvarlak) + başlık 15 px + bir cümle + gerekiyorsa tek
düğme. İllüstrasyon yok. "Henüz yok" durumları kesik çizgili kenar (`--line-strong`) alır; "her şey tamam"
durumları düz kenar ve yeşil ikon zemini alır. Örnek: "Bütün sorular cevaplandı", "Henüz koleksiyon yok".

**Sayfa başlığı.** Küçük üst etiket ("Şirket özeti", 12 px `--muted`) → başlık 30 px 600 → tek satır
meta ("5 belgeden derlendi · son güncelleme 6 Ekim 2026, 14:20"). İçerik sola hizalı, en fazla 1200 px.

## 6. Yap / yapma

| Yap | Yapma |
|---|---|
| Tek vurgu rengi, durum renkleri yalnız durum için | Kategori başına renk, renkli ikon kutuları |
| Hairline kenar, bol boşluk, sola hizalı içerik | Kart gölgesi, her şeyi ortalamak |
| Belgeden gelen metni serif ve işaretli değerle göstermek | Alıntısız değer göstermek; kaynak her zaman yanında |
| Durumu renk + biçimle anlatmak (halka, nokta, tik, çarpı) | Yalnızca renkle durum anlatmak |
| Kullanıcının kelimeleri: Koleksiyonlar, kaynak, soru | "Bilgiler", "record", "candidate", "pipeline" |
| Koyu temayı token'larla tasarlamak | Sabit `#fff`, `#37352f`, `#102238` gibi renkler |
| Gerçekçi örnek içerik (uydurma otel adları) | Gerçek müşteri adları, lorem ipsum, emoji |
