from spacy.language import Language
from spacy.tokens import Doc
import logging
import re
try:
    from spacy_layout import spaCyLayout
except ImportError:
    spaCyLayout = None
try:
    import layoutparser as lp
    import pdf2image
    import numpy as np
except ImportError:
    lp = None
    pdf2image = None
    np = None

def setup_spacy_extensions():
    """Setup custom SpaCy extensions."""
    if not Doc.has_extension("layout"):
        Doc.set_extension("layout", default=None)
    if not Doc.has_extension("paragraphs"):
        Doc.set_extension("paragraphs", default=[])
    if not Doc.has_extension("elements"):
        Doc.set_extension("elements", default=[])

@Language.component("layout_parser")
def layout_parser(doc: Doc) -> Doc:
    """Custom SpaCy component for layout parsing, supporting text and PDFs."""
    doc._.layout = doc
    doc._.paragraphs = []
    doc._.elements = []

    input_text = doc.text
    is_pdf = input_text.endswith('.pdf') and os.path.exists(input_text)

    if is_pdf and spaCyLayout:
        try:
            layout_doc = spaCyLayout(doc.vocab)(input_text)
            doc.text = layout_doc.text
            doc._.layout = layout_doc
            doc._.paragraphs = [p.text for p in layout_doc._.paragraphs if p.text.strip()] if hasattr(layout_doc._, 'paragraphs') else []
            doc._.elements = [e for e in layout_doc._.elements if e.text.strip()] if hasattr(layout_doc._, 'elements') else []
            if not doc._.paragraphs:
                # Fallback: split extracted text by newlines or periods
                paragraphs = [p.strip() for p in re.split(r'\n+|\.\s+', layout_doc.text) if p.strip()]
                doc._.paragraphs = paragraphs
                doc._.elements = [{"type": "paragraph" if not re.match(r'^\d+\.\s*', p) else "list_item", "text": re.sub(r'^\d+\.\s*', '', p)} for p in paragraphs]
            logging.info(f"Processed PDF with spacy-layout: {len(doc._.paragraphs)} paragraphs")
            return doc
        except Exception as e:
            logging.error(f"Failed to process PDF with spacy-layout: {e}")

    if is_pdf and lp and pdf2image and np:
        try:
            images = pdf2image.convert_from_path(input_text)
            text = ""
            elements = []
            ocr_agent = lp.TesseractAgent()
            for img in images:
                img_np = np.array(img)
                layout = lp.Detectron2LayoutModel(
                    config_path="lp://PubLayNet/faster_rcnn_R_50_FPN_3x/config",
                    label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"},
                    extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.8]
                ).detect(img_np)
                text_blocks = lp.Layout([b for b in layout if b.type in ["Text", "List"]])
                for block in text_blocks:
                    segment_image = block.pad(left=5, right=5, top=5, bottom=5).crop_image(img_np)
                    block_text = ocr_agent.detect(segment_image)
                    text += block_text + "\n"
                    elements.append({"type": block.type, "text": block_text})
            doc.text = text
            paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
            doc._.paragraphs = paragraphs
            doc._.elements = [{"type": "paragraph" if not re.match(r'^\d+\.\s*', p) else "list_item", "text": re.sub(r'^\d+\.\s*', '', p)} for p in paragraphs]
            logging.info(f"Processed PDF with layoutparser: {len(doc._.paragraphs)} paragraphs")
            return doc
        except Exception as e:
            logging.error(f"Failed to process PDF with layoutparser: {e}")

    # Text-based layout parsing
    # Split by newlines or periods to handle PDF-extracted text without newlines
    paragraphs = [p.strip() for p in re.split(r'\n+|\.\s+', input_text) if p.strip()]
    elements = []
    for p in paragraphs:
        if re.match(r'^\d+\.\s*', p):
            elements.append({"type": "list_item", "text": re.sub(r'^\d+\.\s*', '', p)})
        else:
            elements.append({"type": "paragraph", "text": p})
    doc._.paragraphs = paragraphs
    doc._.elements = elements
    logging.info(f"Processed text with layout_parser: {len(paragraphs)} paragraphs")
    
    return doc