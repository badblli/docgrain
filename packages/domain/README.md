# Domain contracts

Vendor-neutral Pydantic document/version/page/table/asset/chunk/job sözleşmeleri, ID helpers ve state helpers implement edilmiştir. Worker shared state machine'i henüz kullanmaz; çoğu content modeli demo/API contract düzeyindedir.

Bu package henüz Canonical Knowledge Model değildir. M1 ayrı onaydan sonra başlayacaktır. SDK/framework bağımlılıkları core modele eklenmez.

M0 contract düzeltmesi: ölçülmeyen `Page.confidence` ve probe yapılmayan `ProviderHealth.healthy` null olabilir. Model varlığı, ilgili extraction/projection'ın implement edildiğini göstermez.
