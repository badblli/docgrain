# D1 değerlendirme aracı

`docgrain-eval`, yayımlanmış belge içeriklerini altın sorularla ölçer. Model çağrısı
yalnızca `run` komutunda, `--dry-run` kaldırılıp model ayarları verilince yapılır.

```sh
pip install -e packages/evaluation
docgrain-eval run --questions data/golden/questions.jsonl --workspace ws_local \
  --api http://localhost:8000 --dry-run
docgrain-eval run --questions data/golden/questions.jsonl --workspace ws_local \
  --api http://localhost:8000 --mode direct_context \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-3.7-flash --api-key-env GEMINI_API_KEY --out data/eval/run-001/
docgrain-eval tables --facts data/golden/tables.jsonl \
  --api http://localhost:8000 --out data/eval/tables-001/
docgrain-eval compare data/eval/run-001 data/eval/run-002
```

`run` her belge için son KnowledgeRevision kimliğini ve yayımlanmış `canonical.md`
dosyasını okur. Özet, kullanılan revizyonları, bağlamın karakter sayısını ve yaklaşık
token sayısını (`karakter / 4`) kaydeder. `results.jsonl` her soru için yanıtı, ayrıştırılan
JSON'u, istem özeti SHA-256 değerini, atıf ve doğruluk kararını, süreyi içerir.
`summary.json` ve `summary.md` genel doğruluğu sunar. JSON özeti ayrıca kategori,
zorluk ve belge bazında doğruluğu, çekimserlik kesinliği/duyarlılığı, belge ve sayfa
atıf isabetini, p50/p95 süreyi ve sağlayıcının döndürdüğü token kullanımını içerir.

Puanlama deterministiktir; eş anlamlılık veya çıkarım hakemliği yapmaz. Metin
normalleştirme ve `accept` biçimleri yazım farklarını karşılar. `list` için tüm maddeler
aranır. Sayı karşılaştırmasında tolerans sıfırdır. Atıf isabeti doğru belgeyi ölçer;
sayfa isabeti yalnızca altın kanıtta sayfa varsa hesaplanır. `tables` yayımlanmış
`canonical.json` içindeki tablo hücrelerini denetler; tablo, satır veya sütun
bulunamazsa durum `missing`, hücre farklıysa `wrong` olur. Model çağırmaz.

Bağlam tüm çalışma alanını içerir; büyük çalışma alanlarında modelin bağlam sınırı
aşılabilir. Token sayısı yalnızca tahmindir. Kaynak içeriği güvenilmeyen veri olarak
istemde belirtilir; sonuçların anlam doğruluğu yine altın veriyle ayrıca incelenmelidir.
