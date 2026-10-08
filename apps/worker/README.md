# Worker

Redis listesinden job ID alır, PostgreSQL queued → running claim yapar ve doğrulanmış PDF/DOCX/XLSX/PNG/JPEG kaynağını Docling + Tesseract ile okur. Varsayılan profil `C_tesseract`; TXT deterministik okuyucuda kalır. Görseller ve tamamen metinsiz PDF'ler tam sayfa OCR kullanır. Karma PDF'ler Docling 2.130'un dosya başına tek OCR modu nedeniyle bölge modunda kalır.

Docling JSON'u checksum ve değişmez MinIO sürümüyle canonical revision'a bağlı bir artifact olarak saklanır. DOCX kaynak bağlantıları bu JSON'un nesne yollarıdır; OOXML konumu iddia edilmez. XLSX'te yalnız Docling'in verdiği hücrelere sayı/tarih/yüzde biçimi ve mevcut formül sonucu eklenir; formül hesaplanmaz, eksik hücre/tablo tamamlanmaz. PDF inceleme PNG'leri aynı Docling dönüşümünden gelir (`images_scale=2`, 144 DPI); `pages.json`, `document.json` ve `document.md` sözleşmeleri korunur.

Sayfa kalite sinyalleri Docling confidence raporunun düşük notlarından gelir; OCR ve içerik otomatik onaylanmaz. B/D/E profilleri ölçüm için seçilebilir; A kaldırılmıştır. E yalnız açık profil seçimi, endpoint, model ve anahtar ortam değişkeniyle çalışır. Eski tüm sayfaları Gemini'ye gönderen yol kaldırılmıştır. Ayrı seçili görsel inceleme araçları bu WP kapsamında değiştirilmediği için `google-genai` bağımlılığı korunur.

Canonical persistence etkinse canonical JSON/Markdown, AI çıktısı, chunks ve doğrulanmış manifest yayımlanır; embedding yapılmaz. Stage özetleri sonda kaydedilir; stage süreleri ve deneme sayıları ölçülmez. Redis BRPOP sonrası ack/lease/recovery ve stage replay garantisi yoktur. Okuyucu kararı: [ADR 0024](../../docs/adr/0024-docling-reads-documents.md).
