# Çevrimdışı belge okuma — WP104

Worker derlemesi `/opt/docling-models` içine yalnızca Docling 2.130'un CPU
profillerinin kullandığı Heron, TableFormer accurate ve resim sınıflandırıcısı
dosyalarını indirir. Tam commit kimlikleri ve dosya listeleri
`apps/worker/docgrain_worker/docling_models.py` içindedir. Model kartları ve varsa
lisans dosyaları da korunur. EasyOCR'ın mevcut CRAFT/Latin kontrol noktaları ayrı
olarak imaja alınmaya devam eder.

Kaynaklar: [Docling 2.130 model önayarları](https://github.com/docling-project/docling/blob/v2.130.0/docling/datamodel/stage_model_specs.py),
[TableFormer yükleyicisi](https://github.com/docling-project/docling/blob/v2.130.0/docling/models/stages/table_structure/table_structure_model.py),
[Heron revizyonu](https://huggingface.co/docling-project/docling-layout-heron/commit/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8),
[TableFormer v2.3.0 revizyonu](https://huggingface.co/docling-project/docling-models/commit/fc0f2d45e2218ea24bce5045f58a389aed16dc23),
[resim sınıflandırıcısı revizyonu](https://huggingface.co/docling-project/DocumentFigureClassifier-v2.5/commit/f859dfbff5c9916cd996942d4b0db7fa25808220).

İmaj ve Compose varsayılanları `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
PDF/PNG/JPEG dönüştürücüleri açıkça yerel `artifacts_path` kullanır. Worker,
kuyruğa bağlanmadan bütün model dosyalarının mevcut ve boş olmadığını kontrol
eder; eksikte dosya adlarıyla hata kaydeder ve durur. Dönüştürücü de gerekli
dosyaları başlatılmadan kontrol eder. İndirme yalnızca açık `--download`
komutuyla derleme sırasında yapılır; eksik dosya için imaj yeniden derlenmelidir.
Bu kontrol dosya varlığını sınar, model doğruluğunu veya bozulmadığını kanıtlamaz.

`DOCGRAIN_DOCLING_MODEL_DIR` dizini değiştirilebilir; aynı depo-alt-dizin yapısı
korunmalıdır. İşleme kimliği dizin konumundan bağımsızdır ve kullanılan model
revizyonlarını içerir. Açıkça seçilen E profili uzak modele erişmeye devam eder;
HF çevrimdışı ayarları bu kullanıcı tarafından seçilmiş API çağrılarını engellemez.

## Lead doğrulaması

Aşağıdaki Bash komutlarını depo kökünde çalıştırın. Önceki imajı yeniden
etiketlemek yerine kendi mevcut worker imajınızın etiketini boyut sorgusunda
kullanın. Her iki boyut da Docker'ın sıkıştırılmamış `.Size` değeridir.

```sh
docker image inspect docgrain-worker --format '{{.Size}}'
docker build -f apps/worker/Dockerfile -t docgrain-worker:wp104 .
docker image inspect docgrain-worker:wp104 --format '{{.Size}}'
mkdir -p .pytest_cache/wp104
docker run --rm --network none -v "$PWD:/checkout:ro" -w /checkout \
  docgrain-worker:wp104 python -m pytest -q tests/integration/test_docling_profile_conversions.py
```

Sentetik belge kümesi üretip aynı imajla iki ağ koşulunda ölçün (gerçek kaynak
belgesi kullanmaz; bütün çıktılar Git dışında `.pytest_cache` altında kalır):

```sh
docker run --rm --network none -v "$PWD:/checkout:ro" \
  -v "$PWD/.pytest_cache/wp104:/results" -w /checkout docgrain-worker:wp104 \
  python -c 'from pathlib import Path; from tests.fixtures.structural.docling_profiles import create_profile_corpus; create_profile_corpus(Path("/results/corpus"))'
docker run --rm --network bridge -v "$PWD:/checkout:ro" \
  -v "$PWD/.pytest_cache/wp104:/results" -w /checkout docgrain-worker:wp104 \
  python benchmarks/docling_profiles.py --profiles C_tesseract --root /results/corpus --out /results/online
docker run --rm --network none -v "$PWD:/checkout:ro" \
  -v "$PWD/.pytest_cache/wp104:/results" -w /checkout docgrain-worker:wp104 \
  python benchmarks/docling_profiles.py --profiles C_tesseract --root /results/corpus --out /results/offline
docker run --rm --network none -v "$PWD/.pytest_cache/wp104:/results:ro" \
  docgrain-worker:wp104 python -c '
import json
from pathlib import Path
def rows(mode):
    result = json.loads(Path(f"/results/{mode}/profiles.json").read_text())["rows"]
    assert len(result) == 6 and all(r["status"] != "failed" for r in result)
    return [{k: v for k, v in r.items() if k not in {"seconds", "seconds_per_page", "peak_rss_bytes"}} for r in result]
assert rows("online") == rows("offline")
print("Ağlı/ağsız sonuçlar eşit")'
```

Süre ve bellek ölçümleri karşılaştırma dışında; metin oranı, tablolar, görseller,
sayfalar, kaynak kutuları, güven raporu ve işleme kimliği eşit olmalıdır. Yalnız
başarılı çıkış kodu anlam doğruluğunu kanıtlamaz; entegrasyon testleri sentetik
belgelerde beklenen metin ve tablo içeriğini ayrıca doğrular.

## Bu çalışma ortamındaki ölçüm

Docker istemcisi mevcut, ancak `docker version` worker Docker API'sine bağlanırken
`permission denied` döndü. Bu nedenle önceki/sonraki imaj boyutu **ölçülemedi**;
imaj derlemesi, Docling/EasyOCR dönüşümleri ve ağlı/ağsız sonuç karşılaştırması
lead ortamında doğrulanmalıdır. Sayısal boyut tahmini kabul kanıtı sayılmadı.
