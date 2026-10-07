# Büyük çalışma alanlarında kayıt eşleştirme (WP69)

Eşleştirme yalnızca aynı bilgi listesindeki farklı belgelerin kayıtlarını karşılaştırır.
İsimler TR/EN/DE/RU harf dönüşümü ve noktalama temizliğiyle karşılaştırılır; isim
kelimeleri, çeviri isimleri ve sayısal alanlar ucuz aday anahtarlarıdır. Ortak anahtarı
olmayan çiftler elenir. Çelişen sayısal/kategori alanları `different`, yeterli bağımsız
kanıtlar `same` olur. Yalnızca kalan belirsiz çiftler modele gönderilir. Belge içindeki
kimlik çakışmaları ve alan alternatifleri modelle çözümlenmez; inceleme bekler.

Model erişimi varsayılan olarak kapalıdır. `--auto-accept strong` mevcut görünür
kimlik onaylarını uygular: aynı isimdeki alan çelişkileri korunur; model cevabı tek
başına onay oluşturmaz. Sonuçtaki rekabet ve geçişli çelişki kontrolleri her çalışmada
yeniden uygulanır. `match_proposals.json` şeması değişmez.

## Lead için gerçek çalışma komutu

PowerShell'de mevcut ortam değişkenlerini kullanın; gizli anahtarı komuta yazmayın.
`$recordsDir` belge başına `records.json` dosyalarını içeren özel dizin,
`$matchOutDir` ise bu çalışma alanının eşleştirme çıktı dizinidir. Sonraki çalışmada
aynı dizinleri kullanın. İlgili çalışma alanı için onaylanmış şema gerekiyorsa
`--schema $schemaFile` ekleyin.

```powershell
$env:PYTHONPATH = 'packages/domain;packages/evaluation;packages/records'
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m docgrain_records match `
  --records $recordsDir --out $matchOutDir --auto-accept strong `
  --base-url $env:MODEL_BASE_URL --model $env:MODEL_NAME --api-key-env MODEL_API_KEY `
  --concurrency 4 --batch-size 8 --batch-chars 32000 --timeout 60 --retries 3 --max-minutes 15
```

`--max-minutes` dolunca yeni istek gönderilmez; gönderilmiş isteklerin tamamlanması
(zaman aşımı ve yeniden denemeler dahil) beklenir ve başarılı cevaplar kaydedilir.
Eksik çalışma çıkış kodu `2` döndürür; sonuç/özet dosyaları yazılmaz ve varsa önceki
sonuç dosyaları korunur. İlerleme stderr'e başlangıçta, yaklaşık 20 saniyede bir ve
istekler tamamlandığında yazılır. İstek sayısı HTTP denemelerini, yeniden denemeleri
ve uyumluluk için yapılandırılmış çıktı biçiminden vazgeçilen ek isteği de içerir;
bu sayı her çalışmada yeniden başlar.

`match_progress.jsonl` kararlar geldikçe diske yazılır. Yeniden başlatma, kaydedilmiş
çiftlerin puanlamasını ve model çağrılarını atlar. Dosyanın yarım kalmış son satırı
atılır; diğer bozuk satırlar hata verir. Girdi, şema, model/endpoint veya güçlü isim
politikası değişirse eski kararlar kullanılmaz. Toplu istek boyutu, eşzamanlılık ve
süre bütçesi değiştirilebilir. Çift tek başına karakter sınırını aşarsa açık hata
verilir; kaynak kesilmez. Aynı çıktı dizininde eşzamanlı iki eşleştirme çalıştırmayın.

## Tekrarlanabilir sentetik ölçüm

```powershell
$env:PYTHONPATH = 'packages/domain;packages/evaluation;packages/records'
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' benchmarks/fast_matching.py
```

8 belge × 100 kayıt: 90 kayıt grubu aynı isimde, 10 grup ortak ayırt edici kelimeli
farklı isimlerde. Tüm veriler sentetiktir; `httpx.MockTransport` sabit sahte cevap
verir ve ağ kullanılmaz. `single_pair`, önceki belirsiz çift başına tekli istek
akışını; `batched`, 8 çift/istek ve 4 eşzamanlı isteği ölçer.

| Ölçüm | Tekli akış | Toplu akış |
| --- | ---: | ---: |
| Girdi kayıtları | 800 | 800 |
| Eleme öncesi aynı liste/belgeler arası olası çiftler | 280.000 | 280.000 |
| Anahtarlarla eleme sonrası puanlanan çiftler | 2.800 | 2.800 |
| Modelsiz kararlaştırılan çiftler | 2.520 | 2.520 |
| Modele gönderilen belirsiz çiftler | 280 | 280 |
| Model istekleri (yeniden deneme yok) | 280 | 35 |

Anahtarlarla eleme ve deterministik kurallar önceki kodda zaten vardı; bu örnekte
WP69'un ek kazancı istek sayısında %87,5 azalmadır. Sonuç önerileri birebir aynıdır.
Sahte model süreleri gerçek sağlayıcı gecikmesini göstermez. Gerçek çalışma bu WP
kapsamında çalıştırılmadı; lead yukarıdaki komutla kendi özel verisi üzerinde ölçer.
