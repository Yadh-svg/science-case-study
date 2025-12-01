import streamlit as st
import yaml
from google import genai
from google.genai import types

# ---------------------------------------------------------
#  LOAD PROMPT FROM YAML
# ---------------------------------------------------------
def load_prompt_template(path: str = "prompt.yaml", key: str = "case_study_science") -> str:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get(key, "")

# ---------------------------------------------------------
#  STREAMLIT SETUP
# ---------------------------------------------------------
st.set_page_config(page_title="Science CBS Generator", layout="wide")
st.title("🔬 Science Case-Based Study Generator")

# Load prompt
template_prompt = load_prompt_template()

# Gemini Client
# Gemini Client
# api_key will be defined later in the layout
client = None

# ---------------------------------------------------------
#  USER INPUTS
# ---------------------------------------------------------
st.subheader("Enter CBS Input Details")

col1, col2 = st.columns(2)

with col1:
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key:
        client = genai.Client(api_key=api_key)
    
    grade = st.text_input("Grade")
    curriculum = st.text_input("Curriculum", "CBSE")
    subject = st.text_input("Subject", "Science")
    chapter = st.text_input("Chapter / Unit")

with col2:
    topic = st.text_input("Topic (one or more)")
    concepts = st.text_area("Concepts in Chapter")
    num_questions = st.number_input("Number of CBS Questions", 1, 20, 1)

# Domain input
domain = st.selectbox(
    "Select Science Domain",
    ["Life Science", "Physical Science", "Earth Science", "Environmental Science"]
)

# ---------------------------------------------------------
#  GENERATE CBS
# ---------------------------------------------------------
if st.button("✨ Generate Science CBS"):
    if not client:
        st.error("Please enter a valid API Key first.")
    else:
        with st.spinner("Generating using Gemini 2.5 Pro…"):

            # Fill in placeholders
            final_prompt = (
                template_prompt
                    .replace("{{Grade}}", grade)
                    .replace("{{Curriculam}}", curriculum)
                    .replace("{{Subject}}", subject)
                    .replace("{{Chapter}}", chapter)
                    .replace("{{Topic}}", topic)
                    .replace("{{Concepts}}", concepts)
                    .replace("{{Domain}}", domain)
                    .replace("{{Number_of_questions}}", str(num_questions))
            )

            # Gemini call
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=final_prompt
            )

        st.success("✔ CBS Generated Successfully!")
        st.markdown("### 📘 Output")
        st.markdown(response.text)
