# WP124 — Charizard uygulama notları

Codex ajanı kullanım sınırına takılınca yarım kalan çalışma Charizard (Claude alt ajanı)
tarafından tamamlandı. Yarım değişikliklerin iyi kısımları korundu; düzeltilen ve
eklenenler aşağıda.

## Çalıştırılan kontroller

Çalışma ağacının kökünden, ana deponun sabitlenmiş sanal ortamıyla:

```sh
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q -p no:cacheprovider --basetemp "<scratchpad>/wp124-pt"
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m ruff check .
git diff --check
```

- Tam test: **1739 passed, 162 skipped** (186 sn). Ruff: **All checks passed!**
  `git diff --check` temiz; yeni dosyalarda satır sonu boşluğu ve CRLF yok.
- WP124 modülleri (`test_file_version_diff.py`, `test_file_versions_api.py`,
  `test_file_versions_live.py`, `test_modes.py`, `test_knowledge_api.py`):
  **43 passed, 3 skipped**.
- Atlanan WP124 testleri (Docker gerektirir, burada çalıştırılmadı):
  - `tests/integration/test_file_versions_live.py::test_api_version_promotes_only_after_usable_completion_and_never_rolls_back`
    (`done` ve `partial`, 2 adet) — `DOCGRAIN_M1_TEST_DATABASE_URL` ile yalıtılmış PostgreSQL ister.
    `repository.add_version` ve `document_jobs.promote_usable_version` SQL'i yalnız bu testle
    doğrulanır; host'ta doğrulanmadı.
  - `tests/integration/test_file_versions_live.py::test_real_docx_single_word_and_single_cell_diff`
    — Docling worker imajı ister (gerçek DOCX → Docling → diff).
- Docling host'ta kurulu değil. Gerçek Docling biçimi için depodaki Docling 2.130 çıktısı
  `tests/fixtures/structural/wp118-structured.docling.json` kullanıldı (biçimli paragraf
  `InlineGroup`, tablo hücre bayrakları).

## Kabul ölçütleri

| Ölçüt | Durum | Kanıt |
|---|---|---|
| Yeni sürüm → `revision=2`, aynı belge kimliği; iş bitene kadar eski sürüm en güncel | sağlandı (birim) | `test_new_version_same_document_pending_status_renamed_upload_and_confirmation` |
| Aynı sha → `deduplicated` | sağlandı | `test_same_sha_is_deduplicated_and_other_format_rejected` |
| Biçim ailesi değişimi → 415 (PDF/XLSX gibi; TXT→XML de) | sağlandı | aynı test + `test_old_failed_revision_is_not_reused_and_txt_xml_are_different_families` |
| Başarısız yeni sürüm eskiyi en güncel bırakır | sağlandı (birim); gerçek DB'de doğrulanmadı | birim testi + atlanan canlı test |
| Bir kelime → tam 1 `changed`, önce/sonra metniyle | sağlandı | `test_one_word_is_one_changed_paragraph_with_both_locators`, gerçek Docling JSON: `test_real_docling_export_one_word_in_formatted_paragraph_and_one_cell` |
| Bir fiyat hücresi → 1 `changed`, satır + sütun başlığıyla | sağlandı | `test_one_price_cell_addressed_by_row_and_column`, gerçek Docling JSON'da `Family` / `Price` |
| 1 paragraf eklendi + 1 silindi → 1 added + 1 removed | sağlandı | `test_added_and_removed_paragraph_do_not_shift_following_units` |
| Aynı metin yeniden kaydedildi → 0 | sağlandı | `test_resaved_content_unicode_and_whitespace_are_unchanged` |
| İki eşit paragraf yer değiştirdi → 0 | sağlandı | `test_swapped_paragraphs_and_duplicate_multiplicity` |
| Gerçek DOCX (Docling) ile aynı ölçütler | doğrulanmadı | worker imajında `test_real_docx_single_word_and_single_cell_diff` |

## Kanonik kimlikler sürümler arasında kararlı mı?

**Hayır, kimlik olarak kullanılamaz.** `canonical_mapper` kimlik politikası 0.2.0'da düğüm
kimliği kaynak konumundan türer: PDF'te sayfa + bbox geometrisi, Docling JSON'da nesne
yolu (`#/texts/7`), DOCX'te blok yolu. Metin girdisi değildir; bu yüzden yerinde
düzenlenen bir paragraf kimliğini korur. Ancak öne bir paragraf eklenince sonraki tüm
`#/texts/N` yolları kayar, PDF'te satır kayması geometriyi değiştirir. Politika 0.1.0'da
PDF kimliğine metin özeti de girer (içerikten türer). Sonuç: `canonical_diff` (kimliğe
göre) iki dosya sürümünde düzenlemeyi "silindi + eklendi" ya da çok sayıda kaymış nesne
olarak gösterebilir. WP124 farkı bu yüzden kimliğe değil, yapı adresine (başlık yolu,
tablo + satır/sütun başlığı, anahtar) ve normalleştirilmiş metin benzerliğine dayanır.
Docling `ref` değerleri sonuçta yalnız sürüme özgü konum olarak verilir.

## Farkın biçimi (WP125 sözleşmesi)

Genel işlev: `docgrain_domain.canonical.version_diff.diff_docling_documents(before, after)
-> DocumentChanges` (saf; G/Ç, model, docling bağımlılığı yok). Ayrıntı modülün
docstring'indedir. `model_dump(mode="json")`:

```json
{
  "has_changes": true,
  "added_units": 0, "removed_units": 0, "changed_units": 1, "unchanged_units": 21,
  "changes": [{
    "operation": "changed",
    "kind": "table_cell",
    "address": {"heading_path": ["Services"], "group_path": [], "position": 4,
                "table": "Services", "row_header": "Delivery", "column_header": "Price"},
    "before": "10", "after": "12",
    "before_locator": {"ref": "#/tables/0", "provenance": [{"page_no": 1, "bbox": {}}], "row": 1, "column": 1, "cell_ref": null},
    "after_locator":  {"ref": "#/tables/0", "provenance": [{"page_no": 1, "bbox": {}}], "row": 1, "column": 1, "cell_ref": null}
  }]
}
```

- `kind`: `heading`, `paragraph`, `list_item`, `table_cell`, `key_value`, `picture_text`.
- `operation`: `added` (yalnız `after`), `removed` (yalnız `before`), `changed` (ikisi).
- WP125: `has_changes == false` ise belge atlanabilir; değilse `changes` içindeki birimler
  ve iki taraftaki konumlar değişenlerdir.
- API `GET /v1/versions/{id}/diff?base=...` bu alanları eski `VersionDiff` alanlarıyla
  (`base_version_id`, `head_version_id`, `page_delta`, `chunk_delta`, `table_delta`,
  `asset_delta`, `entries=[]`) birlikte döndürür. Demo fikstürleri eski sayaç yanıtını alır.

## Tasarım kararları

- **Yeni sürüm uç noktası**: `POST /v1/documents/{document_id}/versions`; gövde kayıt
  gövdesiyle aynı (`workspace_id` isteğe bağlı, belgeninkinden farklıysa 400). Aynı belge
  için kayıtlar belge kilidiyle sıralanır; `add_version` belge satırını kilitleyip
  revizyonu `MAX(revision)+1` olarak transaction içinde verir (başarısız revizyonlar da
  sayılır, numara tekrar kullanılmaz). Yeni dosya adı/MIME sürüme yazılır
  (`document_versions.filename/mime_type`, eski satırlar için NULL → belge değerleri);
  belge başlığı değişmez. `PUT .../content` ve `POST .../uploaded` sürümün dosya adını kullanır.
- **Tekilleştirme**: önce en güncel sürümün sha'sı; ayrıca en güncelden **yeni** olan
  işlenen/başarısız sürümler (yükleme yeniden denemesi; başarısızsa WP108 gibi yeniden
  kuyruğa alınır). En güncelden eski başarısız bir revizyon artık yeniden kullanılmaz:
  onun işi bitse bile en güncel olamazdı (Codex sürümündeki hata; düzeltildi). Eski bir
  içeriğe geri dönüş yeni revizyon üretir.
- **Biçim ailesi**: Docling okuyucusu (`SPECS[...].docling_format`); TXT ve genel XML'de
  okuyucu olmadığı için kendi değeri. Codex sürümünde ikisi de `None` olduğundan TXT→XML
  geçiyordu; düzeltildi. JPG↔PNG aynı aile (`image`); DOC↔DOCX farklı aile (karar
  gerekirse bkz. aşağı).
- **En güncel sürümün değişmesi**: yalnız worker'ın işi bitirdiği son transaction'da
  (`document_jobs.promote_usable_version`): sürüm ve iş `done/partial` olmalı, yalnız daha
  yüksek revizyon terfi eder (geç biten eski iş geri alamaz). Kanonik kalıcılık açıkken
  kanonik çıktı yayımlanmış olmalı; kapalıyken `done/partial` yeterli (Codex sürümü bu
  durumda hiç terfi etmiyordu; düzeltildi). Hata/kurtarma yolları terfi etmez.
- **Bilgi okuma**: işi biten yeni sürümün ayrıştırması kanonik başlığı (head) önceden
  ilerletebildiği için `latest_knowledge` başlıktan geriye, en güncel sürümün sha'sına
  eşleşen anlık görüntüye yürür; en güncel sürüm hazır değilse 404. Kayıt işi
  (`records_jobs.source_snapshot`) bu işlevi kullandığından eski iyi sürümü görmeye
  devam eder (kayıt koduna dokunulmadı).
- **Docling JSON**: worker artık PDF dışı biçimlerde de sürüm başına
  `artifacts/{doc}/{version}/document.json` yazar. Fark bunu okur; yoksa (WP124 öncesi
  Office sürümleri) kanonik anlık görüntüdeki gömülü/artefakt Docling belgesine düşer
  (sha256 doğrulamalı). Girdi yoksa boş fark değil 409 döner.
- **Fark algoritması** (Codex taslağı üzerine eklenenler): Docling'in biçimli paragrafları
  `InlineGroup` içinde parçalara böldüğü gerçek çıktıda görüldü — artık bir paragraf tek
  birim (önceden kalın bir kelime paragrafı 5 birime bölüyordu); tablo başlıkları paragraf
  birimi; satır/sütun etiketi veya başlık değişince hücreler ızgara konumuyla eşleşir
  (`Delivery → Shipping` = 1 değişen hücre); başlık bayrağı olmayan tabloda ilk satır
  sütun etiketi; iç içe yeniden adlandırılan başlıklar dıştan içe çözülür; büyük
  tablolar için başlık eşlemesi doğrusal. Performans: tamamen yeniden yazılmış
  1000 paragraf ~100 sn'den ~0,7 sn'ye indi (kelime ön elemesi, eşleştirici önbelleği,
  çok büyük gruplarda %5 göreli konum penceresi).
- **Kullanılmayan kod**: eski sayaç farkı `_count_only_diff` olarak duruyor
  (`# KULLANILMIYOR (karar 18, WP124)`, yalnız demo fikstürleri çağırır); eski `add`
  `_unused_add_before_file_versions` olarak duruyor; değişen canlı dosyaların tam
  önceki kopyaları `apps/worker/docgrain_worker/unused/wp124/` altında (documents,
  knowledge, versions, repository, worker main).

## Bilinen sınırlar / karar gerekebilecekler

- Çok kısa paragraflarda tek kelime değişimi (ör. `Açık` → `Kapalı`) benzerlik eşiğinin
  (.60) altında kalabilir ve 1 silindi + 1 eklendi olarak görünür.
- Bir satır silinip aynı yere farklı bir satır eklenirse ızgara konumu eşlemesi bunu
  "değişen hücreler" olarak gösterir.
- DOC→DOCX yeni sürümü 415 alır (farklı Docling okuyucusu). İstenirse aile eşlemesi genişletilebilir.
- Web arayüzü ve `docs/` altında ayrı API notu yok; sözleşme modül docstring'inde.

## Lider için canlı komutlar

Docker imajları yeniden kurulduktan sonra (API `http://localhost:8000`). Sentetik iki DOCX:

```sh
python - <<'EOF'
from docx import Document
for name, word, price in (("v1", "three", "10"), ("v2", "four", "10")):
    d = Document()
    d.add_heading("Service prices", level=1)
    d.add_paragraph(f"Delivery takes {word} days.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Service", "Price"
    t.cell(1, 0).text, t.cell(1, 1).text = "Delivery", price
    d.save(f"/tmp/wp124-{name}.docx")
EOF
MIME=application/vnd.openxmlformats-officedocument.wordprocessingml.document
API=http://localhost:8000

# 1) v1 yükle
SHA=$(sha256sum /tmp/wp124-v1.docx | cut -d' ' -f1); SIZE=$(stat -c%s /tmp/wp124-v1.docx)
R=$(curl -s -X POST $API/v1/documents -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"ws_wp124\",\"filename\":\"guide.docx\",\"mime_type\":\"$MIME\",\"byte_size\":$SIZE,\"content_sha256\":\"$SHA\"}")
DOC=$(echo "$R" | jq -r .document.id); V1=$(echo "$R" | jq -r .version.id); J1=$(echo "$R" | jq -r .job_id)
curl -s -X PUT "$API/v1/documents/$DOC/versions/$V1/content" -F "file=@/tmp/wp124-v1.docx;filename=guide.docx;type=$MIME"
curl -s -X POST "$API/v1/documents/$DOC/versions/$V1/uploaded"
curl -s $API/v1/jobs/$J1 | jq .status          # done/partial olana kadar tekrarla

# 2) v2 (tek kelime farklı) aynı belgenin yeni sürümü olarak
SHA=$(sha256sum /tmp/wp124-v2.docx | cut -d' ' -f1); SIZE=$(stat -c%s /tmp/wp124-v2.docx)
R=$(curl -s -X POST $API/v1/documents/$DOC/versions -H 'content-type: application/json' \
  -d "{\"filename\":\"guide.docx\",\"mime_type\":\"$MIME\",\"byte_size\":$SIZE,\"content_sha256\":\"$SHA\"}")
V2=$(echo "$R" | jq -r .version.id); J2=$(echo "$R" | jq -r .job_id)
echo "$R" | jq '{revision: .version.revision, latest: .document.latest_version_id}'   # 2, hâlâ V1
curl -s -X PUT "$API/v1/documents/$DOC/versions/$V2/content" -F "file=@/tmp/wp124-v2.docx;filename=guide.docx;type=$MIME"
curl -s -X POST "$API/v1/documents/$DOC/versions/$V2/uploaded"
curl -s $API/v1/jobs/$J2 | jq .status          # done/partial olana kadar tekrarla
curl -s $API/v1/documents/$DOC | jq .latest_version.id          # artık V2
curl -s $API/v1/documents/$DOC/versions | jq '.[] | {revision, status, filename}'

# 3) farkı oku: beklenen changed_units=1, before/after paragraf metni
curl -s "$API/v1/versions/$V2/diff?base=$V1" | jq '{has_changes, changed_units, added_units, removed_units, unchanged_units, changes}'
```

Worker imajında ayrıca: `pytest -q tests/integration/test_file_versions_live.py`
(`DOCGRAIN_M1_TEST_DATABASE_URL` ayarlı).
