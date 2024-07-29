<h1>Fast Embeddings</h1>

AlloyDB provides a very useful [embedding() function](https://cloud.google.com/alloydb/docs/ai/work-with-embeddings#embedding-generation) that creates embeddings directly in the database. However, this function does not perform well when generating large batches of embeddings.

This notebook walks you through generating [Vertex AI embeddings](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/text-embeddings-api) for the AlloyDB database used by the [GenWealth Demo App](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/sample-apps/genwealth). It uses [Beam](https://github.com/apache/beam/blob/master/examples/notebooks/beam-ml/data_preprocessing/vertex_ai_text_embeddings.ipynb) (optionally with a DataFlow runner) to significantly speed up the process of generating large batches of embeddings and storing them in AlloyDB vs using the native embedding() function.
