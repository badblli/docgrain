# Yerel bilgi kalitesi ölçümü (WP53)

Bu komutlar kaydedilmiş çıkarım/birleşim çıktılarını okur; API, ağ veya model çağırmaz.
Gerçek şirket ölçümünü lider çalıştırır. Bu WP yalnız sentetik sayılar üretir; bağımsız
doğruluk anahtarları oluşturmaz, mevcut golden dosyalarını değiştirmez.

`docgrain-records` paketi bu üç komut için gerekir; temel değerlendirme paketinin
`records` extra'sında tanımlıdır. Repo venv'inde iki paket zaten kuruludur. Kaynak
worktree kodunu doğrudan çalıştırmak için PowerShell:

```powershell
$env:PYTHONPATH = 'packages/evaluation;packages/records;packages/domain'
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
```

## Kararlılık

```powershell
& $python -m docgrain_eval.cli stability --runs .lead/measure/company_1/run_a .lead/measure/company_1/run_b --out .lead/measure/company_1/stability
```

Kurulu CLI karşılığı: `docgrain-eval stability --runs <dirA> <dirB> --out <dir>`.
`stability.json` ve `stability.md` yazılır. Her girdi şunlardan biri olmalıdır:

- Tek `merge_revision.json` içeren klasör veya doğrudan bu dosya.
- `records.json`, `source.json`, `context.md` üçlülerini içeren çıkarım klasörü.

Bir klasörde birden çok birleşim varsa seçim belirsizdir ve komut hata verir.
Bir birleşim varsa çıkarım çıktılarıyla karıştırılmaz. Aynı türden iki çalışma,
aynı workspace, belge/sürüm/içerik sürümü/hash pinleri ve aynı kabul edilmiş şema
snapshot'ı zorunludur. Çıkarım klasörlerinde yerel bağlam hash'leri de eşleşmelidir.
Birleşimlerde doğrulama pinler üzerinden yapılır (`input_verification=pins_only`);
belgelerin gerçekten aynı pinlerden üretildiğinin güvencesi kayıt üretim hattına aittir.

Üretilen kayıt/aday kimlikleri ve sıralama kararlılık hesabına girmez. Alan değerleri
(liste sırası dahil), diller, birincil dil, kaynak kanıtları, çelişkiler ve onay durumları
girer. Kanıt alıntılarında yalnız NFKC/boşluk normalizasyonu uygulanır. Hesap kaynak
metnini değiştirmez. Kaynak/şema alanlarını sonuca bakarak değiştirmek yasaktır.

Kayıt eşleştirme anahtarı koleksiyon + bütün kimlik alanı değerleri/dilleri;
çıkarımlarda belge de anahtara girer. Kimlik alanı runtime ile aynıdır: `name`, yoksa
şemadaki ilk alan. Her anahtar grubunda payda iki çalışmadaki kayıt sayısının büyüğüdür.
Birebir aynı kayıtlar önce eşleştirilir; kalan yinelenen kayıtlar deterministik sırayla
eşleştirilir. Yinelenme çokluğu korunur. Alan paydası eşleştirilmiş her kayıt çiftinin
alan anahtarları birleşimidir; eksik/fazla alan ve kayıtlar paydada kalır. Kimliği
değişen bir kayıt iki ayrı anahtar olarak sayılır. Belirsiz yinelenme gruplarında alan
eşleştirmesi semantik kimlik kanıtı değildir; şirket raporunda yinelenmeler ayrıca görünür.
Boş payda `null` üretir. `extraction_failures` tamamlanmayan taramaları gösterir;
yüksek kararlılık tamlık veya doğruluk kanıtı değildir.

## Kaynak desteği ve kapsam

```powershell
& $python -m docgrain_eval.cli support --revision .lead/measure/company_1/run_a/merge/merge_revision.json --sources .lead/measure/company_1/run_a/sources --out .lead/measure/company_1/support.json
```

Kurulu CLI: `docgrain-eval support --revision <merge_revision.json> --sources <dir>`.
`--out` yoksa yalnız metin içermeyen JSON sonuç ekrana yazılır.

Payda **onaylı alan/dil değerleridir**: approved yayında birincil ve yerelleştirilmiş
olarak görünür değer aynı dilde bir kez sayılır. Öneriler, inceleme bekleyen ve reddedilen
adaylar paydada değildir. Birden fazla onaylı aday aynı dildeyse yayın sözleşmesi geçersizdir;
komut hata verir. Her onaylı adayın bütün kanıtları kontrol edilir. Bir hatalı atıf alanı
kanıtsız saydırır; birden fazla bozuk atıf alan sayısını çoğaltmaz. Belge, dosya sürümü,
içerik sürümü ve içerik hash'i kaynak pinleriyle eşleşmeli; locator bulunmalı; alıntı
o blokta NFKC/boşluk normalizasyonu sonrası gerçekten bulunmalıdır. Kaynak anahtarları
footer'ı kanıt değildir. Eksik kaynaklar kanıtsız sayılır. Boş yayın `null` oran ve
`target_met=false` verir. Komut başarılı çalışsa bile `target_met` başarısız olabilir;
komut çıkış kodu girdi/çalıştırma hatasını belirtir.

Kaynak dizini çıkarım hattının **gerçek** `source.json` + `context.md` çiftlerini
saklamalıdır; alıntılardan kaynak metni yeniden kurmak yasaktır. `content_sha256`
yüklenen dosyanın hash'idir, `context.md` hash'i değildir. Bu araç gerçek dosyayı yeniden
okumaz ve bağımsız bağlam checksum receipt'i olmayan eski çıktılarda bağlam bütünlüğünü
kriptografik olarak doğrulamaz. Bu ölçüm alıntı varlığını kanıtlar; alan değerinin o
alıntıdan doğru yorumlandığını bağımsız alan anahtarıyla ölçmek gerekir.

`coverage` tahminlere bakılmadan kompakt Markdown içindeki tablo veri satırları ve liste
maddelerini sayar; başlık, tablo ayırıcıları ve footer dışarıda kalır. Satırdaki kimlik
hücresinin/liste metninin aynı bloktaki doğrulanmış alıntıda görünmesi gerekir. Tablo
kimliği ilk dolu hücredir. Tekrarlanan kimlikler ve yalnız sayılardan oluşan kimlikler
`ambiguous_rows` olarak paydada kalır, kapsandı sayılmaz. Bu temkinli yapısal ölçüm
doğruluk veya kaynaktaki her semantik kaydın eksiksizliği değildir; düzyazı/kartlar ve
Markdown dışı yapılar kapsamına girmez. Eksik/uyumsuz kaynak varsa genel kapsam oranı
`null` olur, gözlenen satır sayıları korunur. Kapsam bütün görünür, reddedilmemiş
adayları kapsar; yalnız onaylı yayının kapsamı değildir.

## Şirket karşılaştırması

```powershell
& $python -m docgrain_eval.cli companies --workspaces .lead/measure/company_1/run_a .lead/measure/company_2/run_a .lead/measure/company_3/run_a .lead/measure/company_4/run_a --bundles .lead/bundles --out .lead/measure/companies.md
```

Kurulu CLI: `docgrain-eval companies --workspaces <dir>... --out <report.md>`.
Yanında aynı adlı JSON rapor da oluşur. Çalışma alanları ayrı olmalıdır. Kaynak çiftleri
seçilen klasörün altında ise kapsam ve (birleşimler için) kaynak desteği de hesaplanır;
yoksa bu ölçümler açıkça ölçülmedi gösterilir. `--bundles` isteğe bağlıdır; belirtilen
dosyalar veya klasörlerdeki doğrudan JSON yükleme raporları workspace ile eşleştirilir.
Dosya durumları/sorun sayıları ve çıkarıma girmeyen belgeler görünür; `done` semantik
doğruluk kanıtı olarak kullanılmaz. Bir çalışma alanı için bir yükleme raporu seçin;
birden çok rapor verilirse dosya satırları birlikte sayılır.

Kabul edilmiş şemadaki boş koleksiyonlar da listelenir. Çelişki sayısı aynı alan/dildeki
farklı, reddedilmemiş değer gruplarıdır; çeviriler birbiriyle çelişki sayılmaz. Her şirket
içindeki olası yinelenmeler koleksiyon ve normalleştirilmiş kimlik alanı üzerinden
bulunur. Aksan/kasa farkları, `room`/`oda` gibi genel kelimeler ve `suit`/`suite`
varyantları normalleştirilir; otomatik birleştirme yapılmaz. Bu sezgisel inceleme önerisi
farklı kayıtları aynı grupta toplayabilir ve bütün dillerdeki eş adları bulma garantisi
vermez. Farklı şirketlerde aynı adın bulunması yinelenme değildir.

Raporlar kaynak alıntısı, şirket adı, kayıt adı veya dosya yolu içermez; şirketler sıra
numarasıyla, ayrıntı referansları hash ile gösterilir. Gerçek raporları `.lead/` altında
tutun. Doğruluk `not_measured` kalır: bağımsız anahtarları lider hazırlayıp ölçer.
Prime Beach için mevcut wp45 scorer kullanılabilir; diğer şirketlerin doğruluk anahtarları
bu WP'nin dışında. Hiçbir golden tahminler görüldükten sonra düzenlenmedi.

## Sentetik tekrar

```powershell
& $python docs/examples/stability_synthetic.py --out .lead/wp53-synthetic
& $python -m pytest -q tests/unit/test_consistency.py --basetemp=.lead/pytest-wp53
```

Örnek dört farklı kabul edilmiş şemadan yerel doğrulanmış çıkarım ve birleşim üretir,
sentetik onayları uygular ve üç komutu çalıştırır. Her şirket iki kayıt, dört onaylı
alan/dil ve iki tablo satırı içerir. Model çıktısı sentetiktir; model tekrarlanabilirliği
ölçüldüğü iddia edilmez. [Kaydedilmiş sentetik rapor](../examples/stability-synthetic-report.md).
Testler ayrıca değişen alan, dil/kanıt/onay/çelişki, eksiklik, yinelenme, yanlış pin,
footer/yanlış blok alıntısı, boş payda ve ağ çağrısı olmamasını denetler.
