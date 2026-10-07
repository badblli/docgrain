# wp95-u1-smoke — Bağımsız sentetik anahtar ve canlı U1 kabul testi

- Özet: İki uydurma şirket belgesiyle yükleme, bilgi çıkarma, onay ve kaynaklı Dene yolunu adım adım ölç; eksik veya yanlış sonuç U1'i kapatmasın.
- Model: derin
- Engine: agy
- Phase: U1
- Branch: `codex/wp95-u1-smoke` (base: `origin/dev`)
- Depends on: wp91-u1-pipeline, wp92-u1-settings, wp93-u1-web-flow, wp94-u1-try (canlı kabul); fixture/test geliştirme paralel
- Role: implementer
- Owner: Bulbasaur (agy)

## Goal

`done` veya geçerli JSON'a bakmadan U1'in anlamını bağımsız anahtar ve gerçek yığın üzerinden ölç.
HTTP smoke web turunun yerine geçmez; ikisi ayrı raporlanır. U1 A11/A15/A16/A18–A20.

## Scope

- In: tamamen sentetik iki TXT, bağımsız anahtar, HTTP smoke/report ve offline test.
- Out: ürün/API/worker/web implementasyonu, customer/data okumak, model judge, browser framework
  kurmak, fixture yerine hazır publication koymak, CLI ile pipeline aşamalarını atlamak.

## File ownership

- `tests/fixtures/u1-company/odalar.txt`
- `tests/fixtures/u1-company/hizmetler.txt`
- `tests/fixtures/u1-company/golden.json`
- `tests/fixtures/u1-company/README.md`
- `tests/unit/test_u1_smoke.py`
- `tests/integration/test_u1_smoke.py`
- `docs/examples/u1_smoke.py`
- `docs/plan/U1-smoke.md`

wp90 U1.md/checklist, WP91–94 ürün dosyalarının sahibidir; değişiklik ihtiyacını lidere bildir.

## Tasks

1. Ürün çıktısına bakmadan [U1 sentetik anahtarını](../U1.md) yaz: Bahçe Odası ad/32 m²/2 kişi,
   Danışma ad/08:00–20:00; iki kaynakta 32/36 çelişkisi, ortak oda adı ve kapasite. Bağımsız goldende
   beş kritik alan, kaynak dosyası+konum+tam alıntı, ret değeri, iki soru ve bilinmeyen 2035 fiyatı.
   Kaynak talimatı görünümlü bir cümle ekle; eylem olarak takip edilmemesi ayrıca ölçülsün.
   Kaynak hash'lerini goldende sabitle; pipeline/model tahminiyle anahtar değiştirme.
2. Smoke default offline/help; live yazmaları ancak `--live --enable-model` ile. Model/key
   konfigürasyonu mevcut sunucu profilinden; argv/raporda key yok. Her live koşuda yeni sentetik
   workspace adını kullan; gerçek çalışma alanına dokunma, otomatik delete/reset yapma.
3. Sıra: health mode live → boş şirket oluştur/listede kontrol → model-off job/ask guard → iki
   dosya register/upload/confirm ve processing poll → aynı dosyaları tekrar yükle/dedup → diğer
   şirkette model kapalı kontrolü → model aç → record job başlat/poll → preview ve questions →
   goldene göre insan seçimlerini API'den simüle et → approved JSON/context/AI tools → ask iki soru.
   Ara CLI/discovery dosyası düzenleme/publish çağırma yok. Tam iş yolunu API üzerinden kullan.
4. Her aşamada değer/pin/kaynak/anlam kontrolü: beş alan 5/5, unsupported 0; 32/36 onay öncesi
   approved'da yok; 32 seçilince var/36 yok; old revision okunur; stale answer `409`; araç kaynakları
   aynı revision ve tam doğru locator/quote. Dene sayısal cevap 32/2 ve bu iddiaları destekleyen
   kaynak; “Bilmiyorum.”da fiyat/uydurma source yok. Genel kaynak ID isabeti yeterli değildir.
   Fazladan kayıt/alanı gizleme: kanıtını doğrula ve sayısını raporla. Eksik kritik alan fail.
5. Bounded poll/deadline; demo/eksik servis/ayar/model/timeout durumunda adım `blocked` veya `fail`,
   çıkış sıfır değil. Sonraki bağımlı adımlar `blocked`; başarılı/skipped sayılmaz. Rapor JSON +
   kısa Markdown: adım, durum, neden, duration, workspace/job/source/revision pinleri, model adı,
   anahtar hash'i ve test türü (fake / live-real-model). Ham model/source body veya sır/log yok.
6. Offline fake transport mevcut testlerden bağımsız beklenen yanıtlar üretir; matcher/test
   anlam kontrollerini yanlış değer/eksik evidence/sahte source/done-but-empty sonuçlarla sına.
   Live integration testi yalnız açık opt-in ile çalışır; testin skip'i “U1 passed” raporu üretmez.
7. `U1-smoke.md` exact komutları, rapor şemasını, fixture yeniden üretim doğrulamasını ve kapsam
   sınırını yaz. Lider [checklist](../U1-checklist.md) sentetik web turunu ve gerçek şirket kabulünü
   ayrı doldurur. Gerçek kaynak/anahtar/rapor yalnız Git dışında; bunu bu WP çalıştırmaz.

## Tests

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m pytest -q tests/unit/test_u1_smoke.py -p no:cacheprovider
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m ruff check docs/examples/u1_smoke.py tests/unit/test_u1_smoke.py tests/integration/test_u1_smoke.py
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' docs/examples/u1_smoke.py --help
```

Lider, bütün paketler birleşip Docker yığını hazırken (aşağıdaki **yeni** CLI bu WP'de oluşturulur):

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' docs/examples/u1_smoke.py --live --enable-model --api http://localhost:8000 --credential-id u1-test --base-url https://model.example/v1 --model configured-model --out .lead/u1-smoke
```

Endpoint/model/profil placeholders gerçek sunucu ayarına uyarlanır; key argv'ye konmaz.
Model off guard'ı live koşunun başında ölçülür. Varsayılan test/--help dış çağrı yapmaz.
Docling/EasyOCR/Postgres/MinIO tam entegrasyonları lider worker Docker test ortamında koşar;
bu smoke iki TXT ile bütün altı formatın source fidelity kapısını kapatmaz.

## Acceptance criteria

- [ ] İki nötr TXT ve ürün tahmininden bağımsız frozen golden/hash var; beş alan ve iki soru açık.
- [ ] Offline negative tests: yanlış 36 cevabı, eksik alan/kaynak, boş done, gizli çelişki ve atlanan
      adım genel başarı üretemez; kapalı model/live opt-in yokken transport istek sayısı 0.
- [ ] Live smoke sırası gerçek API/worker publication yoludur; tüm adımlar pass ve çıkış 0 ancak
      anlam/pin/kaynak kontrolleri geçince; demo/blocked/timeout sıfır olmayan çıkışla raporlanır.
- [ ] 5/5 kritik alan; unsupported 0; 32 kabul/36 ret; source-grounded 32/2 cevabı ve doğru bilinmeyen.
- [ ] Rapor adım süreleri/türü/pinleriyle tekrar üretilebilir; secrets/gerçek müşteri verisi yok.
- [ ] Liderin gerçek model live smoke + sentetik web turu ve gerçek şirket kabulü ayrı kanıtla
      raporlanır. Ajan çalıştıramadıysa “not verified”; U1 tamamlandı iddiası yok.

## Notes

AGENTS.md, ROADMAP, [U1](../U1.md), wp11/wp45/wp53/wp68,
`docs/plan/record-golden.md`, `docs/examples/ai-access.md` okunur.
Fixture ilk paralel dalgada; son merge **WP95**, sonra lider kabulü. Install/Git yazması yok.
