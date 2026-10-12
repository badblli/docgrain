# Şirket bilgilerini yapı bağlamıyla yeniden çıkarma

WP114, kayıtların başlık yolunu, bölümünü ve varsa tablo satır/sütun başlıklarını
özgün belge içeriğinden türetir. Aynı ad farklı kat/daire/bölüm altında ise ayrı
kayıt olur. Aynı bağlamdaki tekrarların kanıtları birleşir. Bağlamı olmayan bir
kayıt iki farklı bağlamı birbirine bağlayamaz. Gerçek alan çelişkileri sorulur;
tahmin edilmez.

Belgeler arası eşleşmede başlık metinleri doğrudan karşılaştırılamaz (broşürde
"Odalar", fiyat listesinde "2026 Fiyatları"). Bu yüzden iki belgedeki kayıtlar
yalnız şu durumda yapı çelişkisi sayılır: bir kaydın başlığı/satır başlığı öteki
belgede de var, ama öteki kayıt o başlığın altında değil (iki kat planında da
"Alt Kat" ve "Çatı Katı" var; Alt Kat'taki Hol, Çatı Katı'ndaki Hol ile
birleşmez). Ortak başlık sözlüğü yoksa yapı belgeler arası birleşmeyi engellemez.

Yapı satırları (`§N structure=…`) kaynak anahtarları bölümüne yalnız doğrulayıcı
için eklenir; model istemine ve bölümleme boyutuna girmez. Model, kaydın
bulunduğu blokları kapsayan başlıkları ayrıca `untrusted_containing_headings`
olarak görür.

Kimlik notu: yapı bağlamı olan kayıtların belge içi kimliği (`source_identity`)
artık bağlamı da içerir. Başlıklı belgelerde WP114 sonrası ilk yeniden çıkarımda
kayıt kimlikleri (`rec_…`) değişebilir; bağlamsız kayıtlarınki değişmez.

Kategori/tür/kat/bölüm alıntısı, kaydın kendi kimlik kanıtını kapsayan başlığın
tam başlığı ya da ayraçlı bir dil parçası ("Çorba / Soup" içinde "Soup") ise
başlığın locator'ıyla kabul edilir. Tarama parçası başlığı
içermese bile özgün belgenin başlık yolu kullanılır. Diğer çıplak değerler
WP102 kurallarına tabidir. Modelin verdiği yapı bilgisi kullanılmaz.

## Kalite raporu

Rapor yalnız okur; model çağırmaz, yayın değiştirmez. JSON ayrıntıları ve Türkçe
Markdown üretir. Şüpheler karar değildir. Alan ve dil başına gerçek/yalnız yazım
çelişkilerini ayırır; reddedilmiş yazım varyantlarını da yazım farkı olarak
gösterir. Elenen alan gerekçeleri işin `records.json` dosyalarından gelir.
Desteksiz alanlar, etkin adayların sabit kaynak sürümünü, gerçek kaynak
alıntısını ve alıntıda değerin bulunmasını yeniden denetleyerek sayılır.
Kaynak bağlamı eksikse sonuç sıfır kabul edilmez. Çıkış kodu: 0 başarılı ve
desteksiz alan yok, 1 desteksiz alan var, 2 girdi/okuma hatası.

Fazla birleştirme: aynı kaydın çelişen adayları aynı belgenin farklı yapı
bağlamlarından geliyorsa `different_structure` olarak listelenir. Eski
çıkarımlarda yapı bilgisi olmasa bile özgün `context.md` başlıklarıyla denetlenir.
Başlık yoksa (ör. çizim üstü "ALT KAT" etiketleri düz metin) ama aynı belge farklı
bloklarda farklı değer veriyorsa daha zayıf `same_document_different_blocks`
şüphesi yazılır.

Eksik birleştirme: aynı listedeki adların mevcut birincil ve dil alternatifleri
TR/EN/DE/RU yazım normalizasyonuyla karşılaştırılır (Türkçe harfler, Almanca
aksan/ß ve Kiril transliterasyonu). Karakter benzerliği en az 0,88 veya farklı
dillerdeki adlara eşlik eden en az iki aynı sayısal alan şüphe oluşturur.
Farklı yapı bağlamları beklenen ayrı kayıtlardır; ancak adı birebir aynı, değerleri
hiç çelişmeyen (yalnız tamamlayıcı) iki kayıt `same_name_different_structure`
olarak listelenir (ör. aynı oda "Odalar" ve "Fiyatlar" bölümlerinde: WP114 bunları
belge içinde ayırır). `shared_translated_name`
mevcut dil alternatiflerindeki örtüşmedir; `possible_translated_name` yalnız
sayısal benzerlik işaretidir. Sözlük/model olmadan “Bahçe / Garden” gibi saf
çevirilerin anlamı kanıtlanamaz; bu rapor otomatik eşleştirme yapmaz.

Raporlar kaynak başlıklarını içerebilir: özel çıktı klasöründe saklayın,
Git'e eklemeyin. Konsola kaynak adları, alıntılar veya anahtarlar yazılmaz.

## Lead: canlı önce/sonra komutları

Depo kökünden, her şirketin kendi çalışma alanı kimliğiyle çalıştırın. Aşağıdaki
POSIX komutlarda `WORKSPACE` gerçek kimlikle değiştirilir. Mevcut yayının işi
ve özgün kaynak bağlamları otomatik bulunur. `republish` çıkarım yapmaz; eski
belge içi birleşmeleri ayıramaz. Bu nedenle **Bilgileri çıkar** yeniden
çalıştırılmalıdır.

```sh
WORKSPACE=workspace_example
docker compose cp benchmarks/consolidation_report.py worker:/tmp/consolidation_report.py
docker compose exec -T worker python /tmp/consolidation_report.py \
  --workspace "$WORKSPACE" --out /tmp/wp114/before
docker compose cp worker:/tmp/wp114/before.json /tmp/wp114-before.json
docker compose cp worker:/tmp/wp114/before.md /tmp/wp114-before.md

# Lead'in incelediği WP114 kodunu çalışan API ve worker'a yükle.
docker compose build api worker
docker compose up -d api worker
docker compose cp benchmarks/consolidation_report.py worker:/tmp/consolidation_report.py

# Model seçimi/açık izin çalışma alanında önceden yapılmış olmalıdır.
# Yeni request_id gerekir; eski kimlik aynı işi döndürür.
REQUEST_ID="wp114_$(date +%s)"
curl --fail-with-body -sS -X POST \
  "http://localhost:8000/v1/workspaces/$WORKSPACE/record-jobs" \
  -H 'Content-Type: application/json' \
  -d "{\"request_id\":\"$REQUEST_ID\"}"

# POST'un döndürdüğü job_id için sorgula; done ve yeni revision_id bekle.
JOB_ID=records_example
curl --fail-with-body -sS \
  "http://localhost:8000/v1/workspaces/$WORKSPACE/record-jobs/$JOB_ID"

docker compose exec -T worker python /tmp/consolidation_report.py \
  --workspace "$WORKSPACE" --out /tmp/wp114/after
docker compose cp worker:/tmp/wp114/after.json /tmp/wp114-after.json
docker compose cp worker:/tmp/wp114/after.md /tmp/wp114-after.md
```

Arayüzde aynı işlem: çalışma alanını seç → **Bilgileri çıkar** → yeni işin
bitmesini bekle. İnsan tarafından onaylanmış değerler varsa mevcut yayın
koruması yeni işi reddeder (409); onaylar silinmez. Bu durumda lead mevcut
kararları koruyan yeniden çıkarım yolunu planlamalıdır; koruma atlanmaz.
Kuralla otomatik onaylanan değerler yeni işi engellemez (WP111).

Önce/sonra karşılaştırırken yayın kimliğinin değiştiğini, listelere göre kayıt
sayısını, fazla/eksik birleşme şüphelerini, gerçek/yazım çelişkilerini,
`bare_value_quote` dahil ret gerekçelerini ve **desteksiz alan = 0** sonucunu
birlikte inceleyin. İşin `done` olması tek başına doğruluk kanıtı değildir.

Çevrimdışı sabit bir yayın ve fake iş dosyaları için:

```sh
python benchmarks/consolidation_report.py --workspace workspace_example \
  --revision /tmp/private/merge_revision.json \
  --records /tmp/private/records --out /tmp/private/consolidation
```

Sentetik kat planı ve menü testleri gerçek `CanonicalMapper` snapshot'larını
kullanır. Fake rapor testi CLI'yi çalıştırıp JSON/Markdown çıktılarını ve
fazla/eksik birleşme şüphelerini denetler. Windows'ta pinli yorumlayıcı:

```powershell
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q tests/unit/test_structure_context.py --basetemp=.pytest_cache/wp114-structure
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q --basetemp=.pytest_cache/wp114-full
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m ruff check apps packages tests benchmarks docs/examples
```

Docling/EasyOCR/PostgreSQL/MinIO canlı entegrasyonları worker Docker ortamında
lead tarafından ayrıca çalıştırılır. Bu WP'nin sentetik testleri ağ/model
kullanmaz; gerçek şirket önce/sonra sonuçları bu komutlar çalıştırılana kadar
doğrulanmış değildir.

## Docling yapısına bağımlılık

Başlık yolu Docling'in kendi verisinden gelir: `SectionHeaderItem.level`
(Docling JSON `level`) → `structural.py` → `CanonicalMapper` bölüm ağacı
(`SectionNode.level`/`children`) → `pin_structure` (kaynak anahtarları
altındaki `§N structure=` satırları). Docling PDF gövdesi düzdür; HybridChunker
gibi hiyerarşi seviyelerden kurulur. Tablo satır/sütun başlıkları şimdilik
kompakt projeksiyondaki tablo başlık satırından ve ilk hücreden okunur.

Bilinen sınırlar (lead kararı; WP114 kapsamı dışında, ayrıştırıcı profili ve
yeniden ayrıştırma gerektirir):

- Docling 2.130 PDF başlıklarını `HeadingHierarchyOptions` açılmadıkça hep
  `level=1` verir (`PdfPipelineOptions(heading_hierarchy_options=
  HeadingHierarchyOptions(enabled=True))`; font sinyali için
  `generate_parsed_pages=True`). Bugün `docling_profiles.py` bunu açmıyor; oda
  veya yemek adı da başlık olarak algılanırsa kat/kategori başlığının altına
  yerleşemez ve başlık kanıtı uygulanamaz.
- Docling `TableCell.column_header`/`row_header`/`row_section` bayrakları
  `_docling_cells` içinde düşürülüyor. Kanonik `TableCell.source_attributes`
  (şema 0.6.0) ile taşınabilir; WP117 (yapı birimleri) ile birlikte ele alınmalı.
