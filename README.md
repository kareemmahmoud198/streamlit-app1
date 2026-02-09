# Trading Card Grader AI

An AI-powered tool that evaluates trading cards from eBay listings or uploaded photos and estimates potential PSA grades based on image analysis.

## Features

- **eBay Image Extraction**: Paste an eBay listing URL to automatically pull all card images (highest available quality)
- **Manual Photo Upload**: Upload your own card photos (PNG, JPG, JPEG, WEBP) for analysis
- **AI Vision Analysis**: Uses OpenAI GPT-4o to analyze card condition based on PSA grading standards
- **Structured Grading Report**:
  - Estimated PSA grade (single number + range)
  - PSA 10 probability percentage
  - Confidence level (Low / Medium / High)
  - Centering analysis (front and back with estimated ratios)
  - Corner condition (whitening, softness, bends)
  - Edge condition (chipping, roughness, wear)
  - Surface condition (scratches, print lines, dents, stains)
  - List of missing or unclear photo angles
  - Key issues that limit the grade
  - Detailed analysis notes
  - Final recommendation: **Send for Grading**, **Hold**, or **Pass**

## Prerequisites

- Python 3.8 or higher
- OpenAI API key with GPT-4o access (get one at https://platform.openai.com/api-keys)

## Installation

1. **Clone or download this project**

2. **Install required packages**:
   ```
   pip install -r requirements.txt
   ```

3. **Set up your OpenAI API key**:
   - Create a file named `.env` in the project root
   - Add your API key:
     ```
     OPENAI_API_KEY=your_api_key_here
     ```

## Usage

1. **Start the application**:
   ```
   streamlit run app.py
   ```

2. The app opens in your browser at http://localhost:8501

3. **Analyze a card**:

   **Option A -- eBay URL**
   - Go to the "eBay URL" tab
   - Paste the eBay listing URL
   - Click "Fetch Images from eBay"
   - Review the extracted images
   - Click "Analyze Card"

   **Option B -- Upload Photos**
   - Go to the "Upload Photos" tab
   - Upload one or more card images
   - Click "Analyze Card"

4. Review the grading report

## How It Works

1. **Image Collection**: Images are extracted from the eBay listing HTML (highest resolution available: s-l1600) or uploaded manually.

2. **Image Preparation**: Images are resized (max 1200px) and compressed to JPEG while preserving enough detail for accurate grading. If there are many images, quality is reduced slightly to fit within API limits.

3. **AI Analysis**: All images are sent together in a single request to OpenAI GPT-4o with a professional grading prompt. The AI evaluates centering, corners, edges, and surface based on official PSA standards.

4. **Fallback Handling**: If the request is too large (many high-resolution images), the tool automatically splits into a two-pass analysis and combines the results conservatively.

5. **Report Generation**: The AI response is parsed and displayed in a structured, easy-to-read format with color-coded recommendations.

## Recommendation Guide

| Recommendation     | Meaning                                                          |
|--------------------|------------------------------------------------------------------|
| Send for Grading   | Card appears PSA 8 or higher -- worth submitting for grading     |
| Hold               | Borderline condition (PSA 7-8) or photos insufficient to decide  |
| Pass               | Clear issues visible that would result in PSA 6 or below         |


## Tech Stack

- **Frontend**: Streamlit
- **AI Model**: OpenAI GPT-4o (vision)
- **Image Processing**: Pillow (PIL)
- **Web Scraping**: BeautifulSoup4 + Requests

