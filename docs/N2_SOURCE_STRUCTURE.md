# N2 — Kaynak yapısı ve hücre doğruluğu

2026-10-02 · `codex/n2-source-structure-fidelity`

## Uygulanan kapsam

| Kaynak | Uygulama | Doğrulanan örnek |
| --- | --- | --- |
| PDF | Native çizgi/hücre/kelime eşleştirmesi; hücre bbox; kaynak/parser farkı; rotasyon çerçevesi; exact-token sütun ayrımı | Genel yanlış sayı sütunu, birleşik başlık, 0/90/180/270°, crop, iki sütun |
| DOCX | Gerçek OOXML part/path; tekrar paragraf; body/header/footer; inline/floating drawing binary; birleşik hücre | Aynı metnin iki farklı yolu, metin+resim aynı paragraf, header resmi, horizontal/vertical merge, eksik part/field negatifleri |
| XLSX | Native değer/formül/cache/type/number format/merge; chart series/category/reference/cells | 7 ve 724, tarihi koruma, eksik formula cache, chart kaynak aralığı, external/missing/oversized reference negatifleri |

Yeni ingestion worker N2 profilini kullanır. Canonical **0.6.0**, AI çıktısı **1.2.0**. Hücrelerde eski parser metni/sınır kelimeleri ve sayı biçimi; grafiklerde native seri verisi UI/JSON'da görünür. Kaynak kanıtı hücre/range/part'a döner. İnceleme durumu unreviewed/partial kalabilir.

## Gerçek beş kaynağın karşılaştırması

Kaynak SHA/byte doğrulaması ardından ayrı yerel çıktılar üretildi (`data/reviews/n2-source-review/`). Mevcut API head'lerine veya paketlerine uygulanmadı; model çağrısı yok.

Dobedan sayfa-2 üst **19×12** tabloda önceki altı bağımsız kontrolün **6/6'sı** yeni parser çıktısında eşleşti: kaynakta olmayan İ eklenmedi; Yandan Deniz/Kara Manzaralı başlıkları, 724 toplamı ve 7 engelli odasının doğru sütunu. Genel geometry kuralı kullanıldı; belge ID'si kodda yer almıyor. Diğer tabloların bazı shape ve kırpılmış metin uyuşmazlıkları hâlâ açık. Tüm PDF tablolarının doğruluğu kabul edilmiş sayılmaz.

Gerçek DOCX/XLSX/TXT kaynakları da yeni profille ayrı çıktı üretti. Bu inceleme bütün belge anlamının kabulü değildir. Canonical source→meaning kabulü N5, eski live paketlerin yerini alacak review/CAS uygulaması N4'tür.

## Kontroller

Son Docker image üzerinde full worker/Docling/EasyOCR/PostgreSQL/MinIO turu **269 geçti / 0 atlandı**; ilk tur 265/0 idi. Host **195 geçti / 74 runtime/service atlandı**. Eski core 0.2–0.5 ve AI 1.0/1.1 schema bytes frozen testlerle korunur. Production web build TypeScript kontrolünü içerir; API/web/worker image build başarılı.

Tam test kanıtı `data/reviews/n2-final-tests.xml`; ilk tur `n2-tests.xml`. Kaynak raporu `n2-source-review/report.json`. Testler canlı kullanıcı tabloları/bucket'ları yerine ayrı disposable schema/bucket kullanır.

Yerel stack `data/reviews/n2-local.compose.yml` ile çalışır; OCR/N2 açık, worker Gemini key boş ve queue 0. Beş head değişmedi; 30 stored ve 30 yeniden üretilen output hash'i N1 öncesi baseline ile aynı (`n2-live-parity.json`). Browser gerçek yeni Dobedan parse'ının ayrı read-response fixture'ında doğru 7 sütununu ve eski parser değerini gösterdi (`n2-browser-table.png`); console 0 error. Bu fixture canlı revision değişikliği değildir; test sonunda normal beş-belgeli UI geri açıldı. Yeni provider/embedding çağrısı, push/PR/dev merge yok.

```sh
python -m pytest -q
ruff check --isolated --select E4,E7,E9,F apps packages tests benchmarks docs/examples
```

## Sınırlar ve sonraki adım

- Native tablo karşılaştırması basılı scan metnini veya Vision önerisini onaylamaz. OCR/mixed tablo overwrite edilmez.
- Word başlık/footer akışı fiziksel sayfa sırası değildir; field hesaplama ve genel drawing/layout eşdeğerliği yok.
- Excel formula cache yeniden hesaplanmaz; native chart data grafik görseli/trend yorumu değildir. External/unsupported veriler açık kalır.
- Büyük/held-out source corpus kabulü geçmedi. Test sayısı, şema-valid JSON veya native geometry semantik kabul değildir.

**Sıradaki N3:** mevcut görsel region'ların bilgi/dekorasyon türünü belirlemek, gerekli seçilmiş OCR/Vision önerilerini kaynak/hash/uncertainty ile bağlamak. Ardından N4 review + immutable apply, N5 kaynak kabulü ve en son embedding.
