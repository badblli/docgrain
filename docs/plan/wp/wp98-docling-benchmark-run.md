# WP98 — ölçümü çalıştırma ve doğrulama

Varsayılan `DocumentParser` profili `A_current` olarak kalır. Worker'ın mevcut
`ocr_enabled` ve `native_fidelity` bayraklarını korur. Ölçüm betiği A'yı bugünkü
worker varsayılanları olan OCR açık / yerel içerik koruma açık ile çalıştırır.
B–E yerel PDF tablo/okuma sırası, eksik tablo, DOCX yerel içerik ve XLSX eksik hücre
tamamlama geçişlerini kapatır. Kaynak bağlantıları, XLSX hücre değerleri/formülleri
ve mevcut tarih/sayı eşlemesi korunur; hiçbir modül silinmez.

## Lead için komutlar

Lead worker imajını oluşturduktan sonra **worker konteynerinin içinde**, depo
`/srv` altında ve özel kaynak/çıktı dizinleri bağlıyken:

```sh
cd /srv
python benchmarks/docling_profiles.py --profiles A_current,B_docling --root /srv/data/sources --out /srv/data/benchmarks/wp98-ab
python benchmarks/docling_profiles.py --profiles A_current,B_docling,C_tesseract,D_fullpage --root /srv/data/sources --out /srv/data/benchmarks/wp98-abcd
```

Konteyner varsayılan olarak betik ve testleri içermiyorsa depoyu salt okunur bağlayın;
özel çıktıyı ayrıca yazılabilir bağlayın. Örneğin depo kökünde, Linux kabuğunda:

```sh
docker compose run --rm --no-deps -v "$PWD:/srv/repo:ro" -v "$PWD/data:/srv/data:rw" worker python /srv/repo/benchmarks/docling_profiles.py --profiles A_current,B_docling --root /srv/data/sources --out /srv/data/benchmarks/wp98-ab
```

Geometri etkisini ayrı ölçmek için aynı profilleri yeni bir çıktı dizininde çalıştırın:

```sh
python benchmarks/docling_profiles.py --profiles A_current,B_docling --bbox-tolerance 0.5 --root /srv/data/sources --out /srv/data/benchmarks/wp98-ab-clip
```

E yalnız açık profil seçimi ve dolu anahtar ortam değişkeniyle çalışır. Anahtar değeri
argümanlara veya işlem tanımına yazılmaz. Endpoint ve model çalışma alanının seçimi
olmalıdır; base URL API köküdür, gerekli olduğunda `/v1` içerir:

```sh
python benchmarks/docling_profiles.py --profiles E_vlm --base-url "$WORKSPACE_MODEL_BASE_URL" --model "$WORKSPACE_MODEL_NAME" --key-env WORKSPACE_MODEL_KEY --root /srv/data/sources --out /srv/data/benchmarks/wp98-e
```

Bu çalışmada E veya gerçek belgeler üzerinde model çağrısı yapılmadı. Yeni anahtar
oluşturulmadı ve mevcut anahtarlar okunmadı; WP'nin istediği ortam değişkeni adı
üzerinden bağlantı yapılandırması uygulandı.

## Ölçümlerin anlamı

- JSON ve Markdown dosyaları özel çıktıdır. Dosya adları bu iki dosyada bulunur;
  dönüşümün kaynak adı/metni içerebilen tanılama çıktıları konsola aktarılmaz.
- Sözcük oranı Unicode-normalize edilmiş sözcüklerin **tekrar sayısını** karşılaştırır.
  PDF metin katmanı, DOCX paragraf içindeki bitişik XML metin parçaları, XLSX önbellek
  hücre değerleri ve TXT metni referanstır. Taramada veya görselde metin katmanı yoksa
  oran `null` olur; OCR metni kendi doğruluk anahtarı olarak kullanılmaz.
- Kutu oranı PDF/görsel öğeleri ve hücrelerinin geometrili kaynak bağlantılarını
  kapsar. DOCX/XLSX/TXT için geometrik oran uygulanamaz. `bbox_unresolved` canonical
  eşleyicinin aynı adlı sorunlarının sayısıdır; kutu oranının paydası ayrı kaydedilir.
- Docling'in ham per-page OCR/layout/parse/table puanları, mean/low puan ve notları
  canonical JSON metadata'sında saklanır. NaN/sonsuz puanlar `null` olur. `poor` ve
  `fair` düşük not sayılır; parser zor sayfa kodları ayrı gösterilir. Notlar kullanıcı
  onayı veya gerçek doğruluk kanıtı sayılmaz.
- A'nın eski converter kurulumu bağımsız olarak dondurulmuş entegrasyon testiyle
  Markdown/Docling JSON baytlarına karşılaştırılır. Profil kimliği ve güven raporu
  yeni metadata olduğu için **canonical dosyanın tamamı** eski sürümle bayt eşit
  olamaz; içerik yolu, kaynak bağlantıları ve eski converter çıktısı korunur.
- D/E tam sayfa OCR modunu PDF ve görsel pipeline'ında açar; metin katmanlı PDF
  sayfaları da aynı moddan geçer. Yerel içerik ile OCR birleştirmesi Docling'e aittir.
- E'nin zor sayfa VLM sonuçları onaysız, sayfa kaynaklı öneriler olarak ayrı tutulur;
  yerel metnin yerine yazılmaz. JSON'daki `word_recall_with_vlm_proposals` ayrıca
  öneri metnini ölçer. Picture description Docling JSON'unda kalır.
- Süre dönüştürme/OCR/model yükleme süresidir. PDF dışındaki biçimler için bir sayfa
  varsayılır; PDF/görselde Docling sayfa sayısı kullanılır. RSS 10 ms aralıkla ölçülen
  mutlak süreç belleğidir; daha önce yüklenen modellerin önbellekleri dahil olur.
- VLM çağrısı seçilmiş chat completions endpoint'ine yapılan mantıksal HTTP isteği
  sayısıdır; HTTP kitaplığının kendi yeniden denemeleri bu sayıya dahil değildir.
- Başarısız dosyalar raporda `failed` ve yalnız hata türüyle görünür; dönüşüm hataları
  veya boş kaynak kökü çıkış kodunu 1 yapar. Kaynak veya anahtar içerebilen hata
  mesajları rapora konulmaz.

## Seçeneklerin doğrulanma durumu

Host venv'de Docling yok; Docker named pipe erişimi ve PyPI bağlantısı sandbox
tarafından engellendi. Bu nedenle **kurulu 2.130 paketinde denetim yapılamadı**.
Kullanılan seçenek adları upstream'in sabit `v2.130.0` kaynaklarıyla karşılaştırıldı:

- [pipeline_options.py](https://github.com/docling-project/docling/blob/v2.130.0/docling/datamodel/pipeline_options.py):
  `PdfPipelineOptions`, `EasyOcrOptions.confidence_threshold`, `OcrMode.FULL_PAGE`,
  `PDF_AWARE_LAYOUT_REGIONS`, `TableStructureOptions`, `TableFormerMode.ACCURATE`,
  `do_cell_matching`, `TesseractCliOcrOptions`, picture classification/description,
  `PictureDescriptionApiOptions`, `VlmPipelineOptions`, `enable_remote_services`.
- [pipeline_options_vlm_model.py](https://github.com/docling-project/docling/blob/v2.130.0/docling/datamodel/pipeline_options_vlm_model.py):
  `ApiVlmOptions` ve `ResponseFormat.MARKDOWN`.
- [base_models.py](https://github.com/docling-project/docling/blob/v2.130.0/docling/datamodel/base_models.py):
  `ConfidenceReport`, `PageConfidenceScores`, `mean_grade`, `low_grade`.
- [document_converter.py](https://github.com/docling-project/docling/blob/v2.130.0/docling/document_converter.py):
  `convert(..., page_range=(n,n))`.

Upstream kaynakta bulunamayan kullanılan seçenek: **yok**. Kurulu pakette ve gerçek
model dönüşümüyle henüz doğrulanmayan: yukarıdaki yeni seçeneklerin tümü, classification
model önbelleği, `ConversionResult.confidence` aktarımı, VLM Markdown yanıtının dönüşümü.
`verify_installed_options()` çalışma anında sürümü denetler ve seçenekleri kurulu
paketin kaynaklarında arar; eksik ad varsa dönüşüm başlamaz. Model/testler ağsızdır;
layout/TableFormer/classification/EasyOCR ağırlıkları test başlamadan worker model
önbelleğinde bulunmalıdır. Eksik modelleri test sırasında indirmeyin.

## Süre tahmini ve ağsız sentetik koşu

Gerçek çalışma süresi ölçülmedi. CPU'da planlama için A–D profil başına PDF sayfasında
yaklaşık 5–30 sn, taramada 30–120 sn öngörülebilir; bunlar ölçülmüş sonuç değil kaba
tahmindir. 100 metin sayfasının dört profil toplamı yaklaşık 0,6–3,3 saat + ilk model
yüklemeleri; tarama ve görseller süreyi artırır. E ayrıca her seçilen sayfa/görsel için
endpoint gecikmesi ve olası yeniden denemeler ekler. Önce küçük bir özel alt klasör
çalıştırıp `seconds_per_page` sonuçlarıyla bütçeyi hesaplayın.

Worker konteynerinde, depo kökünde, önceden hazır model önbelleğiyle:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest -q tests/integration/test_docling_profile_conversions.py
python -c "from pathlib import Path; from tests.fixtures.structural.docling_profiles import create_profile_corpus; create_profile_corpus(Path('/srv/data/benchmarks/wp98-synthetic'))"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python benchmarks/docling_profiles.py --profiles A_current,B_docling --root /srv/data/benchmarks/wp98-synthetic --out /srv/data/benchmarks/wp98-synthetic-output
```

Host doğrulamalarının kesin sonuçları son WP raporundadır; atlanan entegrasyon testleri
başarı olarak sayılmaz.
