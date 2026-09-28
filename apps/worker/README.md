# Worker

Redis listesinden job ID alır, PostgreSQL queued → running claim yapar ve PDF/DOCX/TXT/XLSX kaynağını MinIO'dan indirir. Hash, boyut ve biçim doğrulamasından sonra PDF/DOCX/XLSX Docling-first, TXT deterministik structural parser'a gider. Sürüm ID'si olan kaynaklar canonical DB revision'a map edilir. PDF için ayrıca PyMuPDF render ve mevcut Gemini key varsa Gemini, yoksa Docling legacy extraction devam eder.

PDF legacy çıktıları provider-specific `document.json`, `document.md`, `pages.json`, page PNG ve Gemini yolunda başarılı sayfa JSON'larıdır. DOCX/TXT/XLSX için sahte PDF artifact üretilmez. Canonical revision PostgreSQL'de ayrıdır; `canonical.json`, reconciliation, processing manifest, chunking ve indexing yoktur.

Gemini page calls en fazla dört concurrent task ve üç attempt kullanır. Stage retry endpoint'i çalışmaz. Redis BRPOP sonrası job ack/lease/recovery yoktur; worker crash sonrası otomatik devam garantisi verilmez. Başarılı page sonuçları batch bitiminde yazılır.

Stage özetleri sonda kaydedilir; başlangıç zamanı, stage duration ve gerçek attempt sayısı ölçülmez. Demo için worker çalıştırmayın. PDF legacy extraction ve M1b canonical structural yolunun ayrımı için [mimari](../../docs/ARCHITECTURE.md) ve [ADR 0006](../../docs/adr/0006-m1b-structural-parsing.md) belgelerine bakın.
