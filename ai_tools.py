import os
import google.generativeai as genai
from dotenv import load_dotenv
from PyPDF2 import PdfReader
import io
import random

load_dotenv()

# --- AI Configuration ---
def get_gemini_model():
    try:
        api_key = os.getenv('GOOGLE_API_KEY')
        if api_key:
            genai.configure(api_key=api_key)
            # Use the latest Flash model for speed and cost
            return genai.GenerativeModel('gemini-2.5-flash')
        else:
            print("[!] Warning: GOOGLE_API_KEY missing.")
            return None
    except Exception as e:
        print(f"[!] Could not initialize Gemini model: {e}")
        return None

# --- PDF Extraction (Restored for Upload Analysis) ---
def extract_text_from_pdf_strategically(s3_client, bucket_name, s3_key):
    """
    Downloads a PDF from S3 and extracts text from strategic pages
    (First 3, Middle 3, Last 3) to get a good overview.
    """
    try:
        s3_object = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        s3_file_content_bytes = s3_object['Body'].read()
        pdf_stream = io.BytesIO(s3_file_content_bytes)
        
        reader = PdfReader(pdf_stream)
        num_pages = len(reader.pages)
        text = ""
        
        if num_pages == 0:
            return None

        # Sample specific pages to get the "gist" of the book
        pages_to_read = []
        
        # First 3 pages (Intro)
        pages_to_read.extend(range(0, min(3, num_pages)))
        
        # Middle 3 pages (Content)
        if num_pages > 10:
            mid = num_pages // 2
            pages_to_read.extend(range(mid, mid + 3))
            
        # Last 3 pages (Conclusion/Index)
        if num_pages > 6:
            pages_to_read.extend(range(num_pages - 3, num_pages))
            
        # Remove duplicates and sort
        pages_to_read = sorted(list(set(pages_to_read)))
        
        for i in pages_to_read:
            if i < num_pages:
                page_text = reader.pages[i].extract_text()
                if page_text:
                    text += f"\n--- Page {i+1} ---\n{page_text}\n"
        
        return text
    except Exception as e:
        print(f"[!] Error extracting PDF text: {e}")
        return None

# --- Feature 1: Upload Analysis (Restored) ---
def generate_starter_layers(ebook, s3_client, bucket_name):
    model = get_gemini_model()
    if not model:
        return {"error": "AI model not available."}
        
    text = extract_text_from_pdf_strategically(s3_client, bucket_name, ebook.file_path)
    if not text:
        # Fallback if text extraction fails
        return {"success": True, "layers": ["General Notes", "Key Quotes"]}

    prompt = f"""
    Analyze this text from the book "{ebook.title}" by {ebook.author_name}.
    
    Text Sample:
    {text[:8000]}
    
    Generate 3-4 short, engaging "Annotation Layer" names for a study group reading this book.
    Examples: "Character Motives", "Historical Context", "Philosophical Themes".
    
    Return ONLY a Python list of strings. Example: ["Theme A", "Theme B"]
    """
    
    try:
        response = model.generate_content(prompt)
        import ast
        # Clean up code blocks if the AI adds them
        clean_text = response.text.replace('```python', '').replace('```', '').strip()
        layers = ast.literal_eval(clean_text)
        return {"success": True, "layers": layers}
    except Exception as e:
        print(f"[!] AI Layer Gen Error: {e}")
        return {"success": True, "layers": ["General Discussion", "Key Themes"]}

# --- Feature 2: Ask AI About User Note (New) ---
def analyze_user_note(user_note, book_title, book_author, book_context):
    """
    Answers a user's question using the book's text as context.
    """
    model = get_gemini_model()
    if not model:
        return "AI is currently offline."

    prompt = f"""
    You are an expert literary assistant.
    
    BOOK INFORMATION:
    Title: "{book_title}"
    Author: "{book_author}"
    
    BOOK CONTENT EXCERPTS (Use this to answer):
    ---
    {book_context[:30000]} 
    ---
    (Note: This is a strategic sample of the book's text).

    USER'S QUESTION:
    "{user_note}"
    
    YOUR TASK:
    Answer the user's question based on the book content provided above and your general knowledge of this book.
    - If the answer is in the text provided, quote it.
    - If the answer requires general knowledge about the book (plot, themes), provide it.
    - Keep the answer helpful and concise (max 4 sentences).
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"I couldn't answer that right now. ({str(e)})"

# --- Dummy Functions (To satisfy other imports if needed) ---
def check_book_genuineness(t, a, x): return "Genuine"
def categorize_book(t, c): return "None"
def summarize_annotations(l): return {"summary": "Disabled"}