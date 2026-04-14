module github.com/antflydb/search-benchmark-game/engines/antfly-go-bleve

go 1.26

require github.com/blevesearch/bleve/v2 v2.5.7

require (
	github.com/RoaringBitmap/roaring/v2 v2.15.0 // indirect
	github.com/ajroetker/go-highway v0.0.12 // indirect
	github.com/axiomhq/hyperloglog v0.2.6 // indirect
	github.com/bits-and-blooms/bitset v1.24.4 // indirect
	github.com/blevesearch/bleve_index_api v1.3.4 // indirect
	github.com/blevesearch/geo v0.2.5 // indirect
	github.com/blevesearch/go-faiss v1.0.28 // indirect
	github.com/blevesearch/go-porterstemmer v1.0.3 // indirect
	github.com/blevesearch/goleveldb v1.1.0 // indirect
	github.com/blevesearch/gtreap v0.1.1 // indirect
	github.com/blevesearch/mmap-go v1.2.0 // indirect
	github.com/blevesearch/scorch_segment_api/v2 v2.4.3 // indirect
	github.com/blevesearch/segment v0.9.1 // indirect
	github.com/blevesearch/snowballstem v0.9.0 // indirect
	github.com/blevesearch/stempel v0.2.0 // indirect
	github.com/blevesearch/upsidedown_store_api v1.0.2 // indirect
	github.com/blevesearch/vellum v1.2.0 // indirect
	github.com/blevesearch/zapx/v11 v11.4.3 // indirect
	github.com/blevesearch/zapx/v12 v12.4.3 // indirect
	github.com/blevesearch/zapx/v13 v13.4.3 // indirect
	github.com/blevesearch/zapx/v14 v14.4.3 // indirect
	github.com/blevesearch/zapx/v15 v15.4.3 // indirect
	github.com/blevesearch/zapx/v16 v16.3.1 // indirect
	github.com/blevesearch/zapx/v17 v17.0.3-0.20260311100439-7e7434b4f844 // indirect
	github.com/bmatcuk/doublestar/v4 v4.10.0 // indirect
	github.com/couchbase/ghistogram v0.1.0 // indirect
	github.com/couchbase/moss v0.3.0 // indirect
	github.com/dgryski/go-metro v0.0.0-20250106013310-edb8663e5e33 // indirect
	github.com/golang/snappy v1.0.0 // indirect
	github.com/json-iterator/go v1.1.12 // indirect
	github.com/kamstrup/intmap v0.5.2 // indirect
	github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd // indirect
	github.com/modern-go/reflect2 v1.0.2 // indirect
	github.com/mschoch/smat v0.2.0 // indirect
	go.etcd.io/bbolt v1.4.3 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
)

replace (
	github.com/blevesearch/bleve/v2 => github.com/antflydb/bleve/v2 v2.5.8-antfly002
	github.com/blevesearch/zapx/v17 => github.com/antflydb/zapx/v17 v17.0.2-antfly004
)
