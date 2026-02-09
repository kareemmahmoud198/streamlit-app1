import streamlit as st
import requests
from bs4 import BeautifulSoup
import openai
import base64
from io import BytesIO
from PIL import Image
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Page config
st.set_page_config(
    page_title="Trading Card Grader AI",
    page_icon="",
    layout="wide"
)

# Custom CSS (same as before)
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .sub-header {
        text-align: center;
        color: #666;
        margin-bottom: 2rem;
    }
    .grade-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 2rem;
        border-radius: 15px;
        text-align: center;
        margin: 1rem 0;
    }
    .grade-number {
        font-size: 4rem;
        font-weight: bold;
    }
    .section-header {
        color: #1E88E5;
        font-size: 1.5rem;
        font-weight: bold;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
        border-bottom: 2px solid #1E88E5;
        padding-bottom: 0.5rem;
    }
    .recommendation-pass {
        background-color: #ff4444;
        color: white;
        padding: 1rem;
        border-radius: 10px;
        font-weight: bold;
    }
    .recommendation-hold {
        background-color: #ffaa00;
        color: white;
        padding: 1rem;
        border-radius: 10px;
        font-weight: bold;
    }
    .recommendation-grade {
        background-color: #00C851;
        color: white;
        padding: 1rem;
        border-radius: 10px;
        font-weight: bold;
    }
    .analysis-section {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
        border-left: 4px solid #1E88E5;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'images' not in st.session_state:
    st.session_state.images = []
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

def extract_ebay_images(url):
    """Extract images from eBay listing using multiple fallback methods"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        image_urls = []
        
        # Method 1: ux-image-carousel-item (most common)
        carousel_items = soup.find_all('div', class_='ux-image-carousel-item')
        for item in carousel_items:
            img = item.find('img')
            if img:
                for attr in ['data-zoom-src', 'data-src', 'src']:
                    src = img.get(attr)
                    if src and 'ebayimg.com' in src:
                        image_urls.append(src)
                        break
        
        # Method 2: Look for picture tags
        if not image_urls:
            pictures = soup.find_all('picture')
            for pic in pictures:
                img = pic.find('img')
                if img:
                    for attr in ['src', 'data-src', 'data-zoom-src']:
                        src = img.get(attr)
                        if src and 'ebayimg.com' in src:
                            image_urls.append(src)
                            break
        
        # Method 3: Find all img tags with ebayimg
        if not image_urls:
            all_imgs = soup.find_all('img')
            for img in all_imgs:
                for attr in ['src', 'data-src', 'data-zoom-src']:
                    src = img.get(attr)
                    if src and 'ebayimg.com' in src and 's-l' in src:
                        image_urls.append(src)
                        break
        
        # Clean and upgrade URLs to highest quality
        cleaned_urls = []
        for img_url in image_urls:
            for size in ['s-l50', 's-l100', 's-l225', 's-l300', 's-l400', 's-l500', 
                        's-l640', 's-l960', 's-l1200']:
                if size in img_url:
                    img_url = img_url.replace(size, 's-l1600')
                    break
            
            if 'ebayimg.com' in img_url and 's-l' in img_url:
                cleaned_urls.append(img_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for img_url in cleaned_urls:
            if img_url not in seen:
                seen.add(img_url)
                unique_urls.append(img_url)
        
        result = unique_urls[:10]
        
        if not result:
            st.warning("Could not extract images from this eBay listing. The page structure may have changed. Please try manual upload instead.")
        
        return result
        
    except Exception as e:
        st.error(f"Error extracting images: {str(e)}")
        st.info("Tip: Copy and paste the direct eBay item page URL, not a search results page.")
        return []

def download_image(url):
    """Download image from URL"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e:
        st.error(f"Error downloading image: {str(e)}")
        return None


def prepare_image_for_api(img, max_dimension=1200, quality=85):
    """Prepare a single image for the API"""
    img_copy = img.copy()
    img_copy.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    
    if img_copy.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img_copy.size, (255, 255, 255))
        if img_copy.mode == 'P':
            img_copy = img_copy.convert('RGBA')
        if img_copy.mode in ('RGBA', 'LA'):
            background.paste(img_copy, mask=img_copy.split()[-1])
            img_copy = background
    
    buffered = BytesIO()
    img_copy.save(buffered, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()


def analyze_card_with_openai(images, api_key):
    """
    Analyze trading card images using OpenAI GPT-4o with detailed, conversational output
    that matches ChatGPT's analysis style
    """
    try:
        client = openai.OpenAI(api_key=api_key)

        # New system prompt that encourages detailed, conversational analysis
        system_message = """You are an expert PSA card grader with years of experience. You provide detailed, thorough analysis similar to how you would explain your assessment to a collector in person.

Your analysis should be:
- Conversational and detailed, not just bullet points
- Specific about what you see in each area (centering, corners, edges, surface)
- Honest about both strengths and weaknesses
- Clear about which issues matter most for the grade
- Realistic about PSA grading standards

PSA 10 requirements:
- Centering: 50/50 to 60/40 front, 55/45 to 75/25 back
- Corners: All four corners must be sharp with no visible wear
- Edges: Clean, no chipping or roughness
- Surface: No print defects, scratches, or other imperfections

Remember: PSA is STRICT. One small flaw can drop a card from a 10 to a 9. Be thorough and realistic."""

        # New user prompt that asks for detailed analysis
        user_message = [
            {
                "type": "text",
                "text": """Please provide a detailed grading analysis of this trading card. Structure your response as follows:

**Card:** [Identify the card if possible]

**What matters most here:** [List the key factors: corners, edges, centering, surface, auto quality if applicable]

---

**Front**

**Centering**
- Describe the left/right and top/bottom centering
- Give specific measurements if possible (e.g., "52/48")
- Note if it meets PSA 10 standards

**Corners**
- Examine each corner individually (top left, top right, bottom left, bottom right)
- Describe what you see (sharp, slight softness, whitening, etc.)
- Be specific about any issues

**Edges**
- Check all four edges
- Note any chipping, silvering, or roughness
- Mention if chrome/foil edges look clean

**Surface (Front)**
- Check for print lines, scratches, indentations
- Note the quality of the chrome/finish
- Comment on centering of the auto if present
- Assess auto ink quality (bold, clean, streaking, bubbling, etc.)

---

**Back**

**Centering**
- Describe back centering with measurements
- Note PSA 10 acceptability

**Corners / Edges**
- Compare to front
- Note any additional issues or if back is cleaner

**Surface (Back)**
- Check for scratches, print lines, or defects
- Note any issues

---

**Serial Number Area** (if applicable)
- Check for foil cracking or indenting around numbers

---

**Overall Probability**
Floor: PSA [X]
Ceiling: PSA [X]  
Most Likely: PSA [X] if the grader is reasonable

Why not guaranteed 10? [Explain the specific issue(s)]

---

**Auto Grade** (if applicable)
If you dual grade:
- Card: [X]-10 range
- Auto: Very likely [X]

---

**Market Reality (Important)**
[Discuss the value difference between grades for this specific card/player]
[Give recommendation: "submit candidate" or "hold" or "pass"]

---

**Prep Advice Before Sending**
- [List specific prep steps]

Be thorough, conversational, and specific. Point out everything you notice."""
            }
        ]

        # Attach all images
        for img in images:
            img_b64 = prepare_image_for_api(img, max_dimension=1200, quality=85)
            user_message.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "high"
                }
            })

        # Make API call
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,
            max_tokens=3000
        )

        result_text = response.choices[0].message.content
        
        # Parse the response to extract key information
        return parse_detailed_response(result_text)

    except Exception as e:
        return {"error": str(e), "raw_response": str(e)}


def parse_detailed_response(result_text):
    """
    Parse the detailed conversational response and extract key metrics
    while preserving the full detailed text
    """
    try:
        # Extract grade estimates using regex
        import re
        
        result = {
            "full_analysis": result_text,
            "estimated_grade_single": None,
            "estimated_grade_range": None,
            "recommendation": None,
            "confidence": "Medium"
        }
        
        # Try to extract "Most Likely: PSA X"
        most_likely = re.search(r'Most Likely:?\s*PSA\s*(\d+)', result_text, re.IGNORECASE)
        if most_likely:
            result["estimated_grade_single"] = int(most_likely.group(1))
        
        # Try to extract grade range
        floor = re.search(r'Floor:?\s*PSA\s*(\d+)', result_text, re.IGNORECASE)
        ceiling = re.search(r'Ceiling:?\s*PSA\s*(\d+)', result_text, re.IGNORECASE)
        
        if floor and ceiling:
            result["estimated_grade_range"] = f"PSA {floor.group(1)}-{ceiling.group(1)}"
        elif result["estimated_grade_single"]:
            grade = result["estimated_grade_single"]
            result["estimated_grade_range"] = f"PSA {max(grade-1, 1)}-{min(grade+1, 10)}"
        
        # Extract recommendation
        if re.search(r'submit\s+candidate', result_text, re.IGNORECASE):
            result["recommendation"] = "Send for Grading"
        elif re.search(r'\bhold\b', result_text, re.IGNORECASE):
            result["recommendation"] = "Hold"
        elif re.search(r'\bpass\b', result_text, re.IGNORECASE):
            result["recommendation"] = "Pass"
        else:
            # Infer from grade
            if result["estimated_grade_single"]:
                if result["estimated_grade_single"] >= 9:
                    result["recommendation"] = "Send for Grading"
                elif result["estimated_grade_single"] >= 7:
                    result["recommendation"] = "Hold"
                else:
                    result["recommendation"] = "Pass"
        
        return result
        
    except Exception as e:
        return {
            "full_analysis": result_text,
            "error": f"Parsing error: {str(e)}"
        }


def display_grading_report(result):
    """Display the detailed grading report"""
    if "error" in result and not result.get("full_analysis"):
        st.error(f"Analysis Error: {result['error']}")
        return
    
    # Display grade summary box if we have estimates
    if result.get("estimated_grade_single"):
        st.markdown('<div class="grade-box">', unsafe_allow_html=True)
        st.markdown(f'<div class="grade-number">PSA {result["estimated_grade_single"]}</div>', unsafe_allow_html=True)
        if result.get("estimated_grade_range"):
            st.markdown(f'**Estimated Range:** {result["estimated_grade_range"]}', unsafe_allow_html=True)
        st.markdown(f'**Confidence:** {result.get("confidence", "Medium")}', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Display full detailed analysis
    st.markdown('<div class="section-header">Detailed Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
    st.markdown(result.get("full_analysis", "No analysis available"))
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Display recommendation
    if result.get("recommendation"):
        st.markdown('<div class="section-header">Final Recommendation</div>', unsafe_allow_html=True)
        recommendation = result["recommendation"]
        if recommendation == "Send for Grading":
            st.markdown(f'<div class="recommendation-grade">{recommendation}</div>', unsafe_allow_html=True)
        elif recommendation == "Hold":
            st.markdown(f'<div class="recommendation-hold">{recommendation}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="recommendation-pass">{recommendation}</div>', unsafe_allow_html=True)


# Main App
st.markdown('<div class="main-header"> Trading Card Grader AI</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Detailed PSA grading analysis from eBay listings or uploaded photos</div>', unsafe_allow_html=True)

# API Key - Get from Streamlit Cloud secrets
try:
    # Try to get from Streamlit Cloud secrets first (production)
    api_key = st.secrets["openai"]["api_key"]
except (KeyError, FileNotFoundError):
    # Fallback to .env for local development
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        st.error(" API Key not configured. Please contact the administrator.")
        st.stop()

st.markdown("---")

# Main content tabs
tab1, tab2 = st.tabs([" eBay URL", " Upload Photos"])

with tab1:
    st.subheader("Enter eBay Listing URL")
    ebay_url = st.text_input("eBay URL:", placeholder="https://www.ebay.com/itm/...")
    
    if st.button("Fetch Images from eBay", key="fetch_btn"):
        if not ebay_url:
            st.warning("Please enter an eBay URL")
        else:
            with st.spinner("Fetching images from eBay..."):
                image_urls = extract_ebay_images(ebay_url)
                
                if image_urls:
                    st.success(f"Found {len(image_urls)} images!")
                    
                    st.session_state.images = []
                    cols = st.columns(4)
                    for idx, img_url in enumerate(image_urls):
                        img = download_image(img_url)
                        if img:
                            st.session_state.images.append(img)
                            with cols[idx % 4]:
                                st.image(img, caption=f"Image {idx+1}", use_container_width=True)
                else:
                    st.error("No images found. Please check the URL or try manual upload.")

with tab2:
    st.subheader("Upload Card Photos")
    uploaded_files = st.file_uploader(
        "Choose images...", 
        type=['png', 'jpg', 'jpeg', 'webp'],
        accept_multiple_files=True
    )
    
    if uploaded_files:
        st.session_state.images = []
        cols = st.columns(4)
        for idx, file in enumerate(uploaded_files):
            img = Image.open(file)
            st.session_state.images.append(img)
            with cols[idx % 4]:
                st.image(img, caption=f"Uploaded {idx+1}", use_container_width=True)

# Analysis Section
st.markdown("---")

if st.session_state.images:
    st.subheader(f" Ready to analyze {len(st.session_state.images)} images")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button(" Analyze Card", key="analyze_btn", use_container_width=True):
            if not api_key:
                st.error("Please enter your OpenAI API key above to analyze the card.")
            else:
                with st.spinner("🤖 Analyzing card images... This may take 30-60 seconds for detailed analysis..."):
                    result = analyze_card_with_openai(st.session_state.images, api_key)
                    st.session_state.analysis_result = result

# Display results
if st.session_state.analysis_result:
    st.markdown("---")
    st.markdown("##  Grading Report")
    display_grading_report(st.session_state.analysis_result)
