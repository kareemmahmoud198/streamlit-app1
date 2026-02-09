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
    page_icon="TC",
    layout="wide"
)

# Custom CSS
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
                # Try multiple attributes
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
        
        # Method 4: Look in script tags for image URLs (JSON data)
        if not image_urls:
            scripts = soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and 'image' in data:
                        imgs = data['image']
                        if isinstance(imgs, str):
                            image_urls.append(imgs)
                        elif isinstance(imgs, list):
                            image_urls.extend(imgs)
                except:
                    pass
        
        # Clean and upgrade URLs to highest quality
        cleaned_urls = []
        for img_url in image_urls:
            # Upgrade to s-l1600 (highest quality)
            for size in ['s-l50', 's-l100', 's-l225', 's-l300', 's-l400', 's-l500', 
                        's-l640', 's-l960', 's-l1200']:
                if size in img_url:
                    img_url = img_url.replace(size, 's-l1600')
                    break
            
            # Only add if it's a product image
            if 'ebayimg.com' in img_url and 's-l' in img_url:
                cleaned_urls.append(img_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for img_url in cleaned_urls:
            if img_url not in seen:
                seen.add(img_url)
                unique_urls.append(img_url)
        
        result = unique_urls[:10]  # Limit to 10 images max
        
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
    """
    Prepare a single image for the API - resize and compress while keeping
    enough detail for accurate card grading.
    """
    img_copy = img.copy()
    img_copy.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    
    # Convert to RGB if needed (for JPEG encoding)
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


def analyze_card_with_openai(images, api_key, batch_size=5):
    """
    Analyze trading card images using OpenAI GPT-4o.
    Sends all images in a single request when possible.
    Falls back to two-pass approach only when request is too large.
    """
    try:
        client = openai.OpenAI(api_key=api_key)

        # Try sending all images at once first (best accuracy)
        # If more than batch_size, reduce quality to fit
        if len(images) <= batch_size:
            return _call_grading_api(client, images, max_dim=1200, quality=85)
        else:
            # More images: use slightly lower quality to fit in one request
            st.info(f"Processing {len(images)} images...")
            return _call_grading_api(client, images, max_dim=1000, quality=75)

    except openai.BadRequestError:
        # If request is too large, split into 2 passes
        st.warning("Images too large for single request. Running two-pass analysis...")
        return _two_pass_analysis(client, images)
    except Exception as e:
        return {"error": str(e)}


def _call_grading_api(client, images, max_dim=1200, quality=85):
    """
    Core API call: sends images with a structured sub-grade scoring prompt.
    """
    system_message = """You are a strict, experienced PSA card grader. You grade cards the same way 
PSA does: each sub-category (centering, corners, edges, surface) gets its own score, 
and the LOWEST sub-category score determines the final grade.

KEY PRINCIPLE: In PSA grading, the final grade is limited by the WORST category. 
A card with perfect surface but one soft corner is NOT a PSA 10 -- it is limited 
by the corner score.

PSA Sub-Grade Scale (use for each category):
  10 = Flawless in this category
   9 = One very minor flaw
   8 = A couple of minor flaws
   7 = Several minor flaws or one moderate flaw
   6 = Noticeable issues
   5 or below = Significant problems

PSA Centering Requirements:
  10: 50/50 to 60/40 front, 55/45 to 75/25 back
   9: 60/40 to 65/35 front, up to 90/10 back  
   8: 65/35 to 70/30 front, up to 90/10 back
   7: 70/30 to 75/25 front
   6 or below: worse than 75/25

PHOTO QUALITY RULE: These are eBay listing photos -- they are designed to make cards 
look good. Compressed images hide micro-defects (tiny corner whitening, hairline 
scratches, slight edge wear). If you cannot clearly confirm a category is flawless 
because photos lack the resolution or angle, you must cap that sub-grade at 8 maximum 
and note it as a photo limitation. Do NOT assume perfection when you simply cannot see 
enough detail."""

    user_message = [
        {
            "type": "text",
            "text": """Grade this trading card using PSA standards with sub-category scoring.

STEP 1 - Score each category individually (10 = perfect, 5 = significant issues):

  A. CENTERING: Measure border ratios on front (L/R, T/B) and back (L/R, T/B).
     Compare to PSA centering chart. Give a centering sub-grade.

  B. CORNERS: Inspect each of the 4 corners on front AND back individually.
     Look for: whitening, softness, dings, bends, rounding.
     The WORST corner determines the corner sub-grade.

  C. EDGES: Inspect all 4 edges on front AND back.
     Look for: chipping, roughness, whitening, nicks, foil peeling.
     The WORST edge determines the edge sub-grade.

  D. SURFACE: Inspect front AND back surfaces.
     Look for: scratches, print lines, indentations, stains, creases, wax, 
     fingerprints, factory defects, ink marks, scuffs.
     The WORST surface issue determines the surface sub-grade.

STEP 2 - Calculate final grade:
  Final grade = LOWEST sub-grade from the 4 categories above.
  (Example: centering=9, corners=7, edges=8, surface=9 --> final grade = 7)

STEP 3 - Determine recommendation based on the FINAL grade (not the best sub-grade):
  - "Send for Grading": Final grade is 9 or higher
  - "Hold": Final grade is 7 or 8
  - "Pass": Final grade is 6 or below

STEP 4 - Assess confidence:
  - "High": Clear close-up photos of all angles (front, back, corners, edges)
  - "Medium": Decent photos but missing some close-ups or angles
  - "Low": Only distant/blurry photos, many areas cannot be evaluated

Return ONLY this JSON:
{
    "centering_sub_grade": 8,
    "corners_sub_grade": 7,
    "edges_sub_grade": 8,
    "surface_sub_grade": 9,
    "estimated_grade_single": 7,
    "estimated_grade_range": "PSA 7-8",
    "psa_10_probability": 0.02,
    "centering_front": "58/42 L-R, 52/48 T-B. Slightly left-heavy.",
    "centering_back": "65/35 L-R, 55/45 T-B. Noticeably off-center left.",
    "corners": "TL: sharp. TR: sharp. BL: slight softness. BR: minor whitening visible.",
    "edges": "Top: clean. Bottom: clean. Left: minor roughness. Right: clean.",
    "surface": "Front: no visible scratches. Back: possible light surface wear near center.",
    "missing_angles": ["Close-up of bottom-left corner", "Edge detail shots"],
    "key_issues": ["Back centering 65/35 limits grade", "BL corner softness", "Left edge roughness"],
    "recommendation": "Hold",
    "confidence": "Medium",
    "detailed_notes": "Card is limited by back centering (65/35) and bottom-left corner softness. These cap the grade at PSA 7-8 range. Surface and front centering are strong but cannot overcome the weaker categories."
}

IMPORTANT: The final grade MUST equal the lowest sub-grade. Do not average them."""
        }
    ]

    # Attach all images
    for img in images:
        img_b64 = prepare_image_for_api(img, max_dimension=max_dim, quality=quality)
        user_message.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{img_b64}",
                "detail": "high"
            }
        })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        temperature=0.2,
        max_tokens=2000
    )

    result_text = response.choices[0].message.content
    return _parse_grading_response(result_text)


def _two_pass_analysis(client, images):
    """
    Fallback: split images into two halves, analyze each, 
    then ask the AI to combine findings.
    """
    mid = len(images) // 2
    first_half = images[:mid]
    second_half = images[mid:]

    st.write(f"Pass 1: Analyzing images 1-{mid}...")
    result1 = _call_grading_api(client, first_half, max_dim=1000, quality=75)
    if "error" in result1:
        return result1

    st.write(f"Pass 2: Analyzing images {mid+1}-{len(images)}...")
    result2 = _call_grading_api(client, second_half, max_dim=1000, quality=75)
    if "error" in result2:
        return result2

    # Combine: take the worse (lower) sub-grade for each category
    combined = result1.copy()
    
    # Take worst sub-grade from each category
    for key in ['centering_sub_grade', 'corners_sub_grade', 'edges_sub_grade', 'surface_sub_grade']:
        v1 = result1.get(key, 10)
        v2 = result2.get(key, 10)
        combined[key] = min(v1, v2)
    
    # Final grade = lowest sub-grade
    sub_grades = [combined.get(k, 10) for k in 
                  ['centering_sub_grade', 'corners_sub_grade', 'edges_sub_grade', 'surface_sub_grade']]
    final = min(sub_grades)
    combined['estimated_grade_single'] = final
    combined['estimated_grade_range'] = f"PSA {max(final-1, 1)}-{final}"
    
    p1 = result1.get('psa_10_probability', 0)
    p2 = result2.get('psa_10_probability', 0)
    combined['psa_10_probability'] = min(p1, p2)
    
    # Merge lists without duplicates
    issues1 = result1.get('key_issues', [])
    issues2 = result2.get('key_issues', [])
    combined['key_issues'] = list(dict.fromkeys(issues1 + issues2))
    
    missing1 = result1.get('missing_angles', [])
    missing2 = result2.get('missing_angles', [])
    combined['missing_angles'] = list(dict.fromkeys(missing1 + missing2))
    
    notes1 = result1.get('detailed_notes', '')
    notes2 = result2.get('detailed_notes', '')
    combined['detailed_notes'] = f"{notes1}\n\nAdditional observations: {notes2}"
    
    # Recommendation based on final grade
    if final >= 9:
        combined['recommendation'] = "Send for Grading"
    elif final >= 7:
        combined['recommendation'] = "Hold"
    else:
        combined['recommendation'] = "Pass"
    
    # Use lower confidence
    conf_priority = {"Low": 0, "Medium": 1, "High": 2}
    c1 = conf_priority.get(result1.get('confidence', 'Medium'), 1)
    c2 = conf_priority.get(result2.get('confidence', 'Medium'), 1)
    priority_to_conf = {0: "Low", 1: "Medium", 2: "High"}
    combined['confidence'] = priority_to_conf[min(c1, c2)]
    
    return combined


def _parse_grading_response(result_text):
    """Parse the AI response text into a structured result dict."""
    try:
        # Try to extract JSON from markdown code block
        if '```json' in result_text:
            json_start = result_text.find('```json') + 7
            json_end = result_text.find('```', json_start)
            json_text = result_text[json_start:json_end].strip()
        elif '```' in result_text:
            json_start = result_text.find('```') + 3
            json_end = result_text.find('```', json_start)
            json_text = result_text[json_start:json_end].strip()
        else:
            # Try to find JSON object directly
            start = result_text.find('{')
            end = result_text.rfind('}') + 1
            if start != -1 and end > start:
                json_text = result_text[start:end]
            else:
                json_text = result_text.strip()
        
        result = json.loads(json_text)
        
        # Validate required fields exist
        required_fields = ['estimated_grade_single', 'recommendation']
        for field in required_fields:
            if field not in result:
                return {"error": "Incomplete response from AI", "raw_response": result_text}
        
        return result
        
    except json.JSONDecodeError:
        return {"error": "Failed to parse AI response", "raw_response": result_text}


def display_grading_report(result):
    """Display the grading report in a nice format"""
    if "error" in result:
        st.error(f"Analysis Error: {result['error']}")
        if "raw_response" in result:
            st.text_area("Raw Response:", result['raw_response'], height=300)
        return
    
    # Validate: final grade must equal lowest sub-grade
    sub_grades = [
        result.get('centering_sub_grade'),
        result.get('corners_sub_grade'),
        result.get('edges_sub_grade'),
        result.get('surface_sub_grade')
    ]
    valid_sub_grades = [g for g in sub_grades if g is not None]
    if valid_sub_grades:
        lowest = min(valid_sub_grades)
        reported = result.get('estimated_grade_single', lowest)
        # Enforce: final grade cannot be higher than lowest sub-grade
        if reported > lowest:
            result['estimated_grade_single'] = lowest
            result['estimated_grade_range'] = f"PSA {max(lowest - 1, 1)}-{lowest}"
        # Enforce recommendation based on corrected grade
        grade = result['estimated_grade_single']
        if grade >= 9:
            result['recommendation'] = "Send for Grading"
        elif grade >= 7:
            result['recommendation'] = "Hold"
        else:
            result['recommendation'] = "Pass"
    
    # Main Grade Display
    st.markdown('<div class="grade-box">', unsafe_allow_html=True)
    st.markdown(f'<div class="grade-number">PSA {result.get("estimated_grade_single", "?")}</div>', unsafe_allow_html=True)
    st.markdown(f'**Estimated Range:** {result.get("estimated_grade_range", "N/A")}', unsafe_allow_html=True)
    st.markdown(f'**PSA 10 Probability:** {int(result.get("psa_10_probability", 0) * 100)}%', unsafe_allow_html=True)
    st.markdown(f'**Confidence:** {result.get("confidence", "N/A")}', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Sub-Grades Display
    if valid_sub_grades:
        st.markdown('<div class="section-header">Sub-Grade Scores</div>', unsafe_allow_html=True)
        sg_cols = st.columns(4)
        sub_grade_labels = [
            ("Centering", result.get('centering_sub_grade', 'N/A')),
            ("Corners", result.get('corners_sub_grade', 'N/A')),
            ("Edges", result.get('edges_sub_grade', 'N/A')),
            ("Surface", result.get('surface_sub_grade', 'N/A'))
        ]
        for i, (label, grade) in enumerate(sub_grade_labels):
            with sg_cols[i]:
                color = "#00C851" if grade >= 9 else "#ffaa00" if grade >= 7 else "#ff4444"
                st.markdown(f'<div style="text-align:center;padding:0.5rem;border-radius:8px;'
                           f'background-color:{color};color:white;font-weight:bold;">'
                           f'{label}<br><span style="font-size:1.5rem;">{grade}</span></div>',
                           unsafe_allow_html=True)
        
        st.caption("Final grade is determined by the lowest sub-grade score.")
    
    # Detailed Analysis
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="section-header">Centering</div>', unsafe_allow_html=True)
        st.write(f"**Front:** {result.get('centering_front', 'N/A')}")
        st.write(f"**Back:** {result.get('centering_back', 'N/A')}")
        
        st.markdown('<div class="section-header">Corners</div>', unsafe_allow_html=True)
        st.write(result.get('corners', 'N/A'))
        
        st.markdown('<div class="section-header">Edges</div>', unsafe_allow_html=True)
        st.write(result.get('edges', 'N/A'))
    
    with col2:
        st.markdown('<div class="section-header">Surface</div>', unsafe_allow_html=True)
        st.write(result.get('surface', 'N/A'))
        
        st.markdown('<div class="section-header">Key Issues</div>', unsafe_allow_html=True)
        issues = result.get('key_issues', [])
        if issues:
            for issue in issues:
                st.write(f"- {issue}")
        else:
            st.write("No major issues detected")
        
        st.markdown('<div class="section-header">Missing Angles</div>', unsafe_allow_html=True)
        missing = result.get('missing_angles', [])
        if missing:
            for angle in missing:
                st.write(f"- {angle}")
        else:
            st.write("All necessary angles covered")
    
    # Detailed Notes
    st.markdown('<div class="section-header">Detailed Analysis</div>', unsafe_allow_html=True)
    st.write(result.get('detailed_notes', 'N/A'))
    
    # Recommendation
    st.markdown('<div class="section-header">Final Recommendation</div>', unsafe_allow_html=True)
    recommendation = result.get('recommendation', 'N/A')
    if recommendation == "Send for Grading":
        st.markdown(f'<div class="recommendation-grade">{recommendation}</div>', unsafe_allow_html=True)
    elif recommendation == "Hold":
        st.markdown(f'<div class="recommendation-hold">{recommendation}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="recommendation-pass">{recommendation}</div>', unsafe_allow_html=True)

# Main App
st.markdown('<div class="main-header">Trading Card Grader AI</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Estimate PSA grades from eBay listings or uploaded photos</div>', unsafe_allow_html=True)

# API Key Input (check .env first, then allow manual input)
api_key_from_env = os.getenv('OPENAI_API_KEY')

st.markdown("---")
with st.expander("OpenAI API Key", expanded=not api_key_from_env):
    if api_key_from_env:
        st.success("API key loaded from .env file")
        use_env_key = st.checkbox("Use API key from .env file", value=True)
        if use_env_key:
            api_key = api_key_from_env
        else:
            api_key = st.text_input("Or enter API key manually:", type="password", key="manual_api_key")
    else:
        st.info("No API key found in .env file. Please enter your OpenAI API key below.")
        api_key = st.text_input("OpenAI API Key:", type="password", key="api_key_input", 
                                help="Get your API key from https://platform.openai.com/api-keys")

st.markdown("---")

# Main content tabs
tab1, tab2 = st.tabs(["eBay URL", "Upload Photos"])

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
                    
                    # Download and store images
                    st.session_state.images = []
                    cols = st.columns(4)
                    for idx, img_url in enumerate(image_urls):
                        img = download_image(img_url)
                        if img:
                            st.session_state.images.append(img)
                            with cols[idx % 4]:
                                st.image(img, caption=f"Image {idx+1}", use_column_width=True)
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
    st.subheader(f"Ready to analyze {len(st.session_state.images)} images")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("Analyze Card", key="analyze_btn", use_container_width=True):
            if not api_key:
                st.error("Please enter your OpenAI API key above to analyze the card.")
            else:
                with st.spinner("Analyzing card images... This may take 20-30 seconds..."):
                    result = analyze_card_with_openai(st.session_state.images, api_key)
                    st.session_state.analysis_result = result

# Display results
if st.session_state.analysis_result:
    st.markdown("---")
    st.markdown("## Grading Report")
    display_grading_report(st.session_state.analysis_result)
