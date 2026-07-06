import chromadb
from chromadb.config import Settings
from app.config import settings


class ChromaStore:
    def __init__(self):
        self.client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=Settings(
                anonymized_telemetry=False,
                chroma_product_telemetry_impl="app.vector_store.noop_chroma_telemetry.NoOpTelemetry",
                chroma_telemetry_impl="app.vector_store.noop_chroma_telemetry.NoOpTelemetry",
            ),
        )
        self.collection = self.client.get_or_create_collection("course_resources")

    def get_collection(self):
        return self.collection


chroma_store = ChromaStore()
