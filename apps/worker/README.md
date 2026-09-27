# Worker

Redis listesinden job ID alır, PostgreSQL queued → running claim yapar, PDF'yi MinIO'dan indirir ve PyMuPDF ile render eder. Gemini key varsa tüm sayfalarda Gemini; yoksa OCR kapalı Docling çalışır.

Çıktılar provider-specific `document.json`, `document.md`, `pages.json`, page PNG ve Gemini yolunda başarılı sayfa JSON'larıdır. Canonical model/reconciliation, normalization, manifest, chunking ve indexing yoktur. `publish` yalnızca extraction output kaydıdır.

Gemini page calls en fazla dört concurrent task ve üç attempt kullanır. Stage retry endpoint'i çalışmaz. Redis BRPOP sonrası job ack/lease/recovery yoktur; worker crash sonrası otomatik devam garantisi verilmez. Başarılı page sonuçları batch bitiminde yazılır.

Stage özetleri sonda kaydedilir; başlangıç zamanı, stage duration ve gerçek attempt sayısı ölçülmez. Demo için worker çalıştırmayın. M0 extraction ownership'ini değiştirmez; hedef Docling primary + Vision enrichment için [mimari](../../docs/ARCHITECTURE.md).
