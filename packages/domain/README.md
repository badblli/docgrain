# Domain contracts

Vendor-neutral Pydantic document/version/page/table/asset/chunk/job sözleşmeleri, ID helpers ve state helpers implement edilmiştir. Worker shared state machine'i henüz kullanmaz; çoğu content modeli demo/API contract düzeyindedir.

M1'de ayrı `docgrain_domain.canonical` v0.1 contract'ı eklendi. Legacy `models.py` ingestion/API sözleşmeleri olarak korunur; canonical model onlardan otomatik üretilmez. Pydantic core JSON Schema bu modelden üretilir; kullanıcı/domain schema ayrı ve yalnızca explicit validator ile değerlendirilir. `jsonschema` yalnızca `docgrain-domain[validation]` opsiyonel extra'sındadır. Parser/provider SDK bağımlılıkları core modele eklenmez.

M0 contract düzeltmesi: ölçülmeyen `Page.confidence` ve probe yapılmayan `ProviderHealth.healthy` null olabilir. Model varlığı, ilgili extraction/projection'ın implement edildiğini göstermez.
