import io
import base64
import os
import pdfplumber
from openai import AzureOpenAI

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def extract_from_pdf(file_bytes: bytes) -> str:
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


def extract_from_image(file_bytes: bytes, mime_type: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-12-01-preview",
    )
    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "This is a medical document image. Extract all text and medical information "
                            "from it exactly as it appears — including test names, values, reference ranges, "
                            "dates, doctor notes, diagnoses, and any other clinical data. "
                            "Return only the extracted content, no commentary."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content.strip()


def extract_medical_history(
    file_bytes: bytes, mime_type: str = "application/pdf"
) -> str:
    if mime_type in SUPPORTED_IMAGE_TYPES:
        text = extract_from_image(file_bytes, mime_type)
    else:
        text = extract_from_pdf(file_bytes)
    return text[:8000]
