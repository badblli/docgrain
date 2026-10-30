# WP125 raporu — Onaydan sonra güncelleme (Porygon)

## Summary

"Bilgileri çıkar" artık bir kişi değerleri onayladıktan sonra da çalışıyor. İş, yayındaki son revizyondan
(head) başlayan bir **güncelleme** olarak yürür:

- `records_jobs.start()` içindeki `has_accepted` engeli kaldırıldı; eski kontrol
  `_approval_guard_before_wp125` olarak `KULLANILMIYOR (karar 18, WP125)` işaretiyle duruyor. Pipeline'daki eski
  `publication_unchanged` da `_publication_unchanged_before_wp125` olarak duruyor. Head iş sırasında değişirse iş
  yine `publication_changed` ile durur.
- İçeriği (`content_sha256`) ve `knowledge_revision_id` değeri head revizyonundaki kaynak pin'iyle aynı olan
  belgeler yeniden çıkarılmıyor: kayıtları önceki işin dosyalarından gelir, model çağrısı yapılmaz.
- Kişinin kararları alan adayı bazında birleştirmeden sonra, yayından önce taşınıyor
  (`packages/records/docgrain_records/carry_forward.py`). Onaylı bir değerin belgesi değiştiyse ve belgede
  başka bir değer varsa değer ezilmiyor: alan "Belge değişti: önceki onaylı değer X, belgedeki yeni değer Y"
  sorusuna dönüşüyor, cevap verilene kadar eski değer yayında kalıyor.
- Lead incelemesinden sonra (2026-10-30): kişinin kararı ya da `user_edit` düzeltmesi korunurken **yeni veya
  değişmiş** bir belge aynı alan ve dil için başka bir değer verirse bu artık soru oluyor ("çelişkiler sorulur,
  sessizce çözülmez"). Değişmemiş belgelerden gelen değerler soruyu yeniden açmaz. Güncelleme sayıları iş okuma
  yanıtında (`update`) sadece sayı olarak gösteriliyor.
- Değişiklikten önceki dosyaların tam kopyaları `apps/worker/docgrain_worker/unused/wp125/` altında (LF, başlık
  satırıyla). Canlı dosyalarda bu kopyalara işaret eden yorumlar var.

## Tasarım

### 1. İşi başlatma ve eşzamanlı yayın koruması
- `start()` head revizyonunu `publication_head` olarak işe sabitler (önceden de böyleydi). Onay artık engel değil.
- `Pipeline.publication_unchanged()` yalnız head'in değişip değişmediğine bakar. Yayın adımındaki kilitli kontrol
  aynı fonksiyonu kullandığı için iş sırasında araya giren bir yayın `publication_changed` hatası verir (test var).

### 2. Değişmeyen belgeleri yeniden kullanma (`Pipeline._reuse_documents`)
- Yayınlanan head'den başlayıp `parent_id` zincirinde geriye gidilir; `record_job_id` değeri olan ilk revizyonun
  iş klasörü önbellek olarak kullanılır (cevap ve elle düzeltme revizyonlarının iş klasörü olmadığı için).
  Önbellek yalnız aynı çalışma alanının yayınlanmış atalarından gelir.
- Belge şu koşulların hepsini sağlıyorsa yeniden kullanılır: head pin'iyle `content_sha256` ve
  `knowledge_revision_id` aynı, önbellekteki pin de aynı, `records.json` var, çıkarmada başarısız bölüm
  (`failures`) yok, ayrıca belge önceki işte "model gerekiyordu ama kapalıydı" durumunda değil ya da model hâlâ
  kapalı. Model sonradan açılırsa böyle bir belge yeniden okunur (test var).
- Yeniden kullanılan belge için `_structure_result` çağrılmaz, model yolu (`discover`/`extract`) çalışmaz.
  `records.json` güncel sözleşmeyle (`runtime.result`) yeniden doğrulanır. "Aynı liste" cevabıyla emekliye
  ayrılan koleksiyon anahtarları alias üzerinden yeni anahtara çevrilir. Bu arada kenara ayrılan listelerin
  kayıtları atlanır.
- **Bilerek yapılan bir sapma:** Docling yapısı (yerel olarak saklanan Docling JSON'u) ve gruplama planı
  (`build_structure_plan`) her işte **bütün** belgeler için yeniden kurulur. Model çağrısı ve kayıt çıkarma
  yoktur; plan yalnızca belgeler arası liste birleştirmeyi (WP122) ve "aynı liste mi?" cevaplarını tutarlı
  tutmak için kurulur. İlk yazılan sürüm planı yalnız değişen belgeler için kuruyordu. O sürümde değişen bir
  belgenin listesi, cevapla birleştirilmiş listeden ayrı bir koleksiyon olarak çıkabiliyordu. Bu durum için
  `test_same_list_answer_holds_when_one_list_document_changes` testi eklendi.
- Mevcut WP110/WP113 retry/eşzamanlılık testleri gerçek çıkarmayı karşılaştırdığı için o iki testte
  `_reuse_documents` devre dışı bırakıldı.

### 3. Kararları taşıma (`carry_forward`, `apply_review_rules` öncesinde)
Önce yeni birleştirme kayıtları head kayıtlarıyla hizalanır (`_align`: aynı id → kimlik alanı kaynak alıntısı →
kimlik değeri; yalnız tek eşleşme varsa). Böylece cevaplanmış "aynı kayıt" birleştirmeleri ve kayıt id'leri
korunur. Taze bir birleştirme ayrı tutulan iki head kaydını tek kayıtta topladıysa eski kayıt, kaynak alıntısı
tek bir yeni kayıtla örtüşüyorsa o kayda taşınır. Bu durumda karar ve geçmişin `record_id` değeri de yeni
kayda çevrilir. Sonra her head adayı için şunlar yapılır:

| Durum | Sonuç |
|---|---|
| Kişinin kabul/ret kararı, belge değişmemiş | Karar aynen kalır (alıntı yeniden doğrulanmaz) |
| Kişinin kararı, belge değişmiş ama aynı alıntı yeni bağlamda var | Karar aynen kalır; alıntı yeni sürüme pinlenir |
| Onaylı değer, belge değişti, alıntı yok, belgede başka değer var | Kişi onayıysa soru: "Belge değişti: önceki onaylı değer X, belgedeki yeni değer Y". Eski değer yayında kalır, yeni değer `needs_review` olur |
| Onaylı değer, belgesi çalışma alanından kaldırıldı | Soru: "Güncel kaynak yok: önceki onaylı değer X". Değer sessizce silinmez, yayında kalır |
| Onaylı değer, belge değişti, değer belgeden tamamen çıktı | Soru: "Belge değişti: önceki onaylı değer X belgede artık bulunamadı" |
| Kuralın (karar 20) onayladığı değer başka bir değere değişti | Eski kural onayı düşer; yeni değeri karar 20 yeniden değerlendirir (çelişki yoksa otomatik onay, soru yok) |
| Kişinin kararı korunuyor, ama yeni ya da değişmiş bir belge aynı alan+dilde **başka** bir değer veriyor | Soru açılır, onaylı değer yayında kalır, yeni değer `needs_review` olur. Mesaj: yeni belgeyse "Yeni belge farklı bir değer veriyor: onaylı değer X, belgedeki değer Y"; aynı belgeyse "Belge değişti: önceki onaylı değer X, belgedeki yeni değer Y"; başka bir değişmiş belgeyse "Değişen belge farklı bir değer veriyor: onaylı değer X, belgedeki değer Y". `reasked_decisions` sayısına eklenir |
| `user_edit` (WP116) değeri | Her zaman kalır. Yeni ya da değişmiş bir belge farklı bir değer verirse yukarıdaki gibi soru açılır (sessizce `rejected` yapılmaz). Yalnız değişmemiş belgelerden gelen değerler eskisi gibi düzeltmenin arkasında `rejected` kalır |
| Aynı değer yalnız değişmemiş belgelerden geliyor | Soru açılmaz; cevaplanmış çelişki cevaplı kalır |
| Kişinin eklediği alan/koleksiyon/kayıt | `user_edit` kanıtıyla aynen kalır. Şema head'deki kabul edilmiş sözleşmeden birleştirilir (`combine_schemas(cached, yeni)`) |
| Cevaplanmamış kaynak sorusu, girdiler değişmemiş | Aynı soru (aynı id ve seçenekler) kalır |
| Kaynak sorusu cevaplandı, girdiler değişmemiş | Cevap kalır, tekrar sorulmaz ("eski değeri koru" cevabı dahil) |
| Cevaplanmış "aynı kayıt / farklı kayıt" sorusu | Kayıtlar `_align` ile head id'lerine eşlenir, `duplicate_decisions` taşınır; soru geri gelmez |

- Kaynak soruları `MergedField.source_changes: {dil: mesaj}` alanında tutulur. Alanın `review_state` değeri
  `needs_review` olur, `review.questions()` bu dili soru olarak verir (`source_changed: true`, `question_tr` =
  mesaj, iki kaynak seçenek olarak). Cevap (`answer_revision`) o dildeki mesajı siler. Projeksiyon alanda
  `source_change` mesajını gösterir.
- Eski kaynaklara bağlı alıntılar için `MergeRevision.historical_documents` tutulur. Bu pin'ler çıkarma girdisi
  değildir, yalnız kanıt ve dışa aktarma doğrulaması için kullanılır.
- `decisions`, `history`, `duplicate_decisions`, `user_changes` head'den taşınır. `collection_merge_decisions`
  WP119'daki gibi head'den alınır. Yeni revizyonun `parent_id` değeri head, `lineage_id` değeri head'in
  soyudur.

### 4. Eski revizyon
Head revizyonu değişmez. Testler güncellemeden sonra eski revizyonun onaylı baytlarının revizyon id'siyle aynen
okunabildiğini doğruluyor.

## Belge başına saklananlar (yeniden kullanım için)
İş klasörü `runtime/<sha256(job_id)>/`:
- `records/<sha256(document_id)>/records.json`: belgenin doğrulanmış kayıtları (yapı + model). Yeniden
  kullanılan belgeler için de yeni iş klasörüne yazılır, böylece zincir sonraki işte devam eder.
- `records/<sha256(document_id)>/source.json` ve `context.md`: pin'li kaynak (WP125 öncesi işlerde de vardı,
  geriye dönük kullanılır).
- `reuse.json` (yeni): `{"discovery": {"documents": [...], "calls": n}, "documents": {document_id:
  {"content_sha256", "knowledge_revision_id", "model_calls", "model_pending"}}}`.
- WP125 öncesi bir işte `reuse.json` yoksa `source.json` ile `structure/plan.json` içindeki
  `documents_needing_model` kullanılır.

## Metadata sayıları
- `metadata.document_reuse = {"reused", "processed", "model_calls_saved"}`. `model_calls_saved`, yeniden
  kullanılan belgelerin önceki çıkarma çağrılarının toplamıdır. Keşif adımının belgelerinin hepsi yeniden
  kullanıldıysa önceki keşif çağrıları da sayılır.
- `metadata.carry_forward = {"kept_decisions", "reasked_decisions", "new_values", "removed_values"}`:
  - `kept_decisions`: aynen taşınan kişi kararları ve `user_edit` değerleri;
  - `reasked_decisions`: bu işte kaynak sorusuna dönüşen onaylı değerler (alan+dil başına bir);
  - `new_values`: head'de olmayan (dil, değer) adayları (yeni kayıt ve alanlar dahil);
  - `removed_values`: güncel kaynağı kalmayan, reddedilmemiş eski değerler (soruya dönüşenler dahil).
- İş okuma yanıtı (`GET /v1/workspaces/<ws>/record-jobs/<id>` ve `/latest`) artık `update` alanını içerir:
  `{"reused", "processed", "model_calls_saved", "kept_decisions", "reasked_decisions", "new_values",
  "removed_values"}`. Değerler yalnız tamsayıdır, kaynak metni içermez (`records_jobs.update_counts`). Sayılar
  henüz yoksa alan `null` olur.
- Ayrıca `summary.notes` sade Türkçe notlar verir: "N belge değişmediği için yeniden okunmadı", "N onay ve
  düzeltme korundu", "N onaylı değerin belgesi değişti; soru olarak soruldu" (yalnız sayı sıfırdan büyükse;
  ilk çalıştırmanın notları değişmez).

## Files changed
- `apps/api/docgrain_api/records_jobs.py`: onay engeli kaldırıldı, eski hali KULLANILMIYOR olarak duruyor;
  iş özetine (`summary.notes`) güncelleme notları ve `update_counts()` eklendi.
- `apps/api/docgrain_api/routers/record_jobs.py`: okuma yanıtına sayısal `update` alanı eklendi.
- `apps/worker/docgrain_worker/records_pipeline.py`: `publication_unchanged`, `_reuse_documents`,
  `_accepted_update_schema`, yapı planı bütün belgeler için kuruluyor, model yolu yalnız değişen belgelerde
  çalışıyor, `reuse.json`, `carry_forward` çağrısı, metadata.
- `packages/records/docgrain_records/carry_forward.py` (yeni).
- `packages/records/docgrain_records/merge_models.py`: `MergedField.source_changes`,
  `MergeRevision.historical_documents`.
- `packages/records/docgrain_records/review.py`: kaynak soruları, cevapta soru temizleme, tarihsel belge adları.
- `packages/records/docgrain_records/export.py`: `source_change` projeksiyonu, tarihsel pin'ler.
- `tests/unit/test_update_after_approval.py` (yeni, 19 test), `tests/unit/test_u1_pipeline.py` (onay sonrası 202;
  iki eski karşılaştırma testinde yeniden kullanım kapalı).
- `apps/worker/docgrain_worker/unused/wp125/`: yukarıdaki kaynak dosyaların (router için
  `record_jobs_router.py`) ve `test_u1_pipeline.py` dosyasının (`.txt`) değişiklik öncesi tam kopyaları.

## Tests run
Worktree kökünden, ana repo venv'i ile:
- `C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q -p no:cacheprovider --basetemp <scratch>/wp125-pt`
  → **1739 passed, 159 skipped**, 3 uyarı (mevcut starlette/PIL uyarıları).
- `... -m pytest -q tests/unit/test_update_after_approval.py` → **19 passed**.
- `C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m ruff check .` → `All checks passed!`
- `git diff --check` → temiz. Yeni dosyalar LF, sonda boşluk yok.
- Docker worker imajındaki entegrasyon testleri (Docling/OCR/DB) çalıştırılmadı; bu ortamda Docker yok.

## Acceptance criteria
3 sentetik belge ("alpha/beta/gamma", sahte HTTP model), head'de kişi onaylı değerler:
- Hiçbir şey değişmedi → iş çalışıyor, 0 belge yeniden çıkarıldı (`_structure_result` çağrılırsa test düşer),
  0 model çağrısı, kayıtlar/kararlar/geçmiş aynı, `kept_decisions=6`: **met**
  (`test_unchanged_reuses_all_documents_and_keeps_every_human_decision`).
- Bir belgenin yeni sürümü kişi onaylı değeri değiştirdi → tam bir soru, eski ve yeni değer iki kaynakla
  (`alpha-s1`, `alpha-s2`), diğer kayıtlar aynı, onaylı yayında eski değer duruyor; tekrar çalıştırmada soru aynı;
  cevaptan sonra yeni değer yayında: **met** (`test_changed_accepted_value_asks_once_...`). "Eski değeri koru"
  cevabı tekrar sorulmuyor: **met** (`test_keeping_the_old_value_is_not_asked_again_...`).
- Kimsenin bakmadığı değer değişti → karar 20 ile otomatik onay, soru yok: **met**
  (`test_changed_unreviewed_value_uses_decision_20`).
- `user_edit` değeri, eklenen alan, koleksiyon ve kayıt güncellemeden sonra duruyor: **met**
  (`test_user_edit_field_collection_and_record_survive`). Aynı testte değişen belgenin farklı değeri tek soru
  oluyor ("Değişen belge farklı bir değer veriyor: onaylı değer 17, belgedeki değer 9"), yayında 17 kalıyor,
  tekrar çalıştırmada soru aynı, "17'yi koru" cevabından sonra değişmeyen çalıştırmada sorulmuyor.
- Lead incelemesi 1: yeni belge onaylı değere farklı değer veriyor → tek soru, iki seçenek, yayında eski değer;
  cevaptan sonra (eskiyi koru / yeniyi seç, iki parametre) değişmeyen çalıştırmada sorulmuyor: **met**
  (`test_new_document_with_another_value_for_an_approved_field_asks_once`). Cevaplanmış bir çelişki yalnız
  değişmemiş belgelerle yeniden açılmıyor: **met** (`test_unchanged_documents_never_reopen_an_answered_conflict`).
- Lead incelemesi 3: iş okuma yanıtında sayısal `update` sayıları: **met**
  (`test_job_read_exposes_update_counts`).
- Duplicate cevapları ("aynı kayıt" ve "farklı kayıt") bir güncellemeden sonra geçerli, soru geri gelmiyor:
  **met** (`test_duplicate_answer_survives_an_update`, iki parametre).
- Belge kaldırıldı → değerleri "Güncel kaynak yok" sorusu, değerler yayında; cevaplanana kadar soru kalıyor,
  cevaptan sonra sorulmuyor: **met** (`test_removed_document_...` iki test).
- İş sırasında head değişti → `publication_changed`: **met** (`test_update_still_rejects_concurrent_publication`).
- Eski revizyon id'siyle okunabiliyor: **met** (ilk iki testte bayt karşılaştırması).
- Ek testler: aynı alıntı yeni bağlamda var (hash değişse de değişmese de) → kararlar aynı; model kapalıyken
  atlanan belge model açılınca okunuyor; "aynı liste" cevabı bir liste belgesi değişince de geçerli.
- Tam pytest yeşil, ruff temiz: **met**.

## Decisions needed
1. (Çözüldü, lead incelemesi) Yeni ya da değişmiş bir belgenin farklı değeri artık soru oluyor.
2. (Çözüldü, lead incelemesi) `user_edit` slotunda da aynı kural uygulanıyor; yalnız değişmemiş belgelerin
   değerleri `rejected` kalıyor.
   Not: kişinin daha önce reddettiği bir değeri değişmiş bir belge yeniden söylerse soru açılmıyor; ret
   kararı kalıyor. Soru yalnız head'de hiç bulunmayan bir (dil, değer) için açılıyor.
3. Model ayarı değişince (başka bir model) değişmeyen belgeler yeniden çıkarılmıyor. Yalnız "model kapalıyken
   modele ihtiyaç duyan belge" model açılınca yeniden okunuyor. Model değişince tam yeniden çıkarma isteniyorsa
   bir "hepsini yeniden çıkar" seçeneği gerekir.
4. (Çözüldü) Duplicate cevapları için test eklendi.
5. Liste alanlarında (birden çok onaylı değer) yeni bir belge listeye yeni bir öğe eklerse bu da soru olarak
   soruluyor. Bu bilinçli olarak tutucu bir davranış.

## Lead için canlı adımlar
1. Demo çalışma alanında "Bilgileri çıkar" çalıştırın, bitmesini bekleyin.
2. Sorulardan birinde ya da "otomatik onaylananlar" listesinde bir değeri **onaylayın** (ör. bir miktar ya da
   saat).
3. Aynı değerin geçtiği belgenin değiştirilmiş yeni sürümünü yükleyin (WP124 gelene kadar: belgeyi aynı adla
   yeniden yükleyip yeni sürüm oluşturun), hazırlanmasını bekleyin.
4. "Bilgileri çıkar"ı yeniden çalıştırın. Beklenen sonuç: iş 409 vermeden başlar ve biter.
   `GET /v1/workspaces/<ws>/record-jobs/<id>` yanıtında `update.reused` = değişmeyen belge sayısı,
   `update.processed` = 1, `update.reasked_decisions` = 1 olur. `summary.notes` içinde "N belge değişmediği
   için yeniden okunmadı" ve "1 onaylı değerin belgesi değişti; soru olarak soruldu" notları görünür.
5. Sorular listesinde "Belge değişti: önceki onaylı değer X, belgedeki yeni değer Y" sorusu iki kaynakla görünür.
   Onaylı JSON'da hâlâ X vardır.
6. Y'yi seçin. Onaylı JSON'da Y görünür. "Bilgileri çıkar"ı bir kez daha çalıştırın: yeni soru çıkmaz, 0 model
   çağrısı yapılır.
7. İsteğe bağlı: bir belgeyi silip yeniden çalıştırın. O belgenin değerleri "Güncel kaynak yok" sorusu olur ve
   yayında kalır.
8. İsteğe bağlı: onaylı bir değere farklı değer veren yeni bir belge yükleyip yeniden çalıştırın. "Yeni belge
   farklı bir değer veriyor: ..." sorusu çıkar. Cevap verdikten sonraki değişmeyen çalıştırmada soru çıkmaz.

## Suggested commits
- `feat(records): update records after approval and reuse unchanged documents (WP125, Porygon)`: bütün
  değişen/yeni dosyalar (`apps/api/docgrain_api/records_jobs.py`, `apps/api/docgrain_api/routers/record_jobs.py`,
  `apps/worker/docgrain_worker/records_pipeline.py`, `apps/worker/docgrain_worker/unused/wp125/`,
  `packages/records/docgrain_records/{carry_forward,merge_models,review,export}.py`,
  `tests/unit/test_update_after_approval.py`, `tests/unit/test_u1_pipeline.py`, bu rapor).
