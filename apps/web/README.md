# Review console

Next.js tek client page üzerinden HTTP API'yi kullanır. Mevcut ekranlar documents, jobs, provider configuration, pipeline, page renders/extraction Markdown, demo chunks/assets ve version counts içerir. Nested route tree, generated OpenAPI types veya TanStack Query henüz yoktur.

Console `/healthz` ile mode'u öğrenir. Demo üst bantta açıkça belirtilir ve upload kapalıdır. Live sonuçlara örnek kayıt eklenmez; empty/error/loading durumları gösterilir. API yokken offline demo fallback yoktur.

Similarity grafiği ve sabit semantic diff kaldırılmıştır. Demo neighbor endpoint'i sentetik skor üretir ve bu açıkça etiketlenir. Retry uygulanmadığı için aktif retry kontrolü yoktur.

Page panelindeki Markdown dokümanın tamamının extraction çıktısıdır; sayfa bazında veya canonical değildir. JSON API üzerinden alınabilir. Source bbox overlay henüz yoktur. Yükleme sonrası job polling sınırlı sürelidir; listeler yenile düğmesiyle tekrar okunabilir.

```sh
npm ci
npm run dev
```

`NEXT_PUBLIC_API_URL` bundle build sırasında belirlenir. Varsayılan `http://localhost:8000`. UI tasarımı korunur; yeni framework eklenmez.
