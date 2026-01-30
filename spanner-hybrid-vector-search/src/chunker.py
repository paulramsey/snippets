import re
import os
import io
import datetime
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Tuple
from pypdf import PdfReader, PdfWriter
from google.cloud import documentai

class BaseChunker:
    def chunk(self, file_path: str, mime_type: str) -> List[Tuple[str, Dict[str, Any]]]:
        raise NotImplementedError
    
    def _enrich_metadata(self, chunks: List[Tuple[str, Dict[str, Any]]], file_path: str):
        """Adds common metadata to all chunks."""
        total_chunks = len(chunks)
        timestamp = datetime.datetime.now().isoformat()
        file_name = os.path.basename(file_path)
        
        enriched = []
        for text, meta in chunks:
            new_meta = meta.copy()
            new_meta["file_name"] = file_name
            new_meta["extracted_at"] = timestamp
            new_meta["total_chunks"] = total_chunks
            enriched.append((text, new_meta))
        return enriched

class XmlChunker(BaseChunker):
    def chunk(self, file_path: str, mime_type: str) -> List[Tuple[str, Dict[str, Any]]]:
        chunks = []
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            root_meta = dict(root.attrib)
            
            def _traverse(elem, ancestors):
                text = (elem.text or "").strip()
                if len(text) > 5:
                    spec_name = None
                    for tag, attrib in reversed(ancestors):
                         if tag == "spec" and "name" in attrib:
                             spec_name = attrib["name"]
                             break
                    
                    meta = {
                        "tag": elem.tag,
                        "root_attrib": str(root_meta),
                        "spec_name": spec_name,
                        "attrib": str(elem.attrib)
                    }
                    chunks.append((text, meta))
                
                current_ancestor = (elem.tag, elem.attrib)
                for child in elem:
                    _traverse(child, ancestors + [current_ancestor])

            _traverse(root, [])
        except Exception as e:
            print(f"Error parsing XML: {e}")
            
        return self._enrich_metadata(chunks, file_path)

class HtmlChunker(BaseChunker):
    def chunk(self, file_path: str, mime_type: str) -> List[Tuple[str, Dict[str, Any]]]:
        chunks = []
        try:
            from bs4 import BeautifulSoup
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
            
            # Elements to extract text from
            tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'td']
            
            current_text = ""
            current_meta = {"tags": []}
            target_size = 1000
            
            for element in soup.find_all(tags):
                text = element.get_text(strip=True)
                if not text:
                    continue
                
                # Simple aggregation
                if len(current_text) + len(text) < target_size:
                    if current_text:
                        current_text += "\n\n" + text
                    else:
                        current_text = text
                    current_meta["tags"].append(element.name)
                else:
                    # Flush current chunk
                    if current_text:
                        chunks.append((current_text, {"tags": list(set(current_meta["tags"])), "type": "aggregated_html"}))
                    
                    # Start new chunk
                    current_text = text
                    current_meta = {"tags": [element.name]}

            # Flush remaining
            if current_text:
                chunks.append((current_text, {"tags": list(set(current_meta["tags"])), "type": "aggregated_html"}))
                
        except Exception as e:
            print(f"Error parsing HTML: {e}")
            
        return self._enrich_metadata(chunks, file_path)

class DocumentAIChunker(BaseChunker):
    def __init__(self, project_id: str, location: str, processor_id: str):
        self.location = location
        self.client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        self.resource_name = self.client.processor_path(project_id, location, processor_id)

    def chunk(self, file_path: str, mime_type: str) -> List[Tuple[str, Dict[str, Any]]]:
        chunks = []
        try:
            # Check if PDF splitting is needed (only for PDF)
            if mime_type == "application/pdf":
                try:
                    reader = PdfReader(file_path)
                    total_pages = len(reader.pages)
                    if total_pages > 15:
                        return self._chunk_large_pdf(reader, mime_type, file_path)
                except Exception as e:
                    print(f"Error reading PDF for splitting check: {e}")
                    # Fallthrough to standard processing if read fails or not split needed

            # Standard processing (small PDF)
            with open(file_path, "rb") as f:
                content = f.read()
            chunks = self._process_batch(content, mime_type, 0)
        
        except Exception as e:
             print(f"Error calling Document AI: {e}")
             return []
        
        return self._enrich_metadata(chunks, file_path)

    def _chunk_large_pdf(self, reader, mime_type, file_path):
        chunks = []
        total_pages = len(reader.pages)
        batch_size = 15
        
        for i in range(0, total_pages, batch_size):
            writer = PdfWriter()
            batch_pages = reader.pages[i : i + batch_size]
            for p in batch_pages:
                writer.add_page(p)
            
            with io.BytesIO() as batch_stream:
                writer.write(batch_stream)
                batch_content = batch_stream.getvalue()
                
                batch_chunks = self._process_batch(batch_content, mime_type, offset_page=i)
                chunks.extend(batch_chunks)
        
        return self._enrich_metadata(chunks, file_path)

    def _process_batch(self, content: bytes, mime_type: str, offset_page: int) -> List[Tuple[str, Dict[str, Any]]]:
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
        request = documentai.ProcessRequest(name=self.resource_name, raw_document=raw_document)
        result = self.client.process_document(request=request)
        document = result.document

        chunks = []
        def get_text(text_anchor):
            try:
                full_text = ""
                for segment in text_anchor.text_segments:
                    full_text += document.text[segment.start_index : segment.end_index]
                return full_text.strip()
            except:
                return ""

        if document.pages:
            for page in document.pages:
                actual_page_num = page.page_number + offset_page
                
                found_something = False
                
                # Try paragraphs
                for paragraph in page.paragraphs:
                    text = get_text(paragraph.layout.text_anchor)
                    if len(text) > 10:
                        found_something = True
                        metadata = {
                            "page_number": actual_page_num,
                            "type": "paragraph"
                        }
                        chunks.append((text, metadata))
                
                # Try blocks if no paragraphs
                if not found_something:
                     for block in page.blocks:
                        text = get_text(block.layout.text_anchor)
                        if len(text) > 10:
                            found_something = True
                            metadata = {
                                "page_number": actual_page_num,
                                "type": "block"
                            }
                            chunks.append((text, metadata))

        return chunks

def get_chunker(mime_type: str, project_id: str, location: str, processor_id: str) -> BaseChunker:
    if mime_type == "application/pdf":
        if "/" in processor_id:
            processor_id = processor_id.split("/")[-1]
        return DocumentAIChunker(project_id, location, processor_id)
    elif mime_type == "text/html":
        return HtmlChunker()
    elif mime_type in ["application/xml", "text/xml"]:
        return XmlChunker()
    else:
        raise ValueError(f"Unsupported mime type: {mime_type}")
