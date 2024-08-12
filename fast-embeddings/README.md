# Fast Embeddings

AlloyDB provides a very useful [embedding() function](https://cloud.google.com/alloydb/docs/ai/work-with-embeddings#embedding-generation) that creates embeddings directly in the database. However, this function does not always perform well when generating large batches of embeddings.

This snippet provides alternative approaches to quickly generating embeddings to speed up an initial bulk load. See the notebooks within this folder for more details. 