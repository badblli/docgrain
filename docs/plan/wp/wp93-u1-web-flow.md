# wp93-u1-web-flow — Çoklu yükleme, bilgi işi ve ekranları bağlama

- Özet: Kullanıcı birkaç belgeyi birlikte yüklesin, Bilgileri çıkar ile ilerlemeyi izlesin ve onay verdiğinde Koleksiyonlar ile Dene aynı güncel bilgiyi kullansın.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: U1
- Branch: `codex/wp93-u1-web-flow` (base: `origin/dev`)
- Depends on: wp91-u1-pipeline, wp92-u1-settings, wp94-u1-try sözleşmeleri; paralel geliştirilebilir
- Role: implementer
- Owner: Duru (codex)

## Goal

Mevcut ekranlar tek kullanıcı yolunda çalışsın; ara script ve elle sayfa yenileme gerektirmesin.
U1 A1–A4/A7/A12–A14 ve 390 px kabul turunun ekran bağlantıları.

## Scope

- In: ortak web bağlama noktaları, çoklu yükleme, gerçek iş ilerlemesi ve inceleme yenilemesi.
- Out: API/worker, model ayarı/Dene iç bileşeni, yeni tasarım sistemi, .css, dependency/install.

## File ownership

- `apps/web/app/page.tsx`
- `apps/web/app/components/console-types.ts`
- `apps/web/app/components/sidebar.tsx`
- `apps/web/app/components/documents.tsx`
- `apps/web/app/components/record-job-progress.tsx`
- `apps/web/app/components/workspace-review.ts`
- `apps/web/app/components/questions.tsx`
- `apps/web/app/components/question-card.tsx`
- `apps/web/app/components/information/information.tsx`
- `apps/web/app/components/information/labels.ts`
- `apps/web/lib/u1-upload.ts`
- `tests/web/test_u1_upload.mjs`

WP92 settings klasörü, WP94 try klasörü sahibidir; dosyalarına yazma. Ortak UI primitive'lerini
değiştirmeden kullan. `summary.tsx/collection-card.tsx` sahipliği dışarıda; gerekirse bağlı props ile çöz.

## Tasks

1. [U1 sözleşmelerini](../U1.md) uygula. Şirket seçiciye “Yeni şirket” ekle; WP92 POST ile oluştur,
   seç ve boş listeyi göster. Sunucu adı varsa onu kullan; eski id fallback'i koru. Ayarlar/Dene
   menüleri, Screen union ve page render yalnız bu WP'de bağlanır. WP92 WorkspaceSettings,
   WP94 TryView bileşenlerini belirtilen props/named export ile import et.
2. File input `multiple`; dosya başına register → content PUT → uploaded POST protokolü,
   SHA-256 dedup ve ayrı UploadState. Küçük sınırlı upload concurrency; ilk upload'dan sonra
   kalan dosyaları durdurma. İşleme bitişini beklemek diğer dosyanın yüklenmesini engellemesin.
   Aynı dosya tekrarında duplicate oluşturma; bir başarısız dosyayı ayrı yeniden denemek mümkün olsun.
3. Belgeler'de hazırlıkla bilgi işini ayrı anlat. “Bilgileri çıkar” tek birincil eylem; modelsiz
   durumda açıklama + Ayarlar yolu, boş/hazır olmayan/kısmi belge durumunda neden. Demo salt okunur.
   Ayar kaydetmek veya ekran açmak POST job/ask yapmasın. İstemci guard'ı API guard'ının yerine geçmez.
4. İş başlamasını record-jobs POST ile yap, aynı request_id tekrarını koru; latest/detail'i
   en geç 3 saniye aralıkla sorgula. Aşama/bitmiş aşama sayısı göster; sahte yüzde/bitme süresi yok.
   Yenilemede latest'ten sürdür. `needs_review` şema için kontrol mesajı; failed/timeout için sade hata.
   İş bitince summary/questions/collections yenilenir. Onaylı yayın varken tekrar çıkarma `409`
   açıklamasını göster; yeni sürüm/onay taşıma akışı icat etme.
5. Tek aday `needs_review` kartını “Bu bilgiyi onaylayın” diye göster; gerçek çelişkide mevcut
   belge gruplarını ve “Bu belge güncel” davranışını koru. Kaynak adı/konum/alıntı ulaşılabilir olsun.
   Cevap request'ine okunan revision_id'yi koy; `409` güncel veriyi yükler, başarılı gibi davranmaz.
   Cevap sonrası dönen revision Özet/Sorular/Koleksiyonlar'a yansır; Onaylı görünüm eski cache'te kalmaz.
6. Koleksiyon/alan adlarında keşfedilmiş Türkçe etiketi öncelikli kullan; bilinen label fallback'leri
   koru, raw snake_case varsayılan görünümde kalmasın. Şirket değişince upload/job/question/collection
   ve Dene ekranını sıfırla; AbortController veya nesil guard'ıyla gecikmiş eski yanıtları at.
7. frontend-design ve mevcut marka/Tailwind/shadcn içinde loading/empty/error/normal/offline durumları,
   klavye odakları, açık/koyu tema, 390 px. Büyük ekran tasarımı/başka CSS değişikliği yok.

## Tests

```powershell
node --test tests/web/test_u1_upload.mjs
node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web
```

Upload yardımcı fonksiyonuna fetch/hash bağımlılıkları enjekte et; Node'un yerleşik test runner'ı ve
mevcut TypeScript ile kurulum gerektirmeyen test. İki dosya protokolü, ikinci dosya hatası, dedup,
tekrar ve stale workspace callback testleri gerçek anlamlı davranışı denetler. Test transpile
gerektirirse kurulu TypeScript'i kullan, yeni test framework'ü ekleme.
Lider bağımlılıklar hazırken `npm run build` (apps/web içinde) ve [U1-checklist](../U1-checklist.md)
turunu masaüstü/390 px, açık/koyu tema, refresh/double click/şirket geçişinde çalıştırır.

## Acceptance criteria

- [ ] Tek seçimde iki dosya ayrı durumla yüklenir; biri hata olsa diğeri korunur; tekrar belge sayısını artırmaz.
- [ ] Boş şirket oluştur/seç, Ayarlar ve Dene navigasyonu gerçek bileşenlere ulaşır; default teknik terim yok.
- [ ] Kapalı model/hazırlanmamış belge ve demo yönlendirmeleri doğru; POST kullanıcı eylemiyle olur.
- [ ] Tek job ve refresh sonrası devam; aşama polling ≤3 sn; terminal/needs_review/hata dürüst gösterilir.
- [ ] Tek aday onay kartı ve gerçek çelişki ayrıdır; cevap sonrası Onaylı view yeni revision kullanır.
- [ ] Gecikmiş A şirketi yanıtı B'ye yazılmaz; stale answer `409` başarı görünmez.
- [ ] Node testleri/tsc; lider build+web turu kanıtı veya çalıştırılamayan kontrol açıkça raporlanır.
- [ ] 390 px yatay sayfa taşması yok; yeni .css/dependency yok.

## Notes

Oku: AGENTS.md, ROADMAP, [U1](../U1.md), wp54/wp55/wp56/wp60/wp63/wp66,
`docs/brand/BRAND.md`. Merge WP91/92/94 ardından; WP95 canlı smoke sonra.
